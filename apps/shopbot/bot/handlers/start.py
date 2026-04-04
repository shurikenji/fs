"""
bot/handlers/start.py — /start command + welcome message + reply keyboard.
"""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from bot.keyboards.reply_kb import main_menu_kb, primary_menu_label
from db.queries.settings import get_setting

router = Router(name="start")


async def _send_main_menu(message: Message, db_user: dict, *, show_welcome: bool) -> None:
    """Gửi lại reply keyboard chính cho user."""
    if show_welcome:
        welcome = await get_setting("welcome_message") or "Chào mừng bạn đến với ShopBot!"
        bot_name = await get_setting("bot_name") or "ShopBot"
        bot_description = await get_setting("bot_description") or "Hệ thống bán Key API & ChatGPT tự động"
        name = db_user.get("full_name") or db_user.get("username") or "bạn"
        text = (
            f"👋 Xin chào <b>{name}</b>!\n\n"
            f"{welcome}\n\n"
            f"🤖 <b>{bot_name}</b> — {bot_description}\n\n"
            f"Sử dụng menu bên dưới để bắt đầu 👇"
        )
    else:
        primary_label = primary_menu_label()
        text = (
            "👋 <b>Chào mừng bạn đến với cửa hàng!</b>\n\n"
            f'Nhấn "{primary_label}" để bắt đầu.'
        )

    await message.answer(text, reply_markup=main_menu_kb(), parse_mode="HTML")


@router.message(CommandStart())
async def cmd_start(message: Message, db_user: dict) -> None:
    """Xử lý /start — gửi lời chào + reply keyboard."""
    await _send_main_menu(message, db_user, show_welcome=True)


@router.message(Command("menu"))
async def cmd_menu(message: Message, db_user: dict) -> None:
    """Khôi phục reply keyboard chính mà không cần /start lại."""
    await _send_main_menu(message, db_user, show_welcome=False)
