"""
bot/handlers/flow_accounts.py — Luồng bán Tài Khoản & Dịch vụ Nâng Cấp.

Flow account_stocked:
  Catalog → Chọn SP → Tạo order → Thanh toán → Auto-deliver từ kho
  (Xử lý bởi catalog.py._handle_standard_product + payment_poller._process_account_stocked)

Flow service_upgrade:
  Catalog → Chọn SP → FSM nhập thông tin (email/password) → Tạo order → Thanh toán
  → Admin xử lý thủ công (Live Chat)
"""
from __future__ import annotations
from datetime import timedelta
from html import escape
import json

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.callback_data.factories import UpgradeBackCB
from bot.keyboards.inline_kb import back_only_kb, categories_kb, payment_method_kb, products_kb
from bot.services.pricing_resolver import quote_non_api_product
from bot.utils.formatting import format_vnd
from bot.utils.order_code import generate_order_code
from bot.utils.time_utils import get_now_vn

from db.queries.categories import get_active_categories
from db.queries.orders import create_order, update_order_status
from db.queries.products import get_active_products_by_category, get_product_by_id
from db.queries.settings import get_setting_int
from db.queries.wallets import get_balance

router = Router(name="flow_accounts")
_UPGRADE_COLLECT_CONFIRM = "upgrade:collect:confirm"
_UPGRADE_COLLECT_RESET = "upgrade:collect:reset"
_UPGRADE_MAX_TOTAL_CHARS = 16_000
_UPGRADE_PAYMENT_PREVIEW_LIMIT = 1_200


# ── FSM States ──────────────────────────────────────────────────────────────

class UpgradeStates(StatesGroup):
    waiting_user_input = State()  # Nhập thông tin cho upgrade (email, password, etc.)


# ── Middleware: lọc product_type cho router này ─────────────────────────────

# Chỉ handle product types: service_upgrade
# account_stocked đã được catalog.py._handle_standard_product xử lý tự động.
# Cần intercept ở catalog.py trước khi tới đây.


# In catalog.py, select_product calls _handle_standard_product for non-key types.
# For service_upgrade, we need to redirect to the FSM input flow first.
# We'll register a handler for ProductSelectCB that checks product_type.

# NOTE: Vì cùng xử lý ProductSelectCB, router này phải TRƯỚC catalog router
# trong dp.include_routers() để filter đúng. Hoặc ta dùng 1 approach khác:
# Catalog._handle_standard_product sẽ gọi hàm ở đây khi detect service_upgrade.

# Approach: Export hàm handle_upgrade_product cho catalog.py import.


def _build_upgrade_prompt_lines(product: dict, input_prompt: str) -> list[str]:
    part_count = max(0, int(product.get("_input_part_count") or 0))
    total_chars = max(0, int(product.get("_input_total_chars") or 0))
    lines = [
        f"🔧 <b>{product['name']}</b>",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"💰 Giá: <b>{format_vnd(product['price_vnd'])}</b>",
    ]
    if product.get("description"):
        lines.append(f"📝 {product['description']}")

    lines.extend([
        "",
        f"❓ <b>{input_prompt}</b>",
        "",
        "✏️ Gửi thông tin bên dưới. Bạn có thể gửi 1 hoặc nhiều tin nhắn.",
        "📨 Khi gửi xong, bấm <b>Xác nhận thông tin</b>.",
    ])
    if part_count > 0:
        lines.extend([
            "",
            f"📥 Đã nhận: <b>{part_count}</b> phần",
            f"📏 Tổng độ dài hiện tại: <b>{total_chars}</b> ký tự",
        ])
    return lines


def _build_upgrade_payment_lines(
    product_name: str,
    price_vnd: int,
    user_input: str,
    order_code: str,
    balance: int,
    *,
    show_qr: bool,
) -> list[str]:
    truncated = len(user_input) > _UPGRADE_PAYMENT_PREVIEW_LIMIT
    preview_input = user_input[:_UPGRADE_PAYMENT_PREVIEW_LIMIT]
    preview_input = escape(preview_input.rstrip() or user_input)
    lines = [
        f"🔧 <b>{product_name}</b>",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"💰 Giá: <b>{format_vnd(price_vnd)}</b>",
        f"📝 Thông tin của bạn: <code>{preview_input}</code>",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"🔖 Mã đơn: <code>{order_code}</code>",
        "",
        "Chọn phương thức thanh toán:",
        f"👛 Số dư ví: <b>{format_vnd(balance)}</b>",
    ]
    if truncated:
        lines.append("ℹ️ Nội dung quá dài nên bot chỉ hiển thị phần xem trước. Shop vẫn nhận đủ dữ liệu bạn đã gửi.")
    if not show_qr:
        lines.append("⚠️ Dưới 1.000đ chỉ hỗ trợ thanh toán bằng ví.")
    return lines


def _upgrade_collect_kb(cat_id: int) -> object:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Xác nhận thông tin", callback_data=_UPGRADE_COLLECT_CONFIRM),
        InlineKeyboardButton(text="🗑 Nhập lại", callback_data=_UPGRADE_COLLECT_RESET),
    )
    builder.row(
        InlineKeyboardButton(
            text="⬅️ Quay lại",
            callback_data=UpgradeBackCB(cat_id=cat_id).pack(),
        )
    )
    return builder.as_markup()


def _collect_upgrade_parts(fsm_data: dict) -> list[str]:
    parts = fsm_data.get("upgrade_input_parts") or []
    return [str(part) for part in parts if str(part)]


def _join_upgrade_input(parts: list[str]) -> str:
    return "".join(parts)


async def _create_upgrade_order(
    *,
    state: FSMContext,
    db_user: dict,
    product: dict,
    user_input: str,
) -> tuple[int, str, int, str]:
    product_name = product.get("name") or "Dịch vụ"
    product_type = product.get("product_type") or "service_upgrade"
    quote = await quote_non_api_product(product, user_id=db_user["id"])
    price_vnd = quote.payable_amount

    order_code = generate_order_code()
    expire_min = await get_setting_int("order_expire_min", 30)
    expired_at = (get_now_vn() + timedelta(minutes=expire_min)).isoformat()

    order_id = await create_order(
        order_code=order_code,
        user_id=db_user["id"],
        product_id=product["id"],
        product_name=product_name,
        product_type=product_type,
        amount=price_vnd,
        payment_method="qr",
        expired_at=expired_at,
        base_amount=quote.base_amount,
        discount_amount=quote.discount_amount,
        cashback_amount=quote.cashback_amount,
        spend_credit_amount=quote.spend_credit_amount,
        pricing_snapshot=json.dumps(quote.pricing_snapshot, ensure_ascii=True),
        promotion_snapshot=(
            json.dumps(quote.promotion_snapshot, ensure_ascii=True)
            if quote.promotion_snapshot
            else None
        ),
    )

    await update_order_status(
        order_id,
        "pending",
        user_input_data=user_input,
    )
    await state.set_state(None)
    await state.update_data(
        current_order_id=order_id,
        upgrade_input_parts=[],
        upgrade_input_total_chars=0,
    )
    return order_id, product_name, price_vnd, order_code


async def _show_category_products(callback: CallbackQuery, cat_id: int) -> None:
    if not cat_id:
        await callback.message.edit_text(
            "🛒 Danh mục sản phẩm",
            reply_markup=back_only_kb("cat"),
        )
        return

    products = await get_active_products_by_category(cat_id)
    if not products:
        await callback.message.edit_text(
            "📦 Danh mục trống.",
            reply_markup=back_only_kb("cat"),
        )
        return

    per_page = await get_setting_int("pagination_size", 6)
    await callback.message.edit_text(
        "📦 <b>Chọn sản phẩm</b>",
        reply_markup=products_kb(
            products,
            cat_id=cat_id,
            srv_id=0,
            ptype="general",
            page=0,
            per_page=per_page,
        ),
        parse_mode="HTML",
    )


async def _show_expired_upgrade_prompt(
    callback: CallbackQuery,
    state: FSMContext,
    text: str,
) -> None:
    await state.clear()
    categories = await get_active_categories()
    if not categories:
        await callback.message.edit_text(text, reply_markup=back_only_kb("main"))
        return

    per_page = await get_setting_int("pagination_size", 6)
    await callback.message.edit_text(
        f"{text}\n\nChọn lại danh mục:",
        reply_markup=categories_kb(categories, page=0, per_page=per_page),
        parse_mode="HTML",
    )


async def handle_upgrade_product(
    callback: CallbackQuery,
    product: dict,
    state: FSMContext,
    _db_user: dict,
) -> None:
    """
    Xử lý sản phẩm dạng service_upgrade.
    Hỏi user nhập thông tin (email, OTP, etc.) trước khi tạo order.
    """
    input_prompt = product.get("input_prompt") or "Vui lòng nhập thông tin cần thiết:"
    await state.update_data(
        upgrade_product_id=product["id"],
        current_cat_id=product.get("category_id", 0),
        upgrade_input_parts=[],
        upgrade_input_total_chars=0,
    )

    await callback.message.edit_text(
        "\n".join(_build_upgrade_prompt_lines(product, input_prompt)),
        reply_markup=_upgrade_collect_kb(product.get("category_id", 0)),
        parse_mode="HTML",
    )
    await state.set_state(UpgradeStates.waiting_user_input)
    await callback.answer()


@router.message(UpgradeStates.waiting_user_input)
async def upgrade_user_input_received(
    message: Message,
    state: FSMContext,
    db_user: dict,
) -> None:
    """Nhận từng phần thông tin từ user và gom lại trong FSM."""
    user_input = (message.text or message.caption or "").strip()
    fsm_data = await state.get_data()
    cat_id = fsm_data.get("current_cat_id", 0)
    upgrade_back = UpgradeBackCB(cat_id=cat_id) if cat_id else "cat"
    input_parts = _collect_upgrade_parts(fsm_data)
    total_chars = int(fsm_data.get("upgrade_input_total_chars") or 0)

    if not user_input:
        await message.answer(
            "❌ Bot chỉ nhận nội dung dạng text cho bước này. Vui lòng gửi lại bằng văn bản.",
            reply_markup=back_only_kb(upgrade_back),
        )
        return
    next_total = total_chars + len(user_input)
    if next_total > _UPGRADE_MAX_TOTAL_CHARS:
        await message.answer(
            "⚠️ Tổng dữ liệu đã vượt giới hạn bot có thể xử lý an toàn. "
            "Vui lòng rút gọn bớt hoặc liên hệ admin trực tiếp kèm sản phẩm bạn cần mua.",
            reply_markup=_upgrade_collect_kb(cat_id),
        )
        return

    input_parts.append(user_input)
    await state.update_data(
        upgrade_input_parts=input_parts,
        upgrade_input_total_chars=next_total,
    )
    await message.answer(
        f"✅ Đã nhận phần <b>{len(input_parts)}</b> ({len(user_input):,} ký tự). "
        "Gửi tiếp nếu còn dữ liệu, hoặc bấm <b>Xác nhận thông tin</b> khi hoàn tất.",
        reply_markup=_upgrade_collect_kb(cat_id),
        parse_mode="HTML",
    )


@router.callback_query(UpgradeStates.waiting_user_input, F.data == _UPGRADE_COLLECT_RESET)
async def upgrade_user_input_reset(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    fsm_data = await state.get_data()
    product_id = fsm_data.get("upgrade_product_id")
    product = await get_product_by_id(product_id) if product_id else None
    if not product:
        await callback.answer("Phiên nhập thông tin đã hết hạn.", show_alert=True)
        return

    await state.update_data(upgrade_input_parts=[], upgrade_input_total_chars=0)
    input_prompt = product.get("input_prompt") or "Vui lòng nhập thông tin cần thiết:"
    await callback.message.edit_text(
        "\n".join(_build_upgrade_prompt_lines(product, input_prompt)),
        reply_markup=_upgrade_collect_kb(product.get("category_id", 0)),
        parse_mode="HTML",
    )
    await callback.answer("Đã xoá phần thông tin đã nhận.")


@router.callback_query(UpgradeStates.waiting_user_input, F.data == _UPGRADE_COLLECT_CONFIRM)
async def upgrade_user_input_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    db_user: dict,
) -> None:
    fsm_data = await state.get_data()
    input_parts = _collect_upgrade_parts(fsm_data)
    user_input = _join_upgrade_input(input_parts)
    if len(user_input.strip()) < 3:
        await callback.answer("Bạn chưa gửi đủ thông tin để tạo đơn.", show_alert=True)
        return

    product_id = fsm_data.get("upgrade_product_id")
    product = await get_product_by_id(product_id) if product_id else None
    if not product:
        await callback.answer()
        await _show_expired_upgrade_prompt(
            callback,
            state,
            "⚠️ Phiên nhập thông tin dịch vụ đã hết hạn hoặc sản phẩm không còn khả dụng.",
        )
        return

    order_id, product_name, price_vnd, order_code = await _create_upgrade_order(
        state=state,
        db_user=db_user,
        product=product,
        user_input=user_input,
    )
    balance = await get_balance(db_user["id"])
    show_qr = price_vnd >= 1000

    await callback.message.answer(
        "\n".join(
            _build_upgrade_payment_lines(
                product_name,
                price_vnd,
                user_input,
                order_code,
                balance,
                show_qr=show_qr,
            )
        ),
        reply_markup=payment_method_kb(order_id, show_qr=show_qr),
        parse_mode="HTML",
    )
    await callback.answer("Đã tạo đơn từ thông tin bạn gửi.")


@router.callback_query(UpgradeBackCB.filter())
async def back_from_upgrade_prompt(
    callback: CallbackQuery,
    callback_data: UpgradeBackCB,
    state: FSMContext,
) -> None:
    """Quay từ màn nhập thông tin dịch vụ về danh sách sản phẩm của danh mục."""
    await state.clear()
    await state.update_data(current_cat_id=callback_data.cat_id)
    await _show_category_products(callback, callback_data.cat_id)
    await callback.answer()


@router.callback_query(F.data == "back:upgrade_back")
async def legacy_upgrade_back(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Tương thích ngược cho nút quay lại của keyboard cũ."""
    fsm_data = await state.get_data()
    cat_id = int(fsm_data.get("current_cat_id") or 0)
    if cat_id:
        await back_from_upgrade_prompt(callback, UpgradeBackCB(cat_id=cat_id), state)
        return

    await callback.answer("⚠️ Keyboard cũ đã hết hạn. Bot sẽ mở lại danh mục sản phẩm.", show_alert=True)
    await _show_expired_upgrade_prompt(
        callback,
        state,
        "⚠️ Phiên nhập thông tin dịch vụ cũ không còn khả dụng sau khi bot khởi động lại hoặc được cập nhật.",
    )
