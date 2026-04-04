"""
bot/handlers/support.py — Link hỗ trợ.
"""
from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

from bot.keyboards.reply_kb import main_menu_kb
from db.queries.settings import get_setting

router = Router(name="support")


@router.message(Command("support"))
@router.message(F.text == "🆘 Hỗ trợ")
async def support_info(message: Message) -> None:
    """Hiện thông tin hỗ trợ."""
    support_url = await get_setting("support_url") or "https://t.me/yoursupport"
    support_text = await get_setting("support_text") or "Liên hệ admin để được hỗ trợ"
    bot_name = await get_setting("bot_name") or "ShopBot"

    text = (
        f"🆘 <b>Hỗ trợ — {bot_name}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{support_text}\n\n"
        f"📩 Liên hệ: {support_url}\n\n"
        f"💡 <i>Khi liên hệ, vui lòng cung cấp mã đơn hàng để được hỗ trợ nhanh hơn.</i>"
    )

    await message.answer(text, parse_mode="HTML", reply_markup=main_menu_kb())
