"""
bot/handlers/orders.py — Danh sách đơn hàng + chi tiết.
"""
from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from bot.callback_data.factories import OrderListPageCB, OrderDetailCB, BackCB
from bot.keyboards.inline_kb import orders_list_kb, order_detail_kb
from bot.utils.group_labels import format_group_display_names
from bot.utils.formatting import (
    format_vnd, status_emoji, status_text_vi,
    payment_method_text, mask_api_key, quota_to_dollar,
    format_time_vn
)
from db.queries.orders import (
    get_orders_by_user, count_orders_by_user,
    get_order_by_id, cancel_order,
)
from db.queries.servers import get_server_by_id
from db.queries.settings import get_setting_int
from bot.callback_data.factories import OrderCancelCB

router = Router(name="orders")


def _order_not_found_text() -> str:
    return "❌ Đơn hàng không tồn tại."


def _cannot_cancel_order_text() -> str:
    return "❌ Chỉ có thể hủy đơn đang chờ thanh toán."


def _cancelled_order_text(order: dict) -> str:
    return f"🚫 Đơn <b>{order['order_code']}</b> đã được hủy."


async def _get_owned_order_or_alert(
    callback: CallbackQuery,
    order_id: int,
    user_id: int,
) -> dict | None:
    order = await get_order_by_id(order_id)
    if not order or order["user_id"] != user_id:
        await callback.answer(_order_not_found_text(), show_alert=True)
        return None
    return order


# ── Reply keyboard trigger ──────────────────────────────────────────────────

@router.message(Command("orders"))
@router.message(F.text == "📋 Đơn hàng")
async def orders_list(message: Message, db_user: dict) -> None:
    """Hiện danh sách đơn hàng."""
    await _show_orders(message, db_user, page=0)


async def _show_orders(
    target: Message | CallbackQuery,
    db_user: dict,
    page: int,
) -> None:
    """Helper hiện danh sách đơn hàng."""
    per_page = await get_setting_int("pagination_size", 6)
    total = await count_orders_by_user(db_user["id"])

    if total == 0:
        text = "📋 <b>Đơn hàng của bạn</b>\n\nBạn chưa có đơn hàng nào."
        if isinstance(target, CallbackQuery):
            await target.message.edit_text(text, parse_mode="HTML")
            await target.answer()
        else:
            await target.answer(text, parse_mode="HTML")
        return

    orders = await get_orders_by_user(
        db_user["id"], offset=page * per_page, limit=per_page
    )

    text = f"📋 <b>Đơn hàng của bạn</b> ({total} đơn)"
    kb = orders_list_kb(orders, page=page, per_page=per_page, total_count=total)

    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await target.answer()
    else:
        await target.answer(text, reply_markup=kb, parse_mode="HTML")


# ── Phân trang ──────────────────────────────────────────────────────────────

@router.callback_query(OrderListPageCB.filter())
async def orders_page(
    callback: CallbackQuery,
    callback_data: OrderListPageCB,
    db_user: dict,
) -> None:
    """Chuyển trang danh sách đơn hàng."""
    await _show_orders(callback, db_user, page=callback_data.page)


# ── Chi tiết đơn hàng ──────────────────────────────────────────────────────

@router.callback_query(OrderDetailCB.filter())
async def order_detail(
    callback: CallbackQuery,
    callback_data: OrderDetailCB,
    db_user: dict,
) -> None:
    """Xem chi tiết đơn hàng."""
    order = await get_order_by_id(callback_data.order_id)

    if not order or order["user_id"] != db_user["id"]:
        await callback.answer("❌ Đơn hàng không tồn tại.", show_alert=True)
        return

    emoji = status_emoji(order["status"])
    status = status_text_vi(order["status"])
    pay_method = payment_method_text(order["payment_method"])
    server = None
    if order.get("server_id"):
        server = await get_server_by_id(order["server_id"])

    lines = [
        f"📋 <b>Chi tiết đơn hàng</b>",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"🔖 Mã đơn: <code>{order['order_code']}</code>",
        f"📦 Sản phẩm: <b>{order.get('product_name', 'N/A')}</b>",
        f"💰 Số tiền: <b>{format_vnd(order['amount'])}</b>",
        f"💳 Thanh toán: {pay_method}",
        f"{emoji} Trạng thái: <b>{status}</b>",
        f"📅 Tạo lúc: <i>{format_time_vn(order.get('created_at', ''))}</i>",
    ]
    quantity = int(order.get("quantity") or 1)
    if quantity > 1:
        lines.append(f"🔢 Số lượng: <b>x{quantity}</b>")
    if order.get("product_type") == "key_new" and order.get("group_name"):
        display_group = await format_group_display_names(order.get("group_name"), server)
        lines.append(f"👥 Group: <b>{display_group or order['group_name']}</b>")

    # Thông tin key nếu có
    if order.get("api_key"):
        lines.append(f"\n🔑 API Key: <code>{order['api_key']}</code>")
    if order.get("quota_before") is not None and order.get("quota_after") is not None:
        mult = 1.0
        if server:
            mult = server.get("quota_multiple") or 1.0
        
        qb = order["quota_before"]
        qa = order["quota_after"]
        add_q = qa - qb
        
        before_dollar = quota_to_dollar(qb, mult)
        add_dollar = quota_to_dollar(add_q, mult)
        after_dollar = quota_to_dollar(qa, mult)
        
        lines.extend([
            f"\n💵 Số dư trước: <b>{before_dollar}</b>",
            f"💵 Nạp thêm: <b>+{add_dollar}</b>",
            f"💵 Số dư sau: <b>{after_dollar}</b>",
        ])
    if order.get("delivery_info"):
        lines.append(f"\n📦 Giao hàng:\n<code>{order['delivery_info']}</code>")
    if order.get("refund_reason"):
        lines.append(f"\n↩️ Lý do hoàn: {order['refund_reason']}")

    text = "\n".join(lines)

    # Nút hủy nếu đang pending
    kb = order_detail_kb(order["id"], can_cancel=order["status"] == "pending")

    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


# ── Hủy đơn ────────────────────────────────────────────────────────────────

@router.callback_query(OrderCancelCB.filter())
async def cancel_order_cb(
    callback: CallbackQuery,
    callback_data: OrderCancelCB,
    db_user: dict,
) -> None:
    """Hủy đơn hàng pending."""
    order = await _get_owned_order_or_alert(callback, callback_data.order_id, db_user["id"])
    if not order:
        return

    if order["status"] != "pending":
        await callback.answer(_cannot_cancel_order_text(), show_alert=True)
        return

    await cancel_order(order["id"])
    cancel_text = _cancelled_order_text(order)
    if callback.message.photo:
        await callback.message.edit_caption(
            caption=cancel_text,
            parse_mode="HTML",
        )
    else:
        await callback.message.edit_text(
            cancel_text,
            parse_mode="HTML",
        )
    await callback.answer("Đã hủy đơn hàng.")


@router.callback_query(BackCB.filter(F.target == "orders_back"))
async def back_to_orders(callback: CallbackQuery, db_user: dict) -> None:
    """Quay từ chi tiết đơn hàng về danh sách đơn."""
    await _show_orders(callback, db_user, page=0)
