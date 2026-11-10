"""Pull central source configuration into the legacy shopbot database."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import hmac
from typing import Any
from urllib.parse import urlparse

import aiohttp

from bot.config import settings
from db.database import open_write_transaction
from db.queries.settings import get_setting, get_setting_int, set_setting

logger = logging.getLogger(__name__)

REVISION_KEY = "control_plane_applied_revision"
STATUS_KEY = "control_plane_sync_status"
ETAG_KEY = "control_plane_snapshot_etag"
CHECKSUM_KEY = "control_plane_applied_checksum"
PENDING_ACK_KEY = "control_plane_pending_ack"


def _value(source: dict[str, Any], key: str, default: Any = None) -> Any:
    value = source.get(key)
    return default if value is None else value


def _server_values(source: dict[str, Any], existing: dict[str, Any] | None) -> dict[str, Any]:
    old = existing or {}
    # Commerce settings belong to Shopbot, including for centrally linked sources.
    bot_multiple = _value(old, "quota_multiple", 1.0)
    try:
        bot_multiple = float(bot_multiple)
    except (TypeError, ValueError):
        raise ValueError("Invalid Shopbot quota multiplier") from None
    if not math.isfinite(bot_multiple) or bot_multiple <= 0:
        raise ValueError("Invalid Shopbot quota multiplier")
    return {
        "name": _value(source, "name", old.get("name", "Unnamed source")),
        "base_url": _value(source, "upstream_base_url", old.get("base_url", "")),
        "user_id_header": _value(source, "auth_user_value", old.get("user_id_header", "")),
        "access_token": _value(source, "auth_token", old.get("access_token", "")),
        "price_per_unit": _value(old, "price_per_unit", 0),
        "dollar_per_unit": _value(old, "dollar_per_unit", 1.0),
        "quota_multiple": bot_multiple,
        "quota_per_unit": _value(old, "quota_per_unit", 500000),
        "default_group": _value(old, "default_group", ""),
        "sort_order": int(_value(source, "profile_sort_order", source.get("sort_order", old.get("sort_order", 0))) or 0),
        "api_type": _value(source, "source_type", old.get("api_type", "newapi")),
        "supports_multi_group": _value(old, "supports_multi_group", int(source.get("supports_group_chain") or 0)),
        "manual_groups": _value(old, "manual_groups", ""),
        "auth_type": _value(source, "auth_mode", old.get("auth_type", "header")),
        "auth_user_header": _value(source, "auth_user_header", old.get("auth_user_header", "")) or "",
        "auth_user_value": _value(source, "auth_user_value", old.get("auth_user_value", "")) or "",
        "auth_token": _value(source, "auth_token", old.get("auth_token", "")) or "",
        "auth_cookie": _value(source, "auth_cookie", old.get("auth_cookie", "")) or "",
        "groups_endpoint": _value(source, "groups_path", old.get("groups_endpoint", "")) or "",
        "import_spend_accrual_enabled": _value(old, "import_spend_accrual_enabled", 0),
        "discount_stack_mode": _value(old, "discount_stack_mode", "exclusive"),
        "discount_allowed_stack_types": _value(old, "discount_allowed_stack_types", "cashback"),
        "supports_key_lookup_by_id": int(_value(source, "supports_key_lookup_by_id", old.get("supports_key_lookup_by_id", 0)) or 0),
        "token_key_endpoint_template": _value(source, "token_key_endpoint_template", old.get("token_key_endpoint_template", "/api/token/{id}/key")),
        "control_plane_source_id": str(source["id"]),
        "is_active": old.get("is_active", 0),
    }


def _validate_snapshot_sources(sources: list[Any]) -> None:
    seen: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("Control-plane snapshot contains a non-object source")
        source_id = source.get("id")
        name = str(source.get("name") or "").strip()
        if not isinstance(source_id, str) or not source_id or source_id != source_id.strip() or len(source_id) > 128 or source_id in seen:
            raise ValueError("Control-plane snapshot contains a duplicate or invalid source ID")
        if not name or len(name) > 256:
            raise ValueError(f"Control-plane source {source_id} has an invalid name")
        upstream = str(source.get("upstream_base_url") or "").strip()
        parsed = urlparse(upstream)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"Control-plane source {source_id} has an invalid upstream URL")
        public = str(source.get("public_base_url") or "").strip()
        if public:
            parsed_public = urlparse(public)
            if parsed_public.scheme not in {"http", "https"} or not parsed_public.netloc:
                raise ValueError(f"Control-plane source {source_id} has an invalid public URL")
        for field in ("price_per_unit", "quota_per_unit", "dollar_per_unit", "quota_multiple", "profile_sort_order"):
            value = source.get(field)
            if value is not None:
                try:
                    numeric = float(value)
                except (TypeError, ValueError):
                    raise ValueError(f"Control-plane source {source_id} has an invalid {field}") from None
                if not math.isfinite(numeric):
                    raise ValueError(f"Control-plane source {source_id} has an invalid {field}")
        seen.add(source_id)


async def apply_snapshot(snapshot: dict[str, Any]) -> int:
    if not isinstance(snapshot, dict) or type(snapshot.get("revision")) is not int or snapshot["revision"] < 0:
        raise ValueError("Control-plane snapshot revision is invalid")
    revision = snapshot["revision"]
    sources = snapshot.get("sources")
    if not isinstance(sources, list):
        raise ValueError("Control-plane snapshot sources must be an array")
    checksum = snapshot.get("checksum")
    try:
        expected = hashlib.sha256(json.dumps(
            {"revision": revision, "sources": sources}, ensure_ascii=True,
            sort_keys=True, separators=(",", ":"), default=str,
        ).encode()).hexdigest()
    except (ValueError, TypeError):
        raise ValueError("Control-plane snapshot cannot be checksummed") from None
    if not isinstance(checksum, str) or len(checksum) != 64 or any(c not in "0123456789abcdef" for c in checksum) or not hmac.compare_digest(expected, checksum):
        raise ValueError("Control-plane snapshot checksum is invalid")
    _validate_snapshot_sources(sources)

    db = await open_write_transaction()
    try:
        cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (REVISION_KEY,))
        row = await cursor.fetchone()
        current_revision = int(row["value"]) if row and row["value"] else 0
        cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (CHECKSUM_KEY,))
        checksum_row = await cursor.fetchone()
        current_checksum = checksum_row["value"] if checksum_row else None
        if revision < current_revision:
            await db.rollback()
            return current_revision
        if revision == current_revision and current_checksum:
            if not hmac.compare_digest(current_checksum, checksum):
                raise ValueError("Control-plane checksum changed without a new revision")
            await db.rollback()
            return current_revision

        cursor = await db.execute("SELECT * FROM api_servers")
        existing_rows = [dict(row) for row in await cursor.fetchall()]
        by_source = {str(row["control_plane_source_id"]): row for row in existing_rows if row.get("control_plane_source_id")}
        unlinked = [row for row in existing_rows if not row.get("control_plane_source_id")]
        for source in sources:
            if str(source["id"]) in by_source:
                continue
            source_hosts = {
                urlparse(str(source.get(field) or "")).hostname
                for field in ("upstream_base_url", "public_base_url")
            } - {None}
            source_name = str(source.get("name") or "").strip().casefold()
            for old in unlinked:
                legacy_host = urlparse(str(old.get("base_url") or "")).hostname
                legacy_name = str(old.get("name") or "").strip().casefold()
                if (legacy_host and legacy_host in source_hosts) or (legacy_name and legacy_name == source_name):
                    raise ValueError("Control-plane source may duplicate an unmapped Shopbot server; review mapping first")

        seen: set[str] = set()
        for source in sources:
            source_id = str(source["id"])
            seen.add(source_id)
            existing = by_source.get(source_id)
            values = _server_values(source, existing)
            if existing:
                assignments = ", ".join(f"{key} = ?" for key in values)
                await db.execute(
                    f"UPDATE api_servers SET {assignments}, updated_at = datetime('now', '+7 hours') WHERE id = ?",
                    [*values.values(), existing["id"]],
                )
            else:
                columns = ", ".join(values)
                placeholders = ", ".join("?" for _ in values)
                await db.execute(
                    f"INSERT INTO api_servers ({columns}) VALUES ({placeholders})",
                    list(values.values()),
                )

        for source_id, old in by_source.items():
            if source_id not in seen:
                await db.execute(
                    "UPDATE api_servers SET is_active = 0, updated_at = datetime('now', '+7 hours') WHERE id = ?",
                    (old["id"],),
                )
        pending_ack = json.dumps([revision, checksum], separators=(",", ":"))
        for key, value in ((REVISION_KEY, str(revision)), (CHECKSUM_KEY, checksum), (PENDING_ACK_KEY, pending_ack), (STATUS_KEY, "healthy")):
            await db.execute(
                """INSERT INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now', '+7 hours'))
                   ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
                (key, value),
            )
        await db.commit()
        return revision
    except BaseException:
        await db.rollback()
        raise
    finally:
        await db.close()


async def _ack_pending(client: aiohttp.ClientSession, headers: dict[str, str]) -> None:
    pending = await get_setting(PENDING_ACK_KEY)
    if not pending:
        return
    try:
        revision, checksum = json.loads(pending)
        if type(revision) is not int or revision < 0 or not isinstance(checksum, str) or len(checksum) != 64:
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError("Stored control-plane acknowledgement is invalid") from None
    async with client.post(
        f"{settings.platform_admin_url.rstrip('/')}/api/internal/config/consumers/shopbot/status",
        json={"revision": revision, "status": "healthy", "checksum": checksum},
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=10),
    ) as response:
        response.raise_for_status()
    db = await open_write_transaction()
    try:
        await db.execute("DELETE FROM settings WHERE key = ? AND value = ?", (PENDING_ACK_KEY, pending))
        await db.commit()
    except BaseException:
        await db.rollback()
        raise
    finally:
        await db.close()


async def sync_once(session: aiohttp.ClientSession | None = None) -> int | None:
    if not settings.platform_admin_url or not settings.portal_internal_token:
        return None
    url = f"{settings.platform_admin_url.rstrip('/')}/api/internal/config/shopbot"
    own_session = session is None
    client = session or aiohttp.ClientSession()
    snapshot: dict[str, Any] | None = None
    try:
        headers = {"X-Control-Plane-Token": settings.portal_internal_token}
        etag = await get_setting(ETAG_KEY)
        applied_checksum = await get_setting(CHECKSUM_KEY)
        if applied_checksum and etag and etag.removeprefix("W/") == f'"{applied_checksum}"':
            headers["If-None-Match"] = etag
        async with client.get(
            url,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=20),
        ) as response:
            if response.status == 304:
                if "If-None-Match" not in headers:
                    raise ValueError("Control-plane returned 304 without a verified local snapshot")
                await _ack_pending(client, headers)
                await set_setting(STATUS_KEY, "healthy")
                return await get_setting_int(REVISION_KEY, 0)
            response.raise_for_status()
            snapshot = await response.json()
            response_etag = response.headers.get("ETag", "")
        if response_etag and (not isinstance(snapshot, dict) or response_etag.removeprefix("W/") != f'"{snapshot.get("checksum", "")}"'):
            raise ValueError("Control-plane ETag does not match the snapshot checksum")
        revision = await apply_snapshot(snapshot)
        if revision != int(snapshot.get("revision") or 0):
            raise ValueError("Control-plane snapshot revision is older than applied configuration")
        if response_etag:
            await set_setting(ETAG_KEY, response_etag)
        await _ack_pending(client, {"X-Control-Plane-Token": settings.portal_internal_token})
        return revision
    except Exception as exc:
        await set_setting(STATUS_KEY, "degraded")
        logger.warning("Control-plane sync degraded (%s)", type(exc).__name__)
        if isinstance(snapshot, dict):
            try:
                async with client.post(
                    f"{settings.platform_admin_url.rstrip('/')}/api/internal/config/consumers/shopbot/status",
                    json={"revision": int(snapshot.get("revision") or 0), "status": "degraded", "error": type(exc).__name__},
                    headers={"X-Control-Plane-Token": settings.portal_internal_token},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    response.raise_for_status()
            except Exception:
                pass
        return None
    finally:
        if own_session:
            await client.close()


async def start_control_plane_sync() -> None:
    """Poll central configuration without blocking bot traffic."""
    while True:
        try:
            await sync_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Control-plane sync loop failed")
        await asyncio.sleep(max(15, settings.control_plane_sync_interval_seconds))
