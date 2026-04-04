"""
bot/handlers/catalog.py — Mặt tiền (Dispatcher) cho sản phẩm.

Nhiệm vụ:
  - Hiện danh mục → phân trang → chọn danh mục → hiện sản phẩm
  - Khi user chọn 1 sản phẩm, đọc product_type rồi uỷ quyền xử lý
    cho flow tương ứng (flow_api_key / flow_accounts).
  - Back navigation cho danh mục.
"""
from __future__ import annotations
from bot.utils.time_utils import get_now_vn

import json
import logging
from dataclasses import replace

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.callback_data.factories import (
    CategoryPageCB, CategorySelectCB, KeyActionCB,
    ProductPageCB, ProductSelectCB, QuantityAdjustCB,
    QuantityBackCB, QuantityConfirmCB, BackCB,
)
from bot.keyboards.inline_kb import (
    categories_kb, key_action_kb, products_kb,
    quantity_picker_kb, back_only_kb,
)
from bot.services.pricing_resolver import QuoteContext, quote_api_order, quote_non_api_product
from bot.utils.group_labels import format_group_display_names
from db.queries.categories import get_active_categories, get_category_by_id
from db.queries.products import get_active_products_by_category, get_product_by_id
from db.queries.servers import get_server_by_id
from db.queries.settings import get_setting_int

logger = logging.getLogger(__name__)

router = Router(name="catalog")
_QUANTITY_ENABLED_TYPES = frozenset({"key_new", "account_stocked"})
_MAX_BULK_KEY_NEW = 10
_MAX_BULK_ACCOUNT = 10


# ── 🛒 Sản phẩm → Danh mục ─────────────────────────────────────────────────

@router.message(Command("products"))
@router.message(F.text.in_({"🛒 Sản phẩm", "🛒 Mua hàng"}))
async def show_categories(message: Message, state: FSMContext) -> None:
    """Hiện danh sách danh mục sản phẩm."""
    await state.clear()
    categories = await get_active_categories()

    if not categories:
        await message.answer("📦 Chưa có sản phẩm nào. Vui lòng quay lại sau!")
        return

    per_page = await get_setting_int("pagination_size", 6)
    await message.answer(
        "🛒 <b>Bắt đầu mua hàng</b>\n\nChọn danh mục:",
        reply_markup=categories_kb(categories, page=0, per_page=per_page),
        parse_mode="HTML",
    )


# ── Phân trang danh mục ────────────────────────────────────────────────────

@router.callback_query(CategoryPageCB.filter())
async def categories_page(
    callback: CallbackQuery,
    callback_data: CategoryPageCB,
) -> None:
    """Chuyển trang danh mục."""
    categories = await get_active_categories()
    per_page = await get_setting_int("pagination_size", 6)
    await callback.message.edit_text(
        "🛒 <b>Bắt đầu mua hàng</b>\n\nChọn danh mục:",
        reply_markup=categories_kb(categories, page=callback_data.page, per_page=per_page),
        parse_mode="HTML",
    )
    await callback.answer()


# ── Chọn danh mục ──────────────────────────────────────────────────────────

@router.callback_query(CategorySelectCB.filter())
async def select_category(
    callback: CallbackQuery,
    callback_data: CategorySelectCB,
    state: FSMContext,
) -> None:
    """Xử lý chọn danh mục — phân luồng theo cat_type."""
    cat = await get_category_by_id(callback_data.id)
    if not cat:
        await callback.answer("❌ Danh mục không tồn tại.", show_alert=True)
        return

    # Lưu category vào FSM data cho back navigation
    await state.update_data(current_cat_id=cat["id"])

    if cat["cat_type"] == "key_api":
        # Hiện sub-menu: Mua key mới / Nạp key cũ
        await callback.message.edit_text(
            f"{cat.get('icon', '📦')} <b>{cat['name']}</b>\n\n"
            f"Chọn hành động:",
            reply_markup=key_action_kb(cat["id"]),
            parse_mode="HTML",
        )
    else:
        # General: Hiện danh sách sản phẩm trực tiếp
        products = await get_active_products_by_category(cat["id"])
        if not products:
            await callback.message.edit_text(
                "📦 Danh mục trống.",
                reply_markup=back_only_kb("cat"),
            )
            await callback.answer()
            return

        per_page = await get_setting_int("pagination_size", 6)
        ptype = "general"

        await callback.message.edit_text(
            f"{cat.get('icon', '📦')} <b>{cat['name']}</b>\n\nChọn sản phẩm:",
            reply_markup=products_kb(
                products, cat_id=cat["id"], srv_id=0,
                ptype=ptype, page=0, per_page=per_page,
            ),
            parse_mode="HTML",
        )
    await callback.answer()


# ── Phân trang sản phẩm ────────────────────────────────────────────────────

@router.callback_query(ProductPageCB.filter())
async def products_page(
    callback: CallbackQuery,
    callback_data: ProductPageCB,
) -> None:
    """Chuyển trang danh sách sản phẩm."""
    cat_id = callback_data.cat_id
    srv_id = callback_data.srv_id
    ptype = callback_data.ptype

    products = await get_active_products_by_category(
        cat_id,
        server_id=srv_id if srv_id > 0 else None,
        product_type=ptype if ptype != "general" else None,
    )

    per_page = await get_setting_int("pagination_size", 6)
    await callback.message.edit_reply_markup(
        reply_markup=products_kb(
            products, cat_id=cat_id, srv_id=srv_id,
            ptype=ptype, page=callback_data.page, per_page=per_page,
        ),
    )
    await callback.answer()


def _supports_quantity(product: dict) -> bool:
    return str(product.get("product_type") or "") in _QUANTITY_ENABLED_TYPES


def _max_quantity_for_product(product: dict) -> int:
    ptype = str(product.get("product_type") or "")
    if ptype == "account_stocked":
        stock = int(product.get("stock") or 0)
        if stock <= 1:
            return 1
        return min(stock, _MAX_BULK_ACCOUNT)
    if ptype == "key_new":
        return _MAX_BULK_KEY_NEW
    return 1


def _normalize_quantity(product: dict, quantity: int) -> tuple[int, int]:
    max_quantity = _max_quantity_for_product(product)
    return max(1, min(quantity, max_quantity)), max_quantity


def _scale_quote(quote: QuoteContext, quantity: int) -> QuoteContext:
    if quantity <= 1:
        return quote

    pricing_snapshot = dict(quote.pricing_snapshot or {})
    pricing_snapshot.update(
        {
            "quantity": quantity,
            "unit_base_amount": quote.base_amount,
            "unit_payable_amount": quote.payable_amount,
            "unit_discount_amount": quote.discount_amount,
            "unit_cashback_amount": quote.cashback_amount,
            "total_base_amount": quote.base_amount * quantity,
            "total_payable_amount": quote.payable_amount * quantity,
        }
    )

    promotion_snapshot = (
        dict(quote.promotion_snapshot)
        if isinstance(quote.promotion_snapshot, dict)
        else quote.promotion_snapshot
    )

    return replace(
        quote,
        base_amount=quote.base_amount * quantity,
        payable_amount=quote.payable_amount * quantity,
        discount_amount=quote.discount_amount * quantity,
        cashback_amount=quote.cashback_amount * quantity,
        spend_credit_amount=quote.spend_credit_amount * quantity,
        quota_amount=quote.quota_amount * quantity,
        dollar_amount=quote.dollar_amount * quantity,
        pricing_snapshot=pricing_snapshot,
        promotion_snapshot=promotion_snapshot,
    )


async def _quote_product_for_quantity(
    product: dict,
    *,
    user_id: int,
    quantity: int,
) -> tuple[QuoteContext, QuoteContext, dict | None]:
    server = None
    ptype = str(product.get("product_type") or "")

    if ptype in {"key_new", "key_topup"} and product.get("server_id"):
        server = await get_server_by_id(product["server_id"])
        if not server:
            raise ValueError("Server không tồn tại")
        single_quote = await quote_api_order(user_id=user_id, server=server, product=product)
    else:
        single_quote = await quote_non_api_product(product, user_id=user_id)

    return single_quote, _scale_quote(single_quote, quantity), server


async def _show_quantity_picker(
    callback: CallbackQuery,
    *,
    product: dict,
    quantity: int,
    user_id: int,
) -> None:
    from bot.utils.formatting import format_vnd

    quantity, max_quantity = _normalize_quantity(product, quantity)
    single_quote, total_quote, server = await _quote_product_for_quantity(
        product,
        user_id=user_id,
        quantity=quantity,
    )

    lines = [
        "🧮 <b>Chọn số lượng</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"📦 <b>{product['name']}</b>",
        f"🔢 Số lượng: <b>x{quantity}</b>",
        f"💵 Đơn giá: <b>{format_vnd(single_quote.payable_amount)}</b>",
        f"💰 Tạm tính: <b>{format_vnd(total_quote.payable_amount)}</b>",
    ]
    if total_quote.discount_amount > 0:
        lines.append(f"🏷 Giá gốc: <b>{format_vnd(total_quote.base_amount)}</b>")
        lines.append(f"💸 Giảm giá: <b>-{format_vnd(total_quote.discount_amount)}</b>")
    if total_quote.cashback_amount > 0:
        lines.append(f"🪙 Cashback: <b>{format_vnd(total_quote.cashback_amount)}</b>")
    if product.get("description"):
        lines.append(f"📝 {product['description']}")

    if product.get("product_type") == "key_new":
        if single_quote.dollar_amount > 0:
            lines.append(f"💵 Mỗi key: <b>{single_quote.dollar_amount:g}$</b>")
        if server:
            lines.append(f"🖥 Server: <b>{server['name']}</b>")
        group_name = (product.get("group_name") or (server.get("default_group") if server else "") or "").strip()
        if group_name:
            display_group = await format_group_display_names(group_name, server)
            lines.append(f"👥 Group: <b>{display_group or group_name}</b>")
    elif product.get("product_type") == "account_stocked":
        lines.append(f"📦 Tồn kho khả dụng: <b>{product.get('stock', 0)}</b>")

    lines.append(f"📏 Giới hạn mỗi đơn: <b>x{max_quantity}</b>")
    lines.extend([
        "━━━━━━━━━━━━━━━━━━━━",
        "Chọn số lượng rồi bấm <b>Tiếp tục thanh toán</b>.",
    ])

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=quantity_picker_kb(
            product_id=product["id"],
            quantity=quantity,
            max_quantity=max_quantity,
        ),
        parse_mode="HTML",
    )


async def _show_product_list_for_quantity_back(callback: CallbackQuery, product: dict) -> None:
    cat_id = int(product.get("category_id") or 0)
    per_page = await get_setting_int("pagination_size", 6)
    ptype = str(product.get("product_type") or "")

    if ptype == "key_new" and product.get("server_id"):
        server = await get_server_by_id(product["server_id"])
        products = await get_active_products_by_category(
            cat_id,
            server_id=product["server_id"],
            product_type="key_new",
        )
        title = f"🔑 <b>Mua key mới — {server['name']}</b>\n\nChọn gói:" if server else "🔑 <b>Mua key mới</b>\n\nChọn gói:"
        await callback.message.edit_text(
            title,
            reply_markup=products_kb(
                products,
                cat_id=cat_id,
                srv_id=product["server_id"],
                ptype="key_new",
                page=0,
                per_page=per_page,
                action="new",
            ),
            parse_mode="HTML",
        )
        return

    category = await get_category_by_id(cat_id)
    products = await get_active_products_by_category(cat_id)
    title = (
        f"{category.get('icon', '📦')} <b>{category['name']}</b>\n\nChọn sản phẩm:"
        if category
        else "📦 <b>Chọn sản phẩm</b>"
    )
    await callback.message.edit_text(
        title,
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


# ── Chọn sản phẩm → Điều hướng theo product_type ───────────────────────────

@router.callback_query(ProductSelectCB.filter())
async def select_product(
    callback: CallbackQuery,
    callback_data: ProductSelectCB,
    state: FSMContext,
    db_user: dict,
) -> None:
    """
    Chọn sản phẩm → đọc product_type → uỷ quyền cho flow tương ứng.
    - key_new / key_topup → _handle_standard_product (FSM data đã có server_id + existing_key)
    - service_upgrade → flow_accounts (FSM thu thập thông tin)
    - account_stocked và còn lại → _handle_standard_product
    """
    product = await get_product_by_id(callback_data.product_id)
    if not product:
        await callback.answer("❌ Sản phẩm không tồn tại.", show_alert=True)
        return

    # Kiểm tra stock
    if product["stock"] == 0:
        await callback.answer("❌ Sản phẩm đã hết hàng.", show_alert=True)
        return

    ptype = product["product_type"]

    if ptype == "service_upgrade":
        # Luồng Nâng cấp — cần thu thập thông tin từ user trước
        from bot.handlers.flow_accounts import handle_upgrade_product
        await handle_upgrade_product(callback, product, state, db_user)
        return

    if _supports_quantity(product):
        _, max_quantity = _normalize_quantity(product, 1)
        if max_quantity > 1:
            try:
                await _show_quantity_picker(
                    callback,
                    product=product,
                    quantity=1,
                    user_id=db_user["id"],
                )
            except ValueError as exc:
                await callback.answer(f"❌ {exc}", show_alert=True)
                return
            await callback.answer()
            return

    # Tất cả loại khác (key_new, key_topup, account_stocked): tạo order + payment
    await _handle_standard_product(callback, product, state, db_user)


@router.callback_query(QuantityAdjustCB.filter())
async def adjust_quantity(
    callback: CallbackQuery,
    callback_data: QuantityAdjustCB,
    db_user: dict,
) -> None:
    product = await get_product_by_id(callback_data.product_id)
    if not product or not _supports_quantity(product):
        await callback.answer("❌ Sản phẩm không còn khả dụng.", show_alert=True)
        return

    if product["stock"] == 0:
        await callback.answer("❌ Sản phẩm đã hết hàng.", show_alert=True)
        return

    try:
        await _show_quantity_picker(
            callback,
            product=product,
            quantity=callback_data.qty,
            user_id=db_user["id"],
        )
    except ValueError as exc:
        await callback.answer(f"❌ {exc}", show_alert=True)
        return
    await callback.answer()


@router.callback_query(QuantityConfirmCB.filter())
async def confirm_quantity(
    callback: CallbackQuery,
    callback_data: QuantityConfirmCB,
    state: FSMContext,
    db_user: dict,
) -> None:
    product = await get_product_by_id(callback_data.product_id)
    if not product or not _supports_quantity(product):
        await callback.answer("❌ Sản phẩm không còn khả dụng.", show_alert=True)
        return

    quantity, _ = _normalize_quantity(product, callback_data.qty)
    await _handle_standard_product(callback, product, state, db_user, quantity=quantity)


@router.callback_query(QuantityBackCB.filter())
async def quantity_back(
    callback: CallbackQuery,
    callback_data: QuantityBackCB,
) -> None:
    product = await get_product_by_id(callback_data.product_id)
    if not product:
        await callback.answer("❌ Sản phẩm không còn khả dụng.", show_alert=True)
        return

    await _show_product_list_for_quantity_back(callback, product)
    await callback.answer()


async def _handle_standard_product(
    callback: CallbackQuery,
    product: dict,
    state: FSMContext,
    db_user: dict,
    *,
    quantity: int = 1,
) -> None:
    """Xử lý sản phẩm dạng chuẩn (chatgpt, account_stocked, general) → tạo order → payment."""
    from datetime import datetime, timedelta
    from bot.utils.formatting import format_vnd, mask_api_key, quota_to_dollar, format_dollar
    from bot.utils.group_labels import format_group_display_names
    from bot.utils.order_code import generate_order_code
    from bot.keyboards.inline_kb import payment_method_kb
    from db.queries.orders import create_order
    from db.queries.wallets import get_balance
    # Lấy thông tin server nếu có
    server = None
    server_name = "N/A"
    server_default_group = ""
    if product.get("server_id"):
        server = await get_server_by_id(product["server_id"])
        if server:
            server_name = server["name"]
            server_default_group = (server.get("default_group") or "").strip()

    # Lấy existing_key từ FSM nếu đang topup
    fsm_data = await state.get_data()
    existing_key = fsm_data.get("existing_key")
    current_cat_id = fsm_data.get("current_cat_id") or product.get("category_id") or 0

    ptype = product.get("product_type", "")
    dollar_amount = product.get("dollar_amount") or 0.0

    if ptype == "key_topup" and not existing_key:
        from bot.handlers.flow_api_key import _show_existing_keys_for_server

        await state.update_data(
            current_cat_id=current_cat_id,
            current_server_id=product.get("server_id"),
            key_action="topup",
        )
        if product.get("server_id") and await _show_existing_keys_for_server(
            callback,
            user_id=db_user["id"],
            server_id=product["server_id"],
            cat_id=current_cat_id,
        ):
            await callback.answer(
                "⚠️ Phiên chọn key để nạp đã hết hạn. Vui lòng chọn lại key hoặc nhập key mới.",
                show_alert=True,
            )
            return

        await callback.message.edit_text(
            "⚠️ Phiên chọn key để nạp đã hết hạn. Vui lòng bắt đầu lại từ danh mục sản phẩm.",
            reply_markup=back_only_kb("cat"),
        )
        await callback.answer()
        return

    if ptype == "key_new" and dollar_amount < 10:
        await callback.answer("❌ Gói mua mới phải có giá trị tối thiểu $10.", show_alert=True)
        return

    if ptype == "key_topup" and dollar_amount < 1:
        await callback.answer("❌ Gói nạp thêm phải có giá trị tối thiểu $1.", show_alert=True)
        return

    if ptype in ("key_new", "key_topup") and server:
        single_quote = await quote_api_order(
            user_id=db_user["id"],
            server=server,
            product=product,
        )
    else:
        single_quote = await quote_non_api_product(product, user_id=db_user["id"])
    quote = _scale_quote(single_quote, quantity)

    # Build product detail text
    lines = [
        f"📦 <b>{product['name']}</b>",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"💰 Giá: <b>{format_vnd(quote.payable_amount)}</b>",
    ]
    if quantity > 1:
        lines.append(f"🔢 Số lượng: <b>x{quantity}</b>")
        lines.append(f"💵 Đơn giá: <b>{format_vnd(single_quote.payable_amount)}</b>")
    if quote.discount_amount > 0:
        lines.append(f"🏷 Giá gốc: <b>{format_vnd(quote.base_amount)}</b>")
        lines.append(f"💸 Giảm giá: <b>-{format_vnd(quote.discount_amount)}</b>")
    if quote.cashback_amount > 0:
        lines.append(f"🪙 Cashback sau thanh toán: <b>{format_vnd(quote.cashback_amount)}</b>")

    if product.get("description"):
        lines.append(f"📝 {product['description']}")
    if product.get("quota_amount") and product.get("server_id"):
        server_info = await get_server_by_id(product["server_id"])
        mult = server_info.get("quota_multiple", 1.0) if server_info else 1.0
        lines.append(f"💵 Số dư: <b>{quota_to_dollar(product['quota_amount'], mult)}</b>")
    elif product.get("quota_amount"):
        lines.append(f"💵 Số dư: <b>{quota_to_dollar(product['quota_amount'])}</b>")
    if product.get("dollar_amount"):
        lines.append(f"💵 Dollar: <b>{format_dollar(product['dollar_amount'])}</b>")
    effective_group = (product.get("group_name") or server_default_group or "").strip()
    display_group = await format_group_display_names(effective_group, server)
    uses_server_default_group = (
        ptype == "key_new"
        and not (product.get("group_name") or "").strip()
        and bool(server_default_group)
    )

    if product.get("server_id"):
        lines.append(f"🖥 Server: <b>{server_name}</b>")
    if effective_group:
        group_label = "Group mặc định của server" if uses_server_default_group else "Group"
        lines.append(f"👥 {group_label}: <b>{display_group or effective_group}</b>")
    if existing_key:
        lines.append(f"🔑 Key nạp: <code>{mask_api_key(existing_key)}</code>")

    stock_text = "Không giới hạn" if product["stock"] == -1 else str(product["stock"])
    lines.append(f"📦 Còn lại: <b>{stock_text}</b>")

    # Tạo order tạm (status=pending)
    order_code = generate_order_code()
    expire_min = await get_setting_int("order_expire_min", 30)
    expired_at = (get_now_vn() + timedelta(minutes=expire_min)).isoformat()

    order_id = await create_order(
        order_code=order_code,
        user_id=db_user["id"],
        product_id=product["id"],
        product_name=product["name"],
        product_type=product["product_type"],
        amount=quote.payable_amount,
        quantity=quantity,
        payment_method="qr",  # Default, sẽ update khi chọn
        server_id=product.get("server_id"),
        group_name=effective_group or None,
        existing_key=existing_key,
        expired_at=expired_at,
        base_amount=quote.base_amount,
        discount_amount=quote.discount_amount,
        cashback_amount=quote.cashback_amount,
        spend_credit_amount=quote.spend_credit_amount,
        pricing_version_id=quote.pricing_version_id,
        applied_tier_id=quote.applied_tier_id,
        pricing_snapshot=json.dumps(quote.pricing_snapshot, ensure_ascii=True),
        promotion_snapshot=(
            json.dumps(quote.promotion_snapshot, ensure_ascii=True)
            if quote.promotion_snapshot
            else None
        ),
    )

    # [NEW] Nếu là tài khoản có sẵn, lập tức xí chỗ (reserve)
    if product["product_type"] == "account_stocked":
        from db.queries.account_stocks import reserve_accounts
        from db.queries.orders import update_order_status
        reserved_accounts = await reserve_accounts(product["id"], order_id, quantity)
        if len(reserved_accounts) < quantity:
            # Thu hồi đơn vừa tạo và báo lỗi (ai đó đã nhanh tay hơn)
            await update_order_status(order_id, "cancelled", cancel_reason="Hết hàng (Race condition)")
            await callback.answer("❌ Tồn kho không đủ cho số lượng bạn chọn. Vui lòng thử lại với số lượng thấp hơn.", show_alert=True)
            return

    await state.update_data(current_order_id=order_id)

    lines.extend([
        f"━━━━━━━━━━━━━━━━━━━━",
        f"🔖 Mã đơn: <code>{order_code}</code>",
        f"\nChọn phương thức thanh toán:",
    ])

    # Hiện balance ví
    balance = await get_balance(db_user["id"])
    lines.append(f"👛 Số dư ví: <b>{format_vnd(balance)}</b>")

    # Hiển thị nút QR hay không
    if ptype in ("key_new", "key_topup"):
        show_qr = (quote.dollar_amount >= 10)
        warning_msg = "⚠️ Dưới $10 chỉ hỗ trợ thanh toán bằng ví nội bộ."
    else:
        show_qr = (quote.payable_amount >= 1000)
        warning_msg = "⚠️ Dưới 1.000đ chỉ hỗ trợ thanh toán bằng ví."

    if not show_qr:
        lines.append(warning_msg)

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=payment_method_kb(order_id, show_qr=show_qr),
        parse_mode="HTML",
    )
    await callback.answer()


# ── Back navigation ─────────────────────────────────────────────────────────

@router.callback_query(BackCB.filter(F.target == "cat"))
async def back_to_categories(callback: CallbackQuery, state: FSMContext) -> None:
    """Quay lại danh mục."""
    await state.clear()
    categories = await get_active_categories()
    per_page = await get_setting_int("pagination_size", 6)
    await callback.message.edit_text(
        "🛒 <b>Bắt đầu mua hàng</b>\n\nChọn danh mục:",
        reply_markup=categories_kb(categories, page=0, per_page=per_page),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(BackCB.filter(F.target == "main"))
async def back_to_main(callback: CallbackQuery, state: FSMContext) -> None:
    """Quay về menu chính (xóa inline message)."""
    await state.clear()
    await callback.message.delete()
    await callback.answer()


# ── Noop callback (pagination indicator) ────────────────────────────────────

@router.callback_query(F.data == "noop")
async def noop_callback(callback: CallbackQuery) -> None:
    """Bỏ qua callback 'noop' (nút hiển thị trang)."""
    await callback.answer()
