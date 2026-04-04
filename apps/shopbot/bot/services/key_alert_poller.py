"""
bot/services/key_alert_poller.py - Poll API keys and notify users when balances are low.
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot

from bot.services.api_clients import get_api_client
from bot.services.key_valuation import hash_api_key, normalize_api_key
from bot.services.notifier import notify_user
from bot.utils.formatting import format_dollar, mask_api_key
from bot.utils.time_utils import to_db_time_string
from db.queries.api_key_alerts import get_api_key_alert_state, upsert_api_key_alert_state
from db.queries.logs import add_log
from db.queries.servers import get_active_servers
from db.queries.settings import get_setting, get_setting_int
from db.queries.user_keys import get_active_user_keys_for_alerts

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_MINUTES = 15
DEFAULT_THRESHOLDS = (5.0, 3.0, 1.0)
REQUEST_PAUSE_SECONDS = 0.15


def _is_truthy(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_thresholds(raw_value: str | None) -> tuple[float, ...]:
    thresholds: set[float] = set()
    for chunk in (raw_value or "").split(","):
        text = chunk.strip()
        if not text:
            continue
        try:
            amount = round(float(text), 4)
        except ValueError:
            continue
        if amount > 0:
            thresholds.add(amount)
    if not thresholds:
        thresholds = set(DEFAULT_THRESHOLDS)
    return tuple(sorted(thresholds, reverse=True))


def _quota_to_dollar_value(quota: int, multiple: float) -> float:
    divisor = 500000 * (multiple if multiple > 0 else 1.0)
    return max(0.0, float(quota) / float(divisor))


def _resolve_alert_level(balance_dollar: float, thresholds: tuple[float, ...]) -> float | None:
    breached = [threshold for threshold in thresholds if balance_dollar <= threshold]
    if not breached:
        return None
    return min(breached)


def _parse_remain_quota(token_data: dict) -> int | None:
    remain_quota = token_data.get("remain_quota")
    if remain_quota is None:
        remain_quota = token_data.get("remainQuota")
    try:
        return max(0, int(remain_quota))
    except (TypeError, ValueError):
        return None


def _parse_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _next_stored_level(previous_level: float | None, current_level: float | None) -> float | None:
    if current_level is None:
        return None
    if previous_level is None:
        return current_level
    if current_level < previous_level:
        return current_level
    if current_level > previous_level:
        return current_level
    return previous_level


def _build_alert_message(*, masked_key_value: str, balance_dollar: float, threshold: float, server_name: str) -> str:
    return (
        "⚠️ API key của bạn sắp hết số dư\n\n"
        f"🔑 Key: <code>{masked_key_value}</code>\n"
        f"💵 Số dư còn lại: <b>{format_dollar(balance_dollar)}</b>\n"
        f"📉 Đã chạm ngưỡng cảnh báo: <b>{format_dollar(threshold)}</b>\n"
        f"🖥 Server: <b>{server_name}</b>\n\n"
        "Bạn nên nạp thêm để tránh gián đoạn sử dụng."
    )


async def start_key_alert_poller(bot: Bot) -> None:
    """Run the low-balance poller loop forever."""
    logger.info("Key alert poller started")
    await add_log("Key alert poller started", module="key_alert")

    while True:
        try:
            interval_minutes = max(
                1,
                await get_setting_int("key_alert_poll_interval_min", DEFAULT_POLL_INTERVAL_MINUTES),
            )
            enabled = _is_truthy(await get_setting("key_alert_enabled", "true"), default=True)
            if enabled:
                await _poll_cycle(bot)
            await asyncio.sleep(interval_minutes * 60)
        except asyncio.CancelledError:
            logger.info("Key alert poller cancelled")
            break
        except Exception as exc:
            logger.error("Key alert poller error: %s", exc, exc_info=True)
            await add_log(f"Key alert poller error: {exc}", level="error", module="key_alert")
            await asyncio.sleep(60)


async def _poll_cycle(bot: Bot) -> None:
    thresholds = _parse_thresholds(await get_setting("key_alert_thresholds", "5,3,1"))
    if not thresholds:
        return

    servers = {int(server["id"]): server for server in await get_active_servers()}
    if not servers:
        return

    user_keys = await get_active_user_keys_for_alerts()
    for user_key in user_keys:
        server = servers.get(int(user_key["server_id"]))
        if server is None:
            continue
        await _check_user_key(bot, user_key=user_key, server=server, thresholds=thresholds)
        await asyncio.sleep(REQUEST_PAUSE_SECONDS)


async def _check_user_key(bot: Bot, *, user_key: dict, server: dict, thresholds: tuple[float, ...]) -> None:
    api_key = normalize_api_key(str(user_key["api_key"]))
    masked_key_value = mask_api_key(api_key)
    api_key_hash = hash_api_key(api_key)
    previous_state = await get_api_key_alert_state(
        user_id=int(user_key["user_id"]),
        server_id=int(server["id"]),
        api_key_hash=api_key_hash,
    )
    previous_level = _parse_float(previous_state.get("last_alert_threshold")) if previous_state else None

    client = get_api_client(server)
    token = await client.search_token(server, api_key)
    if not token:
        await upsert_api_key_alert_state(
            user_id=int(user_key["user_id"]),
            server_id=int(server["id"]),
            api_key_hash=api_key_hash,
            masked_key=masked_key_value,
            last_seen_remain_quota=int(previous_state.get("last_seen_remain_quota") or 0) if previous_state else 0,
            last_seen_balance_dollar=float(previous_state.get("last_seen_balance_dollar") or 0.0) if previous_state else 0.0,
            last_alert_threshold=previous_level,
            last_error="token_not_found",
        )
        return

    remain_quota = _parse_remain_quota(token)
    if remain_quota is None:
        await upsert_api_key_alert_state(
            user_id=int(user_key["user_id"]),
            server_id=int(server["id"]),
            api_key_hash=api_key_hash,
            masked_key=masked_key_value,
            last_seen_remain_quota=int(previous_state.get("last_seen_remain_quota") or 0) if previous_state else 0,
            last_seen_balance_dollar=float(previous_state.get("last_seen_balance_dollar") or 0.0) if previous_state else 0.0,
            last_alert_threshold=previous_level,
            last_error="invalid_remain_quota",
        )
        return

    multiple = float(server.get("quota_multiple") or 1.0)
    balance_dollar = _quota_to_dollar_value(remain_quota, multiple)
    current_level = _resolve_alert_level(balance_dollar, thresholds)

    should_send = current_level is not None and (previous_level is None or current_level < previous_level)
    sent_at: str | None = None
    last_error: str | None = None
    if should_send:
        message = _build_alert_message(
            masked_key_value=masked_key_value,
            balance_dollar=balance_dollar,
            threshold=current_level,
            server_name=str(server["name"]),
        )
        delivered = await notify_user(int(user_key["user_id"]), message, bot=bot)
        if delivered:
            sent_at = to_db_time_string()
        else:
            last_error = "notify_failed"

    stored_level = previous_level if should_send and last_error else _next_stored_level(previous_level, current_level)
    if should_send and sent_at is not None:
        stored_level = current_level

    await upsert_api_key_alert_state(
        user_id=int(user_key["user_id"]),
        server_id=int(server["id"]),
        api_key_hash=api_key_hash,
        masked_key=masked_key_value,
        last_seen_remain_quota=remain_quota,
        last_seen_balance_dollar=balance_dollar,
        last_alert_threshold=stored_level,
        last_alert_sent_at=sent_at,
        last_error=last_error,
    )


