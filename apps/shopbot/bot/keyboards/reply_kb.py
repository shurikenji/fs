"""
bot/keyboards/reply_kb.py — Reply keyboard chính (6 nút, 2 cột).
Luôn hiển thị dưới chat khi user tương tác.
"""
from __future__ import annotations

from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

PRIMARY_MENU_BUTTON_TEXT = "🛒 Mua hàng"


def primary_menu_label() -> str:
    """Nhãn CTA chính dùng trong message hướng dẫn."""
    return PRIMARY_MENU_BUTTON_TEXT.split(" ", 1)[1] if " " in PRIMARY_MENU_BUTTON_TEXT else PRIMARY_MENU_BUTTON_TEXT


def main_menu_kb() -> ReplyKeyboardMarkup:
    """Reply keyboard chính — 6 nút chia 2 cột."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=PRIMARY_MENU_BUTTON_TEXT),
                KeyboardButton(text="👛 Ví"),
            ],
            [
                KeyboardButton(text="📋 Đơn hàng"),
                KeyboardButton(text="🔎 Tìm đơn"),
            ],
            [
                KeyboardButton(text="👤 Tài khoản"),
                KeyboardButton(text="🆘 Hỗ trợ"),
            ],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )
