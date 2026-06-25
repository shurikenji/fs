"""Queries and matching helpers for upstream key backup snapshots."""
from __future__ import annotations

import json
from typing import Any

from db.database import get_db
from db.queries._helpers import execute_commit, fetch_all_dicts, fetch_one_dict


def _to_int(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _clean_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _bare_key(value: str) -> str:
    key = value.strip()
    return key[3:] if key.startswith("sk-") else key


def match_masked_key(full_key: str | None, masked_key: str | None) -> bool:
    """Match full shopbot keys against full or masked upstream key values."""
    if not full_key or not masked_key:
        return False

    bare = _bare_key(full_key)
    masked = _bare_key(masked_key)
    if "*" not in masked:
        return bare == masked or full_key.strip() == masked_key.strip()

    star_start = masked.find("*")
    star_end = masked.rfind("*")
    prefix = masked[:star_start]
    suffix = masked[star_end + 1 :]
    return bool(prefix or suffix) and bare.startswith(prefix) and bare.endswith(suffix)


def _item_matches_user_key(item: dict, user_key: dict) -> bool:
    token_id = item.get("token_id")
    user_token_id = user_key.get("api_token_id")
    if token_id is not None and user_token_id is not None:
        if _to_int(token_id, -1) == _to_int(user_token_id, -2):
            return True

    token_name = _clean_text(item.get("token_name"))
    user_token_name = _clean_text(user_key.get("label"))
    if token_name and user_token_name and token_name == user_token_name:
        return True

    api_key = _clean_text(user_key.get("api_key"))
    return match_masked_key(api_key, _clean_text(item.get("key_value")) or _clean_text(item.get("key_masked")))


def _normalize_item_for_insert(item: dict[str, Any]) -> tuple[object, ...]:
    raw_json = item.get("raw_json")
    if raw_json is None:
        raw_json = item

    remain_quota = _to_int(item.get("remain_quota"))
    used_quota = _to_int(item.get("used_quota"))
    total_quota = _to_int(item.get("total_quota"), remain_quota + used_quota)

    return (
        item.get("snapshot_id"),
        item.get("server_id"),
        item.get("token_id"),
        _clean_text(item.get("token_name")),
        _clean_text(item.get("key_value")),
        _clean_text(item.get("key_masked")),
        _to_int(item.get("status"), 1),
        remain_quota,
        used_quota,
        total_quota,
        _to_float(item.get("balance_dollar")),
        _clean_text(item.get("group_name")),
        1 if item.get("unlimited_quota") else 0,
        _to_int(item.get("expired_time"), -1),
        item.get("created_time"),
        item.get("accessed_time"),
        json.dumps(raw_json, ensure_ascii=True, default=str),
    )


async def create_snapshot(
    server_id: int,
    total_keys: int = 0,
    total_balance: float = 0.0,
    status: str = "success",
    error_message: str | None = None,
) -> int:
    cursor = await execute_commit(
        """INSERT INTO key_backup_snapshots
           (server_id, total_keys, total_balance, status, error_message)
           VALUES (?, ?, ?, ?, ?)""",
        (server_id, total_keys, total_balance, status, error_message),
    )
    return int(cursor.lastrowid)


async def bulk_insert_backup_items(snapshot_id: int, server_id: int, items: list[dict]) -> None:
    if not items:
        return

    rows = [
        _normalize_item_for_insert({**item, "snapshot_id": snapshot_id, "server_id": server_id})
        for item in items
    ]
    db = await get_db()
    await db.executemany(
        """INSERT INTO key_backup_items
           (snapshot_id, server_id, token_id, token_name, key_value, key_masked, status,
            remain_quota, used_quota, total_quota, balance_dollar, group_name, unlimited_quota,
            expired_time, created_time, accessed_time, raw_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    await db.commit()


async def get_latest_snapshot_per_server() -> list[dict]:
    return await fetch_all_dicts(
        """SELECT kbs.*, s.name AS server_name, s.base_url, s.is_active
           FROM key_backup_snapshots kbs
           JOIN api_servers s ON s.id = kbs.server_id
           WHERE NOT EXISTS (
               SELECT 1
               FROM key_backup_snapshots newer
               WHERE newer.server_id = kbs.server_id
                 AND (
                    newer.fetched_at > kbs.fetched_at
                    OR (newer.fetched_at = kbs.fetched_at AND newer.id > kbs.id)
                 )
           )
           ORDER BY s.sort_order ASC, s.id ASC"""
    )


async def _get_user_keys_for_server(server_id: int) -> list[dict]:
    return await fetch_all_dicts(
        """SELECT id, user_id, server_id, api_key, api_token_id, label
           FROM user_keys
           WHERE server_id = ? AND is_active = 1""",
        (server_id,),
    )


async def get_latest_items_by_server(server_id: int) -> list[dict]:
    items = await fetch_all_dicts(
        """SELECT kbi.*
           FROM key_backup_items kbi
           JOIN key_backup_snapshots kbs ON kbs.id = kbi.snapshot_id
           WHERE kbi.server_id = ?
             AND kbs.id = (
                SELECT id
                FROM key_backup_snapshots
                WHERE server_id = ?
                ORDER BY fetched_at DESC, id DESC
                LIMIT 1
             )
           ORDER BY kbi.balance_dollar DESC, kbi.id ASC""",
        (server_id, server_id),
    )
    user_keys = await _get_user_keys_for_server(server_id)
    for item in items:
        matched = next((user_key for user_key in user_keys if _item_matches_user_key(item, user_key)), None)
        item["shopbot_match"] = matched is not None
        item["shopbot_user_id"] = matched.get("user_id") if matched else None
        item["shopbot_user_key_id"] = matched.get("id") if matched else None
    return items


async def get_backup_history(server_id: int, limit: int = 20) -> list[dict]:
    return await fetch_all_dicts(
        """SELECT *
           FROM key_backup_snapshots
           WHERE server_id = ?
           ORDER BY fetched_at DESC, id DESC
           LIMIT ?""",
        (server_id, max(1, int(limit))),
    )


async def cleanup_old_snapshots(retention_days: int) -> None:
    days = max(1, int(retention_days))
    await execute_commit(
        """DELETE FROM key_backup_snapshots
           WHERE fetched_at < datetime('now', '+7 hours', ?)""",
        (f"-{days} days",),
    )


async def find_backup_item_for_user_key(
    server_id: int,
    token_id: int | None,
    token_name: str | None,
    full_key: str | None,
) -> dict | None:
    latest_snapshot = await fetch_one_dict(
        """SELECT id
           FROM key_backup_snapshots
           WHERE server_id = ? AND status = 'success'
           ORDER BY fetched_at DESC, id DESC
           LIMIT 1""",
        (server_id,),
    )
    if not latest_snapshot:
        return None

    snapshot_id = int(latest_snapshot["id"])
    if token_id is not None:
        item = await fetch_one_dict(
            """SELECT *
               FROM key_backup_items
               WHERE snapshot_id = ? AND server_id = ? AND token_id = ?
               LIMIT 1""",
            (snapshot_id, server_id, token_id),
        )
        if item:
            return item

    cleaned_name = _clean_text(token_name)
    if cleaned_name:
        item = await fetch_one_dict(
            """SELECT *
               FROM key_backup_items
               WHERE snapshot_id = ? AND server_id = ? AND token_name = ?
               LIMIT 1""",
            (snapshot_id, server_id, cleaned_name),
        )
        if item:
            return item

    if not full_key:
        return None

    candidates = await fetch_all_dicts(
        """SELECT *
           FROM key_backup_items
           WHERE snapshot_id = ? AND server_id = ?
             AND COALESCE(key_masked, key_value, '') != ''""",
        (snapshot_id, server_id),
    )
    for item in candidates:
        key_value = _clean_text(item.get("key_value")) or _clean_text(item.get("key_masked"))
        if match_masked_key(full_key, key_value):
            return item

    return None
