"""Query helpers for platform-control."""
from __future__ import annotations

import json
from typing import Any

from db.database import get_db


async def get_service_sources(*, enabled_only: bool) -> list[dict[str, Any]]:
    db = await get_db()
    query = "SELECT * FROM service_sources"
    if enabled_only:
        query += " WHERE enabled = 1"
    query += " ORDER BY sort_order ASC, name COLLATE NOCASE, id ASC"
    cursor = await db.execute(query)
    return [dict(row) for row in await cursor.fetchall()]


async def get_service_source(source_id: str) -> dict[str, Any] | None:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM service_sources WHERE id = ?", (source_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def upsert_service_source(source_id: str, **fields: Any) -> None:
    db = await get_db()
    cursor = await db.execute("SELECT id FROM service_sources WHERE id = ?", (source_id,))
    exists = await cursor.fetchone()
    if exists:
        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = list(fields.values()) + [source_id]
        await db.execute(
            f"UPDATE service_sources SET {assignments}, updated_at = datetime('now') WHERE id = ?",
            values,
        )
    else:
        columns = ["id"] + list(fields.keys())
        placeholders = ", ".join("?" for _ in columns)
        values = [source_id] + list(fields.values())
        await db.execute(
            f"INSERT INTO service_sources ({', '.join(columns)}) VALUES ({placeholders})",
            values,
        )
    await db.commit()


async def delete_service_source(source_id: str) -> None:
    db = await get_db()
    await db.execute("DELETE FROM service_sources WHERE id = ?", (source_id,))
    await db.commit()


async def get_proxy_endpoints(*, active_only: bool) -> list[dict[str, Any]]:
    db = await get_db()
    query = "SELECT * FROM proxy_endpoints"
    if active_only:
        query += " WHERE status = 'active'"
    query += " ORDER BY port ASC"
    cursor = await db.execute(query)
    return [dict(row) for row in await cursor.fetchall()]


async def upsert_proxy_endpoint(endpoint_id: str, **fields: Any) -> None:
    db = await get_db()
    cursor = await db.execute("SELECT id FROM proxy_endpoints WHERE id = ?", (endpoint_id,))
    exists = await cursor.fetchone()
    if exists:
        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = list(fields.values()) + [endpoint_id]
        await db.execute(
            f"UPDATE proxy_endpoints SET {assignments}, updated_at = datetime('now') WHERE id = ?",
            values,
        )
    else:
        columns = ["id"] + list(fields.keys())
        placeholders = ", ".join("?" for _ in columns)
        values = [endpoint_id] + list(fields.values())
        await db.execute(
            f"INSERT INTO proxy_endpoints ({', '.join(columns)}) VALUES ({placeholders})",
            values,
        )
    await db.commit()


async def delete_proxy_endpoint(endpoint_id: str) -> None:
    db = await get_db()
    await db.execute("DELETE FROM proxy_endpoints WHERE id = ?", (endpoint_id,))
    await db.commit()


async def get_portal_modules(*, public_only: bool) -> list[dict[str, Any]]:
    db = await get_db()
    query = "SELECT * FROM portal_modules"
    if public_only:
        query += " WHERE enabled = 1 AND is_public = 1"
    query += " ORDER BY sort_order ASC, id ASC"
    cursor = await db.execute(query)
    return [dict(row) for row in await cursor.fetchall()]


async def upsert_portal_module(module_id: str, **fields: Any) -> None:
    db = await get_db()
    cursor = await db.execute("SELECT id FROM portal_modules WHERE id = ?", (module_id,))
    exists = await cursor.fetchone()
    if exists:
        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = list(fields.values()) + [module_id]
        await db.execute(
            f"UPDATE portal_modules SET {assignments}, updated_at = datetime('now') WHERE id = ?",
            values,
        )
    else:
        columns = ["id"] + list(fields.keys())
        placeholders = ", ".join("?" for _ in columns)
        values = [module_id] + list(fields.values())
        await db.execute(
            f"INSERT INTO portal_modules ({', '.join(columns)}) VALUES ({placeholders})",
            values,
        )
    await db.commit()


async def delete_portal_module(module_id: str) -> None:
    db = await get_db()
    await db.execute("DELETE FROM portal_modules WHERE id = ?", (module_id,))
    await db.commit()


async def get_deploy_jobs(*, limit: int) -> list[dict[str, Any]]:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM deploy_jobs ORDER BY id DESC LIMIT ?", (limit,))
    return [dict(row) for row in await cursor.fetchall()]


async def create_deploy_job(job_type: str, status: str, target_ref: str, request_payload: dict[str, Any]) -> int:
    db = await get_db()
    cursor = await db.execute(
        """
        INSERT INTO deploy_jobs (job_type, status, target_ref, request_payload)
        VALUES (?, ?, ?, ?)
        """,
        (job_type, status, target_ref, json.dumps(request_payload, ensure_ascii=True)),
    )
    await db.commit()
    return int(cursor.lastrowid)


async def mark_deploy_job_finished(
    job_id: int,
    status: str,
    *,
    response_payload: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> None:
    db = await get_db()
    await db.execute(
        """
        UPDATE deploy_jobs
        SET status = ?, response_payload = ?, error_message = ?, updated_at = datetime('now')
        WHERE id = ?
        """,
        (
            status,
            json.dumps(response_payload, ensure_ascii=True) if response_payload is not None else None,
            error_message,
            job_id,
        ),
    )
    await db.commit()


async def get_public_modules() -> list[dict[str, Any]]:
    return await get_portal_modules(public_only=True)


async def get_public_proxy_status() -> list[dict[str, Any]]:
    rows = await get_proxy_endpoints(active_only=False)
    return [{"id": row["id"], "name": row["name"], "domain": row["domain"], "status": row["status"]} for row in rows]


async def get_public_balance_sources() -> list[dict[str, Any]]:
    rows = await get_service_sources(enabled_only=True)
    result: list[dict[str, Any]] = []
    for row in rows:
        if not int(row.get("public_balance_enabled") or 0):
            continue
        result.append(
            {
                "id": row["id"],
                "name": row["name"],
                "base_url": row.get("public_base_url") or row["upstream_base_url"],
            }
        )
    return result


async def get_internal_balance_sources() -> list[dict[str, Any]]:
    rows = await get_service_sources(enabled_only=True)
    result: list[dict[str, Any]] = []
    for row in rows:
        if not int(row.get("public_balance_enabled") or 0):
            continue
        result.append(
            {
                "id": row["id"],
                "name": row["name"],
                "base_url": row.get("public_base_url") or row["upstream_base_url"],
                "rate": float(row.get("balance_rate") or 1.0),
            }
        )
    return result


def _public_source_flag(capability: str) -> str:
    flags = {
        "pricing": "public_pricing_enabled",
        "balance": "public_balance_enabled",
        "keys": "public_keys_enabled",
        "logs": "public_logs_enabled",
    }
    try:
        return flags[capability]
    except KeyError as exc:
        raise ValueError(f"Unsupported public source capability: {capability}") from exc


async def get_public_service_sources(capability: str) -> list[dict[str, Any]]:
    flag = _public_source_flag(capability)
    rows = await get_service_sources(enabled_only=True)
    return [row for row in rows if int(row.get(flag) or 0)]


# ── Activity logs ──────────────────────────────────────────────────────────────

async def create_activity_log(action: str, details: str = "", ip_address: str = "") -> None:
    db = await get_db()
    await db.execute(
        "INSERT INTO activity_logs (action, details, ip_address) VALUES (?, ?, ?)",
        (action, details, ip_address),
    )
    await db.commit()


async def get_activity_logs(*, limit: int = 50) -> list[dict[str, Any]]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM activity_logs ORDER BY id DESC LIMIT ?", (limit,)
    )
    return [dict(row) for row in await cursor.fetchall()]


# ── Proxy helpers ──────────────────────────────────────────────────────────────

async def get_proxy_stats() -> dict[str, int]:
    rows = await get_proxy_endpoints(active_only=False)
    total = len(rows)
    active = sum(1 for r in rows if r.get("status") == "active")
    return {"total": total, "active": active, "inactive": total - active}


async def toggle_proxy_status(endpoint_id: str) -> str:
    db = await get_db()
    cursor = await db.execute(
        "SELECT status FROM proxy_endpoints WHERE id = ?", (endpoint_id,)
    )
    row = await cursor.fetchone()
    if not row:
        raise ValueError(f"Proxy endpoint {endpoint_id} not found")
    new_status = "inactive" if row["status"] == "active" else "active"
    await db.execute(
        "UPDATE proxy_endpoints SET status = ?, updated_at = datetime('now') WHERE id = ?",
        (new_status, endpoint_id),
    )
    await db.commit()
    return new_status


async def get_source_stats() -> dict[str, int]:
    rows = await get_service_sources(enabled_only=False)
    total = len(rows)
    enabled = sum(1 for r in rows if int(r.get("enabled") or 0))
    return {"total": total, "enabled": enabled}


async def get_module_stats() -> dict[str, int]:
    rows = await get_portal_modules(public_only=False)
    total = len(rows)
    public = sum(1 for r in rows if int(r.get("is_public") or 0))
    return {"total": total, "public": public}


async def get_pricing_runtime_settings(defaults: dict[str, str] | None = None) -> dict[str, str]:
    db = await get_db()
    cursor = await db.execute("SELECT key, value FROM pricing_runtime_settings")
    rows = await cursor.fetchall()
    data = dict(defaults or {})
    for row in rows:
        data[str(row["key"])] = str(row["value"] or "")
    return data


async def set_pricing_runtime_settings(values: dict[str, Any]) -> None:
    db = await get_db()
    for key, value in values.items():
        await db.execute(
            """
            INSERT INTO pricing_runtime_settings (key, value, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, str(value or "")),
        )
    await db.commit()


async def create_pricing_sync_run(
    source_id: str,
    *,
    trigger: str,
    status: str,
    model_count: int = 0,
    group_count: int = 0,
    translated_count: int = 0,
    duration_ms: int = 0,
    error_message: str | None = None,
) -> int:
    db = await get_db()
    cursor = await db.execute(
        """
        INSERT INTO pricing_sync_runs (
            source_id, trigger, status, model_count, group_count, translated_count, duration_ms, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_id,
            trigger,
            status,
            model_count,
            group_count,
            translated_count,
            duration_ms,
            error_message,
        ),
    )
    await db.commit()
    return int(cursor.lastrowid)


async def get_pricing_sync_runs(
    *,
    source_id: str | None = None,
    status: str | None = None,
    trigger: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    db = await get_db()
    clauses: list[str] = []
    params: list[Any] = []
    if source_id:
        clauses.append("source_id = ?")
        params.append(source_id)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if trigger:
        clauses.append("trigger = ?")
        params.append(trigger)
    query = "SELECT * FROM pricing_sync_runs"
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    cursor = await db.execute(query, params)
    return [dict(row) for row in await cursor.fetchall()]


async def get_latest_pricing_sync_map() -> dict[str, dict[str, Any]]:
    rows = await get_pricing_sync_runs(limit=500)
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        source_id = str(row.get("source_id") or "").strip()
        if source_id and source_id not in latest:
            latest[source_id] = row
    return latest
