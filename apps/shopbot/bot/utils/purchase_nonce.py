"""Stable idempotency keys for Telegram purchase events."""
from __future__ import annotations

from hashlib import sha256

from aiogram.types import CallbackQuery, Message


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def callback_purchase_nonce(callback: CallbackQuery) -> str:
    message = callback.message
    if message is None:
        return _digest(f"callback:{callback.from_user.id}:{callback.id}")
    return _digest(
        f"callback:{callback.from_user.id}:{message.chat.id}:{message.message_id}:{callback.data or ''}"
    )


def message_purchase_nonce(message: Message) -> str:
    user_id = message.from_user.id if message.from_user else 0
    return _digest(f"message:{user_id}:{message.chat.id}:{message.message_id}")
