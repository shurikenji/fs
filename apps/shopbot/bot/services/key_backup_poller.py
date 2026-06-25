"""Background backup of upstream token inventory for all active API servers."""
from __future__ import annotations

import asyncio
import logging
import math
from typing import Any

import aiohttp

from bot.services.api_clients import get_api_client
from bot.utils.formatting import mask_api_key
from db.queries.key_backup import (
    bulk_insert_backup_items,
    cleanup_old_snapshots,
    create_snapshot,
)
from db.queries.logs import add_log
from db.queries.servers import get_active_servers, get_server_by_id
from db.queries.settings import get_setting, get_setting_int

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_MINUTES = 10
DEFAULT_RETENTION_DAYS = 7
PAGE_SIZE = 100
PAGE_PAUSE_SECONDS = 0.2
REQUEST_TIMEOUT_SECONDS = 30

_backup_lock = asyncio.Lock()


def _is_truthy(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _to_int(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _quota_to_dollar_value(quota: int, multiple: float) -> float:
    divisor = 500000 * (multiple if multiple > 0 else 1.0)
    return max(0.0, float(quota) / float(divisor))


def _extract_items_payload(response_payload: dict[str, Any]) -> dict[str, Any]:
    data = response_payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("Token list response does not contain a data object")
    items = data.get("items", [])
    if not isinstance(items, list):
        raise ValueError("Token list response data.items is not a list")
    return data


async def _fetch_page(
    session: aiohttp.ClientSession,
    *,
    base_url: str,
    headers: dict[str, str],
    page: int,
    page_size: int,
) -> dict[str, Any]:
    url = f"{base_url}/api/token/"
    async with session.get(
        url,
        params={"p": page, "page_size": page_size},
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS),
    ) as response:
        response.raise_for_status()
        payload = await response.json()
    if not isinstance(payload, dict):
        raise ValueError("Token list response is not a JSON object")
    if payload.get("success") is False:
        raise ValueError(str(payload.get("message") or "Token list request failed"))
    return _extract_items_payload(payload)


def _normalize_key_fields(raw_key: object) -> tuple[str | None, str | None]:
    if raw_key is None:
        return None, None

    key = str(raw_key).strip()
    if not key:
        return None, None
    if "*" in key:
        return None, key

    normalized = key if key.startswith("sk-") else f"sk-{key}"
    return key, mask_api_key(normalized)


def _normalize_token_item(token: dict[str, Any], *, quota_multiple: float) -> dict[str, Any]:
    remain_quota = _to_int(token.get("remain_quota", token.get("remainQuota")))
    used_quota = _to_int(token.get("used_quota", token.get("usedQuota")))
    total_quota = _to_int(token.get("total_quota", token.get("totalQuota")), remain_quota + used_quota)
    key_value, key_masked = _normalize_key_fields(token.get("key"))

    return {
        "token_id": token.get("id") or token.get("token_id") or token.get("tokenId"),
        "token_name": token.get("name") or token.get("token_name"),
        "key_value": key_value,
        "key_masked": key_masked,
        "status": _to_int(token.get("status"), 1),
        "remain_quota": remain_quota,
        "used_quota": used_quota,
        "total_quota": total_quota,
        "balance_dollar": _quota_to_dollar_value(remain_quota, quota_multiple),
        "group_name": token.get("group") or token.get("group_name") or token.get("groupName"),
        "unlimited_quota": bool(token.get("unlimited_quota", token.get("unlimitedQuota", False))),
        "expired_time": _to_int(token.get("expired_time", token.get("expiredTime")), -1),
        "created_time": token.get("created_time") or token.get("createdTime"),
        "accessed_time": token.get("accessed_time") or token.get("accessedTime"),
        "raw_json": token,
    }


async def is_enabled() -> bool:
    return _is_truthy(await get_setting("key_backup_enabled", "true"), default=True)


async def _fetch_all_tokens(server: dict) -> list[dict[str, Any]]:
    client = get_api_client(server)
    headers = client.get_headers(server)
    base_url = str(server["base_url"]).rstrip("/")
    tokens: list[dict[str, Any]] = []
    page = 1
    total: int | None = None

    async with aiohttp.ClientSession() as session:
        while True:
            data = await _fetch_page(
                session,
                base_url=base_url,
                headers=headers,
                page=page,
                page_size=PAGE_SIZE,
            )
            raw_items = [item for item in data.get("items", []) if isinstance(item, dict)]
            tokens.extend(raw_items)

            if total is None:
                total = _to_int(data.get("total"), len(raw_items))
            total_pages = max(1, math.ceil(total / PAGE_SIZE)) if total is not None else 1
            if page >= total_pages or not raw_items:
                break

            page += 1
            await asyncio.sleep(PAGE_PAUSE_SECONDS)

    return tokens


async def _backup_server_keys(server: dict) -> dict[str, Any]:
    server_id = int(server["id"])
    try:
        raw_tokens = await _fetch_all_tokens(server)
        quota_multiple = float(server.get("quota_multiple") or 1.0)
        normalized_items = [
            _normalize_token_item(token, quota_multiple=quota_multiple)
            for token in raw_tokens
        ]
        total_balance = sum(float(item["balance_dollar"]) for item in normalized_items)
        snapshot_id = await create_snapshot(
            server_id=server_id,
            total_keys=len(normalized_items),
            total_balance=total_balance,
            status="success",
        )
        await bulk_insert_backup_items(snapshot_id, server_id, normalized_items)
        logger.info(
            "Backed up %d keys from %s",
            len(normalized_items),
            server.get("name", server_id),
        )
        return {
            "server_id": server_id,
            "server_name": server.get("name"),
            "status": "success",
            "total_keys": len(normalized_items),
            "total_balance": total_balance,
            "snapshot_id": snapshot_id,
        }
    except Exception as exc:
        logger.error("Key backup failed for %s: %s", server.get("name", server_id), exc, exc_info=True)
        snapshot_id = await create_snapshot(
            server_id=server_id,
            total_keys=0,
            total_balance=0.0,
            status="error",
            error_message=str(exc),
        )
        await add_log(
            f"Key backup failed for {server.get('name', server_id)}: {exc}",
            level="error",
            module="key_backup",
        )
        return {
            "server_id": server_id,
            "server_name": server.get("name"),
            "status": "error",
            "error_message": str(exc),
            "snapshot_id": snapshot_id,
        }


async def _backup_cycle(servers: list[dict] | None = None) -> list[dict[str, Any]]:
    async with _backup_lock:
        selected_servers = servers if servers is not None else await get_active_servers()
        results = []
        for server in selected_servers:
            results.append(await _backup_server_keys(server))

        retention_days = await get_setting_int("key_backup_retention_days", DEFAULT_RETENTION_DAYS)
        await cleanup_old_snapshots(retention_days)
        return results


async def backup_all_servers_now() -> list[dict[str, Any]]:
    return await _backup_cycle(await get_active_servers())


async def backup_server_now(server_id: int) -> dict[str, Any] | None:
    server = await get_server_by_id(server_id)
    if not server:
        return None
    results = await _backup_cycle([server])
    return results[0] if results else None


async def start_key_backup_poller() -> None:
    """Run the key backup poller loop forever."""
    logger.info("Key backup poller started")
    await add_log("Key backup poller started", module="key_backup")

    while True:
        try:
            if await is_enabled():
                await _backup_cycle()
            interval_minutes = max(
                1,
                await get_setting_int("key_backup_interval_min", DEFAULT_INTERVAL_MINUTES),
            )
            await asyncio.sleep(interval_minutes * 60)
        except asyncio.CancelledError:
            logger.info("Key backup poller cancelled")
            break
        except Exception as exc:
            logger.error("Key backup poller error: %s", exc, exc_info=True)
            await add_log(f"Key backup poller error: {exc}", level="error", module="key_backup")
            await asyncio.sleep(60)
