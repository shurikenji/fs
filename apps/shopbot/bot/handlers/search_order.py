"""
bot/handlers/search_order.py — Tìm đơn hàng theo mã đơn.
"""
from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.keyboards.inline_kb import back_only_kb
from bot.utils.formatting import (
    format_vnd, status_emoji, status_text_vi,
    payment_method_text, format_time_vn
)
from db.queries.orders import get_order_by_code

router = Router(name="search_order")


class SearchOrderStates(StatesGroup):
    waiting_order_code = State()


@router.message(Command("search"))
@router.message(F.text == "🔎 Tìm đơn")
async def search_order_prompt(message: Message, state: FSMContext) -> None:
    """Yêu cầu nhập mã đơn hàng."""
    await message.answer(
        "🔎 <b>Tìm đơn hàng</b>\n\n"
        "Nhập mã đơn hàng (vd: <code>ORD1A2B3C4D</code>):",
        parse_mode="HTML",
        reply_markup=back_only_kb("main"),
    )
    await state.set_state(SearchOrderStates.waiting_order_code)


@router.message(SearchOrderStates.waiting_order_code)
async def search_order_input(
    message: Message,
    state: FSMContext,
    db_user: dict,
) -> None:
    """Tìm đơn hàng theo mã được nhập."""
    code = message.text.strip().upper()
    if not code.startswith("ORD") or len(code) != 11:
        await message.answer(
            "❌ Mã đơn không hợp lệ.\n"
            "Mã đơn có format: <code>ORDxxxxxxxx</code> (ORD + 8 ký tự)",
            parse_mode="HTML",
            reply_markup=back_only_kb("main"),
        )
        return

    order = await get_order_by_code(code)

    if not order:
        await message.answer(
            f"❌ Không tìm thấy đơn hàng <b>{code}</b>",
            parse_mode="HTML",
            reply_markup=back_only_kb("main"),
        )
        return

    # Chỉ cho xem đơn của chính mình
    if order["user_id"] != db_user["id"]:
        await message.answer(
            f"❌ Đơn hàng <b>{code}</b> không thuộc về bạn.",
            parse_mode="HTML",
            reply_markup=back_only_kb("main"),
        )
        return

    emoji = status_emoji(order["status"])
    status = status_text_vi(order["status"])
    pay_method = payment_method_text(order["payment_method"])

    lines = [
        f"🔎 <b>Kết quả tìm kiếm</b>",
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

    if order.get("api_key"):
        lines.append(f"\n🔑 API Key: <code>{order['api_key']}</code>")
    if order.get("delivery_info"):
        lines.append(f"\n📦 Giao hàng:\n<code>{order['delivery_info']}</code>")

    await state.clear()
    await message.answer("\n".join(lines), parse_mode="HTML")
