"""Server CRUD and sync-log queries."""
from __future__ import annotations

from typing import Any

from db.database import get_db


def _row_to_dict(row) -> dict | None:
    if row is None:
        return None
    return dict(row)


async def get_all_servers() -> list[dict]:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM servers ORDER BY sort_order, id")
    return [_row_to_dict(r) for r in await cursor.fetchall()]


async def get_enabled_servers() -> list[dict]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM servers WHERE enabled = 1 ORDER BY sort_order, name COLLATE NOCASE, id"
    )
    return [_row_to_dict(r) for r in await cursor.fetchall()]


def _public_flag_column(capability: str) -> str:
    flags = {
        "pricing": "public_pricing_enabled",
        "balance": "public_balance_enabled",
        "keys": "public_keys_enabled",
        "logs": "public_logs_enabled",
    }
    try:
        return flags[capability]
    except KeyError as exc:
        raise ValueError(f"Unsupported public capability: {capability}") from exc


async def get_public_servers(capability: str) -> list[dict]:
    db = await get_db()
    flag = _public_flag_column(capability)
    cursor = await db.execute(
        f"SELECT * FROM servers WHERE enabled = 1 AND {flag} = 1 ORDER BY sort_order, name COLLATE NOCASE, id"
    )
    return [_row_to_dict(r) for r in await cursor.fetchall()]


async def get_public_server(server_id: str, capability: str) -> dict | None:
    db = await get_db()
    flag = _public_flag_column(capability)
    cursor = await db.execute(
        f"SELECT * FROM servers WHERE id = ? AND enabled = 1 AND {flag} = 1",
        (server_id,),
    )
    return _row_to_dict(await cursor.fetchone())


async def get_server(server_id: str) -> dict | None:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM servers WHERE id = ?", (server_id,))
    row = await cursor.fetchone()
    return _row_to_dict(row)


async def upsert_server(server_id: str, **fields: Any) -> None:
    db = await get_db()
    existing = await get_server(server_id)

    if existing is None:
        cols = ["id"] + list(fields.keys())
        placeholders = ", ".join(["?"] * len(cols))
        col_names = ", ".join(cols)
        values = [server_id] + list(fields.values())
        await db.execute(
            f"INSERT INTO servers ({col_names}) VALUES ({placeholders})", values
        )
    else:
        if not fields:
            return
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [server_id]
        await db.execute(
            f"UPDATE servers SET {set_clause}, updated_at = datetime('now') WHERE id = ?",
            values,
        )
    await db.commit()


async def delete_server(server_id: str) -> bool:
    db = await get_db()
    cursor = await db.execute("DELETE FROM servers WHERE id = ?", (server_id,))
    await db.commit()
    return cursor.rowcount > 0


async def update_server_cache(
    server_id: str,
    *,
    pricing_cache: str | None = None,
    groups_cache: str | None = None,
) -> None:
    db = await get_db()
    updates = ["updated_at = datetime('now')"]
    values: list = []
    if pricing_cache is not None:
        updates.append("pricing_cache = ?")
        updates.append("pricing_fetched_at = datetime('now')")
        values.append(pricing_cache)
    if groups_cache is not None:
        updates.append("groups_cache = ?")
        updates.append("groups_fetched_at = datetime('now')")
        values.append(groups_cache)
    values.append(server_id)
    await db.execute(
        f"UPDATE servers SET {', '.join(updates)} WHERE id = ?", values
    )
    await db.commit()


async def create_sync_log(
    server_id: str,
    *,
    trigger: str = "manual",
    status: str,
    model_count: int = 0,
    group_count: int = 0,
    duration_ms: int = 0,
    error_message: str | None = None,
) -> None:
    db = await get_db()
    await db.execute(
        """
        INSERT INTO sync_log (
            server_id, trigger, status, model_count, group_count, duration_ms, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (server_id, trigger, status, model_count, group_count, duration_ms, error_message),
    )
    await db.commit()


async def get_latest_sync_map() -> dict[str, dict]:
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT id, server_id, trigger, status, model_count, group_count, duration_ms,
               error_message, created_at
        FROM sync_log
        ORDER BY created_at DESC, id DESC
        """
    )
    rows = await cursor.fetchall()
    latest: dict[str, dict] = {}
    for row in rows:
        item = _row_to_dict(row)
        if item and item["server_id"] not in latest:
            latest[item["server_id"]] = item
    return latest


async def get_recent_sync_logs(limit: int = 10) -> list[dict]:
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT id, server_id, trigger, status, model_count, group_count, duration_ms,
               error_message, created_at
        FROM sync_log
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    )
    return [_row_to_dict(row) for row in await cursor.fetchall()]
