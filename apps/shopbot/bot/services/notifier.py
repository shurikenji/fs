"""
bot/services/notifier.py - Shared Telegram notification helpers.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import settings
from db.queries.settings import get_setting
from db.queries.users import get_user_by_id

logger = logging.getLogger(__name__)


def _parse_chat_ids(raw_ids: str | None) -> list[int]:
    return [
        int(chunk.strip())
        for chunk in (raw_ids or "").split(",")
        if chunk.strip().isdigit()
    ]


@asynccontextmanager
async def _resolve_bot(bot: Bot | None = None) -> AsyncIterator[Bot | None]:
    """Yield an existing bot or create a temporary one when needed."""
    if bot is not None:
        yield bot
        return

    if not settings.bot_token:
        logger.warning("BOT_TOKEN is not configured; skipping Telegram notification")
        yield None
        return

    temp_bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        yield temp_bot
    finally:
        await temp_bot.session.close()


_TG_MAX_LENGTH = 4000  # Telegram limit is 4096; leave margin for safety


def _split_message(text: str, max_length: int = _TG_MAX_LENGTH) -> list[str]:
    """Split a long message into chunks that fit within Telegram's limit.

    Splits at newline boundaries when possible to avoid cutting mid-line.
    """
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        # Try to split at last newline within the limit
        split_at = remaining.rfind("\n", 0, max_length)
        if split_at <= 0:
            # No newline found; hard-cut at max_length
            split_at = max_length

        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip("\n")

    return chunks


async def send_text(bot: Bot, chat_id: int, text: str) -> bool:
    """Send a Telegram message and return whether it succeeded.

    Automatically splits messages that exceed Telegram's 4096-char limit.
    """
    try:
        for chunk in _split_message(text):
            await bot.send_message(chat_id=chat_id, text=chunk)
        return True
    except Exception as exc:
        logger.error("Cannot send Telegram message to %s: %s", chat_id, exc)
        return False


async def notify_user(user_id: int, text: str, *, bot: Bot | None = None) -> bool:
    """Send a message to a user by internal user id."""
    user = await get_user_by_id(user_id)
    if not user or not user.get("telegram_id"):
        return False

    async with _resolve_bot(bot) as active_bot:
        if active_bot is None:
            return False
        return await send_text(active_bot, int(user["telegram_id"]), text)


async def notify_admins(
    text: str,
    *,
    bot: Bot | None = None,
    admin_ids_raw: str | None = None,
) -> tuple[int, int]:
    """Send a message to all configured admins."""
    admin_ids = await resolve_admin_chat_ids(admin_ids_raw=admin_ids_raw)
    if not admin_ids:
        return 0, 0

    async with _resolve_bot(bot) as active_bot:
        if active_bot is None:
            return 0, len(admin_ids)

        sent = 0
        failed = 0
        for chat_id in admin_ids:
            if await send_text(active_bot, chat_id, text):
                sent += 1
            else:
                failed += 1
        return sent, failed


async def resolve_admin_chat_ids(*, admin_ids_raw: str | None = None) -> list[int]:
    """Resolve configured admin Telegram chat ids."""
    raw_ids = admin_ids_raw
    if raw_ids is None:
        raw_ids = await get_setting("admin_telegram_ids") or settings.admin_telegram_ids
    return _parse_chat_ids(raw_ids)


async def broadcast_text(
    chat_ids: Iterable[int],
    text: str,
    *,
    bot: Bot | None = None,
    delay_seconds: float = 0.05,
) -> tuple[int, int]:
    """Broadcast a message to many chat ids with a small rate-limit delay."""
    async with _resolve_bot(bot) as active_bot:
        if active_bot is None:
            chat_ids_list = list(chat_ids)
            return 0, len(chat_ids_list)

        sent = 0
        failed = 0
        for chat_id in chat_ids:
            if await send_text(active_bot, chat_id, text):
                sent += 1
            else:
                failed += 1
            await asyncio.sleep(delay_seconds)
        return sent, failed
