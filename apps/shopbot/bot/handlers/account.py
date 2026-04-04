"""
bot/handlers/account.py — Thông tin tài khoản user.
"""
from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

from bot.keyboards.reply_kb import main_menu_kb
from bot.utils.formatting import format_vnd, format_time_vn
from db.queries.wallets import get_balance
from db.queries.orders import count_orders_by_user
from db.queries.user_keys import get_user_keys

router = Router(name="account")


@router.message(Command("profile"))
@router.message(F.text == "👤 Tài khoản")
async def account_info(message: Message, db_user: dict) -> None:
    """Hiện thông tin tài khoản."""
    balance = await get_balance(db_user["id"])
    total_orders = await count_orders_by_user(db_user["id"])
    keys = await get_user_keys(db_user["id"])
    key_count = len(keys)

    name = db_user.get("full_name") or "N/A"
    username = db_user.get("username")
    username_str = f"@{username}" if username else "N/A"

    text = (
        f"👤 <b>Tài khoản của bạn</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📛 Tên: <b>{name}</b>\n"
        f"🆔 Username: <b>{username_str}</b>\n"
        f"🔢 Telegram ID: <code>{db_user['telegram_id']}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👛 Số dư ví: <b>{format_vnd(balance)}</b>\n"
        f"📋 Tổng đơn: <b>{total_orders}</b>\n"
        f"🔑 Số key: <b>{key_count}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 Ngày tạo: <i>{format_time_vn(db_user.get('created_at', ''))}</i>"
    )

    await message.answer(text, parse_mode="HTML", reply_markup=main_menu_kb())
