"""
bot/middlewares/auth.py — Middleware auto-register user.
Chạy trước mọi handler:
  1. Lấy hoặc tạo user trong DB dựa trên Telegram info
  2. Tạo wallet nếu chưa có
  3. Inject db_user vào handler data
  4. Block user bị ban
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

from db.queries.users import get_user_by_telegram_id, create_user, update_user
from db.queries.wallets import ensure_wallet

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseMiddleware):
    """
    Outer middleware: tự động đăng ký user mới,
    cập nhật thông tin, inject db_user vào handler data.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Lấy thông tin user từ event
        user_info = self._extract_user(event)
        if not user_info:
            # Event không có user (channel post, etc.) → bỏ qua middleware
            return await handler(event, data)

        telegram_id = user_info["telegram_id"]
        username = user_info.get("username")
        full_name = user_info.get("full_name")

        # Tìm hoặc tạo user trong DB
        db_user = await get_user_by_telegram_id(telegram_id)

        if db_user is None:
            # User mới → tạo account + wallet
            db_user = await create_user(
                telegram_id=telegram_id,
                username=username,
                full_name=full_name,
            )
            await ensure_wallet(db_user["id"])
            logger.info(
                "New user registered: %s (tg_id=%d)",
                full_name or username or "unknown",
                telegram_id,
            )
        else:
            # User đã tồn tại → cập nhật thông tin nếu thay đổi
            if db_user.get("username") != username or db_user.get("full_name") != full_name:
                await update_user(db_user["id"], username=username, full_name=full_name)
                db_user["username"] = username
                db_user["full_name"] = full_name

        # Kiểm tra user bị ban
        if db_user.get("is_banned"):
            if isinstance(event, Message):
                await event.answer("🚫 Tài khoản của bạn đã bị khóa.")
            elif isinstance(event, CallbackQuery):
                await event.answer("🚫 Tài khoản đã bị khóa.", show_alert=True)
            return  # Không chạy handler

        # Inject db_user vào handler data
        data["db_user"] = db_user

        return await handler(event, data)

    @staticmethod
    def _extract_user(event: TelegramObject) -> dict | None:
        """Trích xuất thông tin Telegram user từ event."""
        from_user = None

        if isinstance(event, Message):
            from_user = event.from_user
        elif isinstance(event, CallbackQuery):
            from_user = event.from_user

        if not from_user:
            return None

        return {
            "telegram_id": from_user.id,
            "username": from_user.username,
            "full_name": from_user.full_name,
        }
