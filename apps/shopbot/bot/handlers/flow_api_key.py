"""
bot/handlers/flow_api_key.py — Luồng bán Key API (new + topup + custom dollar).

Tách riêng từ products.py để dễ bảo trì.
Flow:
  KeyAction (new/topup) → Server → (chọn key nếu topup) → Gói → Thanh toán
  Custom dollar: FSM nhập số $ → tính VNĐ → tạo order → thanh toán
"""
from __future__ import annotations
from bot.utils.time_utils import get_now_vn

import json
import logging
import math
from datetime import datetime, timedelta

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.callback_data.factories import (
    KeyActionCB, ServerSelectCB, ProductPageCB,
    ProductSelectCB, PaymentMethodCB, OrderCancelCB,
    MyKeySelectCB, MyKeysPageCB, MyKeySearchCB, MyKeyInputCB, CustomAmountCB,
    BackServersCB, BackKeyInputCB, BackCustomAmountCB,
)
from bot.keyboards.inline_kb import (
    categories_kb, servers_kb, products_kb, payment_method_kb,
    my_keys_kb, my_keys_all_kb, my_key_search_results_kb, back_only_kb,
)
from bot.services.api_clients import get_api_client
from bot.services.key_valuation import KeyValuationService
from bot.services.pricing_resolver import quote_api_order
from bot.utils.formatting import format_vnd, mask_api_key, quota_to_dollar
from bot.utils.group_labels import format_group_display_names
from bot.utils.order_code import generate_order_code
from bot.services.vietqr import build_qr_url, build_qr_caption
from bot.services.payment_poller import process_wallet_payment

logger = logging.getLogger(__name__)

from db.queries.categories import get_active_categories, get_category_by_id
from db.queries.products import get_active_products_by_category, get_product_by_id
from db.queries.servers import get_active_servers, get_server_by_id
from db.queries.orders import create_order, get_order_by_id
from db.queries.user_keys import (
    get_user_keys,
    get_user_key_by_id,
    search_user_keys,
    upsert_user_key,
)
from db.queries.wallets import get_balance
from db.queries.settings import get_setting_int

router = Router(name="flow_api_key")


async def _show_existing_keys_for_server(
    callback: CallbackQuery,
    *,
    user_id: int,
    server_id: int,
    cat_id: int,
    view: str = "recent",
    page: int = 0,
) -> bool:
    keys = await get_user_keys(user_id, server_id=server_id)
    server = await get_server_by_id(server_id)
    if not server:
        return False

    per_page = await get_setting_int("pagination_size", 6)
    total_count = len(keys)
    if view == "all" and total_count:
        total_pages = max(1, math.ceil(total_count / per_page))
        current_page = max(0, min(page, total_pages - 1))
        start_index = current_page * per_page + 1
        end_index = min(total_count, start_index + per_page - 1)
        text = (
            f"💳 <b>Nạp key cũ — {server['name']}</b>\n\n"
            "Tất cả key đã lưu trên server này:\n"
            f"<i>Đang hiển thị {start_index}-{end_index} / {total_count} key</i>"
        )
        reply_markup = my_keys_all_kb(
            keys,
            server_id=server_id,
            cat_id=cat_id,
            page=current_page,
            per_page=per_page,
        )
    elif total_count:
        text = (
            f"💳 <b>Nạp key cũ — {server['name']}</b>\n\n"
            "Chọn key gần đây bạn muốn nạp thêm quota:"
        )
        reply_markup = my_keys_kb(
            keys[:per_page],
            server_id=server_id,
            cat_id=cat_id,
            total_count=total_count,
        )
    else:
        text = (
            f"💳 <b>Nạp key cũ — {server['name']}</b>\n\n"
            "Bạn chưa có key nào đã lưu trên server này.\n"
            "Hãy dán API key để tiếp tục nạp."
        )
        reply_markup = my_keys_kb(
            [],
            server_id=server_id,
            cat_id=cat_id,
            total_count=0,
        )

    await callback.message.edit_text(
        text,
        reply_markup=reply_markup,
        parse_mode="HTML",
    )
    return True


async def _show_key_products_for_server(
    callback: CallbackQuery,
    *,
    cat_id: int,
    server_id: int,
    action: str,
) -> bool:
    server = await get_server_by_id(server_id)
    if not server:
        return False

    ptype = "key_new" if action == "new" else "key_topup"
    products = await get_active_products_by_category(
        cat_id, server_id=server_id, product_type=ptype
    )
    if not products:
        await callback.message.edit_text(
            f"📦 Chưa có gói cho server <b>{server['name']}</b>.",
            reply_markup=back_only_kb(BackServersCB(cat_id=cat_id, action=action)),
            parse_mode="HTML",
        )
        return True

    per_page = await get_setting_int("pagination_size", 6)
    title = "🔑 Mua key mới" if action == "new" else "💳 Nạp key cũ"
    await callback.message.edit_text(
        f"{title} — <b>{server['name']}</b>\n\nChọn gói:",
        reply_markup=products_kb(
            products,
            cat_id=cat_id,
            srv_id=server_id,
            ptype=ptype,
            page=0,
            per_page=per_page,
            action=action,
        ),
        parse_mode="HTML",
    )
    return True


async def _show_expired_catalog_prompt(
    callback: CallbackQuery,
    state: FSMContext,
    text: str,
) -> None:
    """Fallback thân thiện cho keyboard cũ hoặc context đã mất."""
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


# ── FSM States ──────────────────────────────────────────────────────────────

class ApiKeyStates(StatesGroup):
    waiting_existing_key = State()   # Nhập key cũ khi topup
    waiting_key_search = State()     # Tìm key cũ theo ký tự cuối
    waiting_custom_dollar = State()  # Nhập số $ tùy chọn


# ── Key action: Mua mới / Nạp cũ → Chọn server ────────────────────────────

@router.callback_query(KeyActionCB.filter())
async def key_action(
    callback: CallbackQuery,
    callback_data: KeyActionCB,
    state: FSMContext,
) -> None:
    """Chọn action (new/topup) → hiện danh sách server."""
    action = callback_data.action  # 'new' | 'topup'
    await state.update_data(key_action=action, current_cat_id=callback_data.cat_id)

    servers = await get_active_servers()
    if not servers:
        await callback.message.edit_text(
            "🖥 Chưa có server nào được cấu hình.",
            reply_markup=back_only_kb("cat"),
        )
        await callback.answer()
        return

    action_text = "🔑 Mua key mới" if action == "new" else "💳 Nạp key cũ"
    await callback.message.edit_text(
        f"{action_text}\n\nChọn server:",
        reply_markup=servers_kb(servers, cat_id=callback_data.cat_id, action=action),
        parse_mode="HTML",
    )
    await callback.answer()


# ── Chọn server ─────────────────────────────────────────────────────────────

@router.callback_query(ServerSelectCB.filter())
async def select_server(
    callback: CallbackQuery,
    callback_data: ServerSelectCB,
    state: FSMContext,
    db_user: dict,
) -> None:
    """Chọn server → hiện danh sách gói (key_new) hoặc chọn key (key_topup)."""
    action = callback_data.action
    server_id = callback_data.server_id
    cat_id = callback_data.cat_id

    server = await get_server_by_id(server_id)
    if not server:
        await callback.answer("❌ Server không tồn tại.", show_alert=True)
        return

    await state.update_data(
        current_server_id=server_id,
        key_action=action,
        current_cat_id=cat_id,
    )

    if action == "topup":
        await _show_existing_keys_for_server(
            callback,
            user_id=db_user["id"],
            server_id=server_id,
            cat_id=cat_id,
        )
    else:
        # New: hiện danh sách gói key_new
        ptype = "key_new"
        products = await get_active_products_by_category(
            cat_id, server_id=server_id, product_type=ptype
        )
        if not products:
            await callback.message.edit_text(
                f"📦 Chưa có gói cho server <b>{server['name']}</b>.",
                reply_markup=back_only_kb(BackServersCB(cat_id=cat_id, action=action)),
                parse_mode="HTML",
            )
            await callback.answer()
            return

        per_page = await get_setting_int("pagination_size", 6)
        await callback.message.edit_text(
            f"🔑 <b>Mua key mới — {server['name']}</b>\n\nChọn gói:",
            reply_markup=products_kb(
                products, cat_id=cat_id, srv_id=server_id,
                ptype=ptype, page=0, per_page=per_page,
                action="new",
            ),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(MyKeysPageCB.filter())
async def show_all_my_keys(
    callback: CallbackQuery,
    callback_data: MyKeysPageCB,
    db_user: dict,
) -> None:
    """Mở danh sách toàn bộ key đã lưu với phân trang."""
    await _show_existing_keys_for_server(
        callback,
        user_id=db_user["id"],
        server_id=callback_data.server_id,
        cat_id=callback_data.cat_id,
        view="all",
        page=callback_data.page,
    )
    await callback.answer()


@router.callback_query(MyKeySearchCB.filter())
async def prompt_key_search(
    callback: CallbackQuery,
    callback_data: MyKeySearchCB,
    state: FSMContext,
) -> None:
    """Yêu cầu user nhập vài ký tự cuối để tìm key đã lưu."""
    await state.update_data(
        current_server_id=callback_data.server_id,
        current_cat_id=callback_data.cat_id,
        key_action="topup",
    )
    await callback.message.edit_text(
        "🔎 <b>Tìm key đã lưu</b>\n\n"
        "Nhập 4-8 ký tự cuối của key để lọc nhanh trong danh sách đã lưu.\n"
        "Nếu muốn dán full key, hãy quay lại và chọn <b>Dán key khác</b>.",
        reply_markup=back_only_kb(
            BackKeyInputCB(server_id=callback_data.server_id, cat_id=callback_data.cat_id)
        ),
        parse_mode="HTML",
    )
    await state.set_state(ApiKeyStates.waiting_key_search)
    await callback.answer()


# ── Chọn key hiện có (topup) ───────────────────────────────────────────────

@router.callback_query(MyKeySelectCB.filter())
async def select_my_key(
    callback: CallbackQuery,
    callback_data: MyKeySelectCB,
    state: FSMContext,
    db_user: dict,
) -> None:
    """Chọn key hiện có → hiện danh sách gói topup."""
    key_row = await get_user_key_by_id(callback_data.key_id)
    if not key_row or key_row["user_id"] != db_user["id"]:
        await callback.answer("❌ Key không tồn tại.", show_alert=True)
        return

    await state.update_data(
        existing_key=key_row["api_key"],
        current_server_id=key_row["server_id"],
    )

    fsm_data = await state.get_data()
    cat_id = fsm_data.get("current_cat_id", 0)
    server_id = key_row["server_id"]

    # Hiện gói topup
    products = await get_active_products_by_category(
        cat_id, server_id=server_id, product_type="key_topup"
    )
    if not products:
        await callback.message.edit_text(
            "📦 Chưa có gói nạp cho server này.",
            reply_markup=back_only_kb(BackServersCB(cat_id=cat_id, action="topup")),
        )
        await callback.answer()
        return

    per_page = await get_setting_int("pagination_size", 6)
    await callback.message.edit_text(
        f"💳 <b>Nạp key</b>: <code>{mask_api_key(key_row['api_key'])}</code>\n\nChọn gói nạp:",
        reply_markup=products_kb(
            products, cat_id=cat_id, srv_id=server_id,
            ptype="key_topup", page=0, per_page=per_page,
            action="topup",
        ),
        parse_mode="HTML",
    )
    await callback.answer()


# ── Nhập key mới (topup, FSM) ──────────────────────────────────────────────

@router.callback_query(MyKeyInputCB.filter())
async def input_key_prompt(
    callback: CallbackQuery,
    callback_data: MyKeyInputCB,
    state: FSMContext,
) -> None:
    """Yêu cầu user dán full API key để topup."""
    await state.update_data(
        current_server_id=callback_data.server_id,
        current_cat_id=callback_data.cat_id,
        key_action="topup",
    )
    await callback.message.edit_text(
        "✏️ <b>Dán API Key</b>\n\n"
        "Dán API key bạn muốn nạp thêm quota:\n"
        "Ví dụ: <code>sk-abcdefghijklmn...</code>",
        reply_markup=back_only_kb(
            BackKeyInputCB(server_id=callback_data.server_id, cat_id=callback_data.cat_id)
        ),
        parse_mode="HTML",
    )
    await state.set_state(ApiKeyStates.waiting_existing_key)
    await callback.answer()


@router.message(ApiKeyStates.waiting_existing_key)
async def input_key_received(
    message: Message,
    state: FSMContext,
    db_user: dict,
) -> None:
    """Nhận key từ user → kiểm tra key trên server → hiện gói topup."""
    api_key = message.text.strip()
    fsm_data = await state.get_data()
    server_id = fsm_data.get("current_server_id", 0)
    cat_id = fsm_data.get("current_cat_id", 0)
    key_input_back = (
        BackKeyInputCB(server_id=server_id, cat_id=cat_id)
        if server_id and cat_id
        else "cat"
    )

    if len(api_key) < 30:
        await message.answer(
            "❌ Key (mã token) quá ngắn. Vui lòng copy và dán đầy đủ key.",
            reply_markup=back_only_kb(key_input_back),
        )
        return

    if not server_id or not cat_id:
        await state.clear()
        await message.answer(
            "⚠️ Phiên nhập key đã hết hạn sau khi bot khởi động lại hoặc do tin nhắn cũ. "
            "Vui lòng mở lại mục Sản phẩm và chọn server để nạp key.",
            reply_markup=back_only_kb("cat"),
        )
        return

    # Validate key tồn tại trên server
    server = await get_server_by_id(server_id)
    if not server:
        await message.answer(
            "❌ Server không tồn tại.",
            reply_markup=back_only_kb(BackServersCB(cat_id=cat_id, action="topup")),
        )
        await state.clear()
        return

    token_data = await get_api_client(server).search_token(server, api_key)
    if not token_data:
        await message.answer(
            "❌ <b>Key không tồn tại</b> trên server này.\n\n"
            "Vui lòng kiểm tra lại key và nhập lại.",
            parse_mode="HTML",
            reply_markup=back_only_kb(key_input_back),
        )
        return  # Giữ FSM state để user nhập lại

    normalized_key = api_key if api_key.startswith("sk-") else f"sk-{api_key}"
    await state.update_data(existing_key=normalized_key)
    await state.set_state(None)

    accrual_lines: list[str] = []
    if server.get("import_spend_accrual_enabled"):
        valuation = await KeyValuationService.evaluate_imported_key(
            user_id=db_user["id"],
            server=server,
            api_key=normalized_key,
            token_data=token_data,
            source="manual_topup_input",
            source_ref=f"server:{server_id}",
        )
        status = valuation.get("status")
        if status == "owner_mismatch":
            accrual_lines.append(
                "ℹ️ Key này đã được liên kết với tài khoản khác trong hệ thống."
                " Bạn vẫn có thể nạp, nhưng tài khoản hiện tại sẽ không được cộng ưu đãi từ key này."
            )
        elif status == "credited":
            accrual_lines.append(
                "🎯 Đã ghi nhận thêm chi tiêu hợp lệ: "
                f"<b>{format_vnd(int(valuation.get('credited_value_vnd') or 0))}</b>"
            )
        elif status == "no_change":
            accrual_lines.append("ℹ️ Key đã tồn tại trong hệ thống, chưa có giá trị tăng thêm để cộng tier.")
        else:
            accrual_lines.append(
                "⚠️ Server không trả đủ `remain_quota` và `used_quota`, lần nhập này chỉ xác thực key."
            )
    else:
        await upsert_user_key(
            user_id=db_user["id"],
            server_id=server["id"],
            api_key=normalized_key,
            api_token_id=token_data.get("id"),
            label=mask_api_key(normalized_key),
        )

    # Hiện gói topup
    products = await get_active_products_by_category(
        cat_id, server_id=server_id, product_type="key_topup"
    )
    if not products:
        await message.answer(
            "📦 Chưa có gói nạp cho server này.",
            reply_markup=back_only_kb(BackServersCB(cat_id=cat_id, action="topup")),
        )
        return

    # Hiện số dư hiện tại của key
    extra_text = ("\n" + "\n".join(accrual_lines)) if accrual_lines else ""
    current_quota = token_data.get("remain_quota", 0)
    mult = server.get("quota_multiple", 1.0) or 1.0
    current_dollar = quota_to_dollar(current_quota, mult)

    per_page = await get_setting_int("pagination_size", 6)
    await message.answer(
        f"💳 <b>Nạp key</b>: <code>{mask_api_key(normalized_key)}</code>\n"
        f"💵 Số dư hiện tại: <b>{current_dollar}</b>{extra_text}\n\nChọn gói nạp:",
        reply_markup=products_kb(
            products, cat_id=cat_id, srv_id=server_id,
            ptype="key_topup", page=0, per_page=per_page,
            action="topup",
        ),
        parse_mode="HTML",
    )


@router.message(ApiKeyStates.waiting_key_search)
async def key_search_received(
    message: Message,
    state: FSMContext,
    db_user: dict,
) -> None:
    """Nhận từ khóa ngắn để tìm key đã lưu trên server hiện tại."""
    keyword = (message.text or "").strip()
    fsm_data = await state.get_data()
    server_id = int(fsm_data.get("current_server_id") or 0)
    cat_id = int(fsm_data.get("current_cat_id") or 0)
    search_back = (
        BackKeyInputCB(server_id=server_id, cat_id=cat_id)
        if server_id and cat_id
        else "cat"
    )

    if len(keyword) < 4:
        await message.answer(
            "❌ Từ khóa quá ngắn. Hãy nhập ít nhất 4 ký tự cuối của key.",
            reply_markup=back_only_kb(search_back),
        )
        return

    if not server_id or not cat_id:
        await state.clear()
        await message.answer(
            "⚠️ Phiên tìm key đã hết hạn. Vui lòng mở lại mục Sản phẩm và chọn server để nạp key.",
            reply_markup=back_only_kb("cat"),
        )
        return

    server = await get_server_by_id(server_id)
    if not server:
        await state.clear()
        await message.answer(
            "❌ Server không tồn tại.",
            reply_markup=back_only_kb(BackServersCB(cat_id=cat_id, action="topup")),
        )
        return

    matched_keys = await search_user_keys(
        db_user["id"],
        server_id=server_id,
        keyword=keyword,
    )
    total_count = len(await get_user_keys(db_user["id"], server_id=server_id))

    if not matched_keys:
        await message.answer(
            "❌ Không tìm thấy key phù hợp trong danh sách đã lưu.\n\n"
            "Hãy thử nhập lại vài ký tự cuối khác, hoặc quay lại để dán full key.",
            reply_markup=back_only_kb(search_back),
        )
        return

    await state.set_state(None)
    await message.answer(
        f"🔎 <b>Kết quả tìm key — {server['name']}</b>\n\n"
        f"Tìm thấy <b>{len(matched_keys)}</b> key phù hợp. Chọn key bạn muốn nạp:",
        reply_markup=my_key_search_results_kb(
            matched_keys,
            server_id=server_id,
            cat_id=cat_id,
            total_count=total_count,
        ),
        parse_mode="HTML",
    )


# ── Custom dollar amount ────────────────────────────────────────────────────

@router.callback_query(CustomAmountCB.filter())
async def custom_amount_prompt(
    callback: CallbackQuery,
    callback_data: CustomAmountCB,
    state: FSMContext,
) -> None:
    """Yêu cầu nhập số $ custom."""
    await state.update_data(
        current_cat_id=callback_data.cat_id,
        key_action=callback_data.action,
        current_server_id=callback_data.server_id,
    )
    await callback.message.edit_text(
        "💵 <b>Nhập số dollar ($)</b>\n\n"
        "Nhập số $ bạn muốn nạp vào key:\n"
        "Ví dụ: <code>10</code> hoặc <code>25.5</code>",
        reply_markup=back_only_kb(
            BackCustomAmountCB(
                server_id=callback_data.server_id,
                cat_id=callback_data.cat_id,
                action=callback_data.action,
            )
        ),
        parse_mode="HTML",
    )
    await state.set_state(ApiKeyStates.waiting_custom_dollar)
    await callback.answer()


@router.message(ApiKeyStates.waiting_custom_dollar)
async def custom_dollar_received(
    message: Message,
    state: FSMContext,
    db_user: dict,
) -> None:
    """Nhận số $ → tính VNĐ → tạo order → hiện payment."""
    text = message.text.strip().replace(",", ".").replace("$", "")
    fsm_data = await state.get_data()
    server_id = fsm_data.get("current_server_id", 0)
    cat_id = fsm_data.get("current_cat_id", 0)
    action = fsm_data.get("key_action", "new")
    existing_key = fsm_data.get("existing_key")
    custom_amount_back = (
        BackCustomAmountCB(server_id=server_id, cat_id=cat_id, action=action)
        if server_id and cat_id
        else "cat"
    )

    try:
        dollar_amount = float(text)
    except ValueError:
        await message.answer(
            "❌ Vui lòng nhập số hợp lệ. Ví dụ: <code>10</code>",
            parse_mode="HTML",
            reply_markup=back_only_kb(custom_amount_back),
        )
        return

    if dollar_amount <= 0:
        await message.answer(
            "❌ Số tiền phải lớn hơn 0.",
            parse_mode="HTML",
            reply_markup=back_only_kb(custom_amount_back),
        )
        return

    if not server_id or not cat_id:
        await state.clear()
        await message.answer(
            "⚠️ Phiên nhập số tiền đã hết hạn sau khi bot khởi động lại hoặc do tin nhắn cũ. "
            "Vui lòng mở lại mục Sản phẩm và chọn lại server/gói.",
            reply_markup=back_only_kb("cat"),
        )
        return

    if action == "new" and dollar_amount < 10:
        await message.answer(
            "❌ Số tiền tối thiểu mua key mới là $10.",
            parse_mode="HTML",
            reply_markup=back_only_kb(custom_amount_back),
        )
        return

    if action == "topup" and dollar_amount < 1:
        await message.answer(
            "❌ Số tiền tối thiểu nạp key cũ là $1.",
            parse_mode="HTML",
            reply_markup=back_only_kb(custom_amount_back),
        )
        return

    server = await get_server_by_id(server_id)
    if not server:
        await message.answer(
            "❌ Server không tồn tại.",
            reply_markup=back_only_kb(BackServersCB(cat_id=cat_id, action=action)),
        )
        await state.clear()
        return

    # Tính quota và VNĐ từ server config
    multiple = server.get("quota_multiple", 1.0) or 1.0
    quota_per_unit = server.get("quota_per_unit", 500000)
    price_per_unit = server.get("price_per_unit", 31000)

    dollar_per_unit = server.get("dollar_per_unit", 10.0)
    if dollar_per_unit <= 0:
        dollar_per_unit = 10.0

    # Tỷ giá 1$ = giá 1 unit / số dollar 1 unit
    price_per_dollar = price_per_unit / dollar_per_unit

    # Quota cho mỗi $ = quota 1 unit / dollar 1 unit
    quota_per_dollar_server = quota_per_unit / dollar_per_unit

    logger.info(
        "Custom dollar calc: $%.2f, price/unit=%d, $/unit=%.2f -> tỷ giá=%.2f",
        dollar_amount, price_per_unit, dollar_per_unit, price_per_dollar
    )

    # Quota chuyển vào API
    custom_quota = int(dollar_amount * quota_per_dollar_server * multiple)

    # VNĐ
    vnd_amount = int(dollar_amount * price_per_dollar)

    # Tối thiểu 1,000₫ (giới hạn ngân hàng)
    if vnd_amount < 1000:
        vnd_amount = 1000

    logger.info("Custom dollar result: quota=%d, vnd=%d", custom_quota, vnd_amount)

    quote = await quote_api_order(
        user_id=db_user["id"],
        server=server,
        custom_dollar=dollar_amount,
    )
    custom_quota = quote.quota_amount
    vnd_amount = quote.payable_amount
    base_amount = quote.base_amount
    if vnd_amount < 1000:
        vnd_amount = 1000
        if base_amount < 1000:
            base_amount = 1000
        quote.spend_credit_amount = vnd_amount

    await state.set_state(None)

    # Tạo product type
    product_type = "key_new" if action == "new" else "key_topup"

    # Build detail text
    rate_vnd_per_dollar = int(base_amount / dollar_amount) if dollar_amount > 0 else 0
    lines = [
        f"💵 <b>Nạp ${dollar_amount:,.2f}</b>",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"💰 Cần thanh toán: <b>{format_vnd(vnd_amount)}</b>",
        f"📊 Tỷ giá: <b>{format_vnd(rate_vnd_per_dollar)}/$</b>",
        f"🖥 Server: <b>{server['name']}</b>",
    ]
    if action == "new":
        display_group = await format_group_display_names(server.get("default_group"), server)
        if display_group:
            lines.append(f"👥 Group mặc định của server: <b>{display_group}</b>")
    if existing_key:
        lines.append(f"🔑 Key nạp: <code>{mask_api_key(existing_key)}</code>")
    if quote.discount_amount > 0:
        lines.append(f"🏷 Giá gốc: <b>{format_vnd(base_amount)}</b>")
        lines.append(f"💸 Giảm giá tier: <b>-{format_vnd(quote.discount_amount)}</b>")
    if quote.cashback_amount > 0:
        lines.append(f"🪙 Cashback sau thanh toán: <b>{format_vnd(quote.cashback_amount)}</b>")

    # Tạo order
    order_code = generate_order_code()
    expire_min = await get_setting_int("order_expire_min", 30)
    expired_at = (get_now_vn() + timedelta(minutes=expire_min)).isoformat()

    order_id = await create_order(
        order_code=order_code,
        user_id=db_user["id"],
        product_type=product_type,
        amount=vnd_amount,
        payment_method="qr",
        product_name=f"Custom ${dollar_amount:,.2f}",
        server_id=server_id,
        group_name=server.get("default_group") or None,
        existing_key=existing_key,
        custom_quota=custom_quota,
        expired_at=expired_at,
        base_amount=base_amount,
        discount_amount=quote.discount_amount,
        cashback_amount=quote.cashback_amount,
        spend_credit_amount=quote.spend_credit_amount,
        pricing_version_id=quote.pricing_version_id,
        applied_tier_id=quote.applied_tier_id,
        pricing_snapshot=json.dumps(quote.pricing_snapshot, ensure_ascii=True),
    )

    await state.update_data(current_order_id=order_id)

    # Hiện balance ví
    balance = await get_balance(db_user["id"])

    lines.extend([
        f"━━━━━━━━━━━━━━━━━━━━",
        f"🔖 Mã đơn: <code>{order_code}</code>",
        f"\nChọn phương thức thanh toán:",
        f"👛 Số dư ví: <b>{format_vnd(balance)}</b>",
    ])

    # QR chỉ hiện khi số lượng $ >= 10
    show_qr = dollar_amount >= 10

    if not show_qr:
        lines.append(f"⚠️ Dưới $10 chỉ hỗ trợ thanh toán bằng ví nội bộ.")

    await message.answer(
        "\n".join(lines),
        reply_markup=payment_method_kb(order_id, show_qr=show_qr),
        parse_mode="HTML",
    )


# ── Chọn thanh toán ─────────────────────────────────────────────────────────

@router.callback_query(PaymentMethodCB.filter(F.method == "qr"))
async def payment_qr(
    callback: CallbackQuery,
    callback_data: PaymentMethodCB,
    db_user: dict,
) -> None:
    """Thanh toán QR → tạo mã QR + chờ poller xử lý."""
    order = await get_order_by_id(callback_data.order_id)
    if not order or order["user_id"] != db_user["id"]:
        await callback.answer("❌ Đơn không tồn tại.", show_alert=True)
        return

    if order["status"] != "pending":
        await callback.answer("❌ Đơn đã được xử lý.", show_alert=True)
        return

    # Cập nhật payment_method
    from db.queries.orders import update_order_status
    await update_order_status(order["id"], "pending", payment_method="qr")

    expire_min = await get_setting_int("order_expire_min", 30)
    qr_url = await build_qr_url(order["amount"], order["order_code"])
    caption = await build_qr_caption(order["amount"], order["order_code"], expire_min)

    # Xóa inline message, gửi ảnh QR
    from bot.keyboards.inline_kb import order_cancel_kb
    await callback.message.delete()
    await callback.message.answer_photo(
        photo=qr_url,
        caption=caption,
        parse_mode="HTML",
        reply_markup=order_cancel_kb(order["id"])
    )
    await callback.answer()


@router.callback_query(PaymentMethodCB.filter(F.method == "wallet"))
async def payment_wallet(
    callback: CallbackQuery,
    callback_data: PaymentMethodCB,
    db_user: dict,
) -> None:
    """Thanh toán bằng ví → xử lý ngay."""
    order = await get_order_by_id(callback_data.order_id)
    if not order or order["user_id"] != db_user["id"]:
        await callback.answer("❌ Đơn không tồn tại.", show_alert=True)
        return

    if order["status"] != "pending":
        await callback.answer("❌ Đơn đã được xử lý.", show_alert=True)
        return

    # Kiểm tra số dư
    balance = await get_balance(db_user["id"])
    if balance < order["amount"]:
        await callback.answer(
            f"❌ Số dư không đủ! Cần {format_vnd(order['amount'])}, "
            f"hiện có {format_vnd(balance)}.",
            show_alert=True,
        )
        return

    # Xử lý thanh toán ví ngay
    await callback.message.edit_text(
        f"⏳ Đang xử lý thanh toán đơn <b>{order['order_code']}</b>...",
        parse_mode="HTML",
    )

    bot = callback.bot
    success = await process_wallet_payment(bot, order["id"])

    if not success:
        show_qr = True
        product_name = str(order.get("product_name") or "")
        if product_name.startswith("Custom $"):
            try:
                show_qr = float(product_name.removeprefix("Custom $").replace(",", "").strip()) >= 10
            except ValueError:
                show_qr = True
        await callback.message.edit_text(
            f"❌ Thanh toán đơn <b>{order['order_code']}</b> thất bại.\n"
            f"Vui lòng kiểm tra số dư ví hoặc chọn phương thức khác.",
            parse_mode="HTML",
            reply_markup=payment_method_kb(order["id"], show_qr=show_qr),
        )

    await callback.answer()


# ── Back to servers ─────────────────────────────────────────────────────────

@router.callback_query(BackServersCB.filter())
async def back_to_servers(
    callback: CallbackQuery,
    callback_data: BackServersCB,
    state: FSMContext,
) -> None:
    """Quay lại danh sách server."""
    action = callback_data.action
    await state.update_data(current_cat_id=callback_data.cat_id, key_action=action)

    servers = await get_active_servers()
    if not servers:
        await callback.message.edit_text(
            "🖥 Chưa có server nào.",
            reply_markup=back_only_kb("cat"),
        )
        await callback.answer()
        return

    action_text = "🔑 Mua key mới" if action == "new" else "💳 Nạp key cũ"
    await callback.message.edit_text(
        f"{action_text}\n\nChọn server:",
        reply_markup=servers_kb(servers, cat_id=callback_data.cat_id, action=action),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(BackKeyInputCB.filter())
async def back_from_key_input(
    callback: CallbackQuery,
    callback_data: BackKeyInputCB,
    state: FSMContext,
    db_user: dict,
) -> None:
    """Quay từ màn nhập key về danh sách key/server topup."""
    await state.set_state(None)
    await state.update_data(
        current_server_id=callback_data.server_id,
        current_cat_id=callback_data.cat_id,
        key_action="topup",
    )

    if not await _show_existing_keys_for_server(
        callback,
        user_id=db_user["id"],
        server_id=callback_data.server_id,
        cat_id=callback_data.cat_id,
    ):
        await callback.answer(
            "⚠️ Danh sách key cũ không còn khả dụng. Bot sẽ đưa bạn về danh sách server.",
            show_alert=True,
        )
        await back_to_servers(
            callback,
            BackServersCB(cat_id=callback_data.cat_id, action="topup"),
            state,
        )
        return
    await callback.answer()


@router.callback_query(BackCustomAmountCB.filter())
async def back_from_custom_amount(
    callback: CallbackQuery,
    callback_data: BackCustomAmountCB,
    state: FSMContext,
) -> None:
    """Quay từ màn nhập số $ về danh sách gói của server hiện tại."""
    await state.set_state(None)
    await state.update_data(
        current_server_id=callback_data.server_id,
        current_cat_id=callback_data.cat_id,
        key_action=callback_data.action,
    )
    if not await _show_key_products_for_server(
        callback,
        cat_id=callback_data.cat_id,
        server_id=callback_data.server_id,
        action=callback_data.action,
    ):
        await callback.answer(
            "⚠️ Màn gói nạp cũ không còn khả dụng. Bot sẽ đưa bạn về danh sách server.",
            show_alert=True,
        )
        await back_to_servers(
            callback,
            BackServersCB(cat_id=callback_data.cat_id, action=callback_data.action),
            state,
        )
        return
    await callback.answer()


@router.callback_query(F.data.regexp(r"^srv:[^:]+:\d+$"))
async def legacy_server_select(
    callback: CallbackQuery,
    state: FSMContext,
    db_user: dict,
) -> None:
    """Tương thích ngược cho callback chọn server từ keyboard cũ."""
    _, action, server_id_text = (callback.data or "").split(":")
    fsm_data = await state.get_data()
    cat_id = int(fsm_data.get("current_cat_id") or 0)
    if not cat_id:
        await callback.answer("⚠️ Keyboard cũ đã hết hạn. Bot sẽ mở lại danh mục sản phẩm.", show_alert=True)
        await _show_expired_catalog_prompt(
            callback,
            state,
            "⚠️ Keyboard cũ không còn đủ dữ liệu sau khi bot cập nhật hoặc khởi động lại.",
        )
        return

    await select_server(
        callback,
        ServerSelectCB(cat_id=cat_id, action=action, server_id=int(server_id_text)),
        state,
        db_user,
    )


@router.callback_query(F.data.regexp(r"^mki:\d+$"))
async def legacy_key_input_prompt(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Tương thích ngược cho nút nhập key mới từ keyboard cũ."""
    _, server_id_text = (callback.data or "").split(":")
    fsm_data = await state.get_data()
    cat_id = int(fsm_data.get("current_cat_id") or 0)
    if not cat_id:
        await callback.answer("⚠️ Keyboard cũ đã hết hạn. Bot sẽ mở lại danh mục sản phẩm.", show_alert=True)
        await _show_expired_catalog_prompt(
            callback,
            state,
            "⚠️ Nút nhập key này thuộc phiên thao tác cũ và không còn đủ ngữ cảnh.",
        )
        return

    await input_key_prompt(
        callback,
        MyKeyInputCB(server_id=int(server_id_text), cat_id=cat_id),
        state,
    )


@router.callback_query(F.data.regexp(r"^ca:[^:]+:\d+$"))
async def legacy_custom_amount_prompt(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Tương thích ngược cho nút nhập số $ custom từ keyboard cũ."""
    _, action, server_id_text = (callback.data or "").split(":")
    fsm_data = await state.get_data()
    cat_id = int(fsm_data.get("current_cat_id") or 0)
    if not cat_id:
        await callback.answer("⚠️ Keyboard cũ đã hết hạn. Bot sẽ mở lại danh mục sản phẩm.", show_alert=True)
        await _show_expired_catalog_prompt(
            callback,
            state,
            "⚠️ Nút nhập số tiền này thuộc phiên thao tác cũ và không còn đủ ngữ cảnh.",
        )
        return

    await custom_amount_prompt(
        callback,
        CustomAmountCB(cat_id=cat_id, action=action, server_id=int(server_id_text)),
        state,
    )


@router.callback_query(F.data.in_({"back:srv", "back:key_input_back", "back:custom_amount_back"}))
async def legacy_back_navigation(
    callback: CallbackQuery,
    state: FSMContext,
    db_user: dict,
) -> None:
    """Tương thích ngược cho các nút back cũ trước khi callback_data được mở rộng."""
    data = callback.data or ""
    fsm_data = await state.get_data()
    server_id = int(fsm_data.get("current_server_id") or 0)
    cat_id = int(fsm_data.get("current_cat_id") or 0)
    action = str(fsm_data.get("key_action") or "new")

    if data == "back:srv" and cat_id:
        await back_to_servers(callback, BackServersCB(cat_id=cat_id, action=action), state)
        return

    if data == "back:key_input_back" and server_id and cat_id:
        await back_from_key_input(
            callback,
            BackKeyInputCB(server_id=server_id, cat_id=cat_id),
            state,
            db_user,
        )
        return

    if data == "back:custom_amount_back" and server_id and cat_id:
        await back_from_custom_amount(
            callback,
            BackCustomAmountCB(server_id=server_id, cat_id=cat_id, action=action),
            state,
        )
        return

    await callback.answer("⚠️ Keyboard cũ đã hết hạn. Bot sẽ mở lại danh mục sản phẩm.", show_alert=True)
    await _show_expired_catalog_prompt(
        callback,
        state,
        "⚠️ Phiên thao tác cũ không còn khả dụng sau khi bot khởi động lại hoặc được cập nhật.",
    )
