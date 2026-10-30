"""Pull central source configuration into the legacy shopbot database."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlparse

import aiohttp

from bot.config import settings
from db.database import get_db
from db.queries.settings import get_setting, get_setting_int, set_setting
from db.queries.servers import get_all_servers

logger = logging.getLogger(__name__)

REVISION_KEY = "control_plane_applied_revision"
STATUS_KEY = "control_plane_sync_status"
ETAG_KEY = "control_plane_snapshot_etag"


def _value(source: dict[str, Any], key: str, default: Any = None) -> Any:
    value = source.get(key)
    return default if value is None else value


def _server_values(source: dict[str, Any], existing: dict[str, Any] | None) -> dict[str, Any]:
    old = existing or {}
    profile = source
    return {
        "name": _value(source, "name", old.get("name", "Unnamed source")),
        "base_url": _value(source, "public_base_url") or _value(source, "upstream_base_url", old.get("base_url", "")),
        "user_id_header": _value(source, "auth_user_value", old.get("user_id_header", "")),
        "access_token": _value(source, "auth_token", old.get("access_token", "")),
        "price_per_unit": int(_value(profile, "price_per_unit", old.get("price_per_unit", 0)) or 0),
        "dollar_per_unit": float(_value(profile, "dollar_per_unit", old.get("dollar_per_unit", 10.0)) or 10.0),
        "quota_multiple": float(_value(source, "quota_multiple", old.get("quota_multiple", 1.0)) or 1.0),
        "quota_per_unit": int(_value(profile, "quota_per_unit", old.get("quota_per_unit", 0)) or 0),
        "default_group": _value(profile, "default_group", old.get("default_group", "")) or "",
        "sort_order": int(_value(profile, "profile_sort_order", source.get("sort_order", old.get("sort_order", 0))) or 0),
        "api_type": _value(source, "source_type", old.get("api_type", "newapi")),
        "supports_multi_group": int(_value(source, "supports_group_chain", old.get("supports_multi_group", 0)) or 0),
        "manual_groups": _value(source, "manual_groups", old.get("manual_groups", "")) or "",
        "auth_type": _value(source, "auth_mode", old.get("auth_type", "header")),
        "auth_user_header": _value(source, "auth_user_header", old.get("auth_user_header", "")) or "",
        "auth_user_value": _value(source, "auth_user_value", old.get("auth_user_value", "")) or "",
        "auth_token": _value(source, "auth_token", old.get("auth_token", "")) or "",
        "auth_cookie": _value(source, "auth_cookie", old.get("auth_cookie", "")) or "",
        "groups_endpoint": _value(source, "groups_path", old.get("groups_endpoint", "")) or "",
        "import_spend_accrual_enabled": int(_value(profile, "import_spend_accrual_enabled", old.get("import_spend_accrual_enabled", 0)) or 0),
        "discount_stack_mode": _value(profile, "discount_stack_mode", old.get("discount_stack_mode", "exclusive")),
        "discount_allowed_stack_types": _value(profile, "discount_allowed_stack_types", old.get("discount_allowed_stack_types", "cashback")),
        "supports_key_lookup_by_id": int(_value(profile, "supports_key_lookup_by_id", old.get("supports_key_lookup_by_id", 0)) or 0),
        "token_key_endpoint_template": _value(profile, "token_key_endpoint_template", old.get("token_key_endpoint_template", "/api/token/{id}/key")),
        "control_plane_source_id": str(source["id"]),
        "is_active": 1,
    }


def _validate_snapshot_sources(sources: list[Any]) -> None:
    seen: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("Control-plane snapshot contains a non-object source")
        source_id = str(source.get("id") or "").strip()
        name = str(source.get("name") or "").strip()
        if not source_id or len(source_id) > 128 or source_id in seen:
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
                    float(value)
                except (TypeError, ValueError):
                    raise ValueError(f"Control-plane source {source_id} has an invalid {field}") from None
        seen.add(source_id)


async def apply_snapshot(snapshot: dict[str, Any]) -> int:
    revision = int(snapshot.get("revision") or 0)
    current_revision = await get_setting_int(REVISION_KEY, 0)
    if revision <= current_revision:
        return current_revision

    sources = snapshot.get("sources")
    if not isinstance(sources, list):
        raise ValueError("Control-plane snapshot sources must be an array")
    _validate_snapshot_sources(sources)

    existing_rows = await get_all_servers()
    by_source = {str(row.get("control_plane_source_id")): row for row in existing_rows if row.get("control_plane_source_id")}
    db = await get_db()
    await db.execute("BEGIN")
    try:
        seen: set[str] = set()
        for source in sources:
            if not isinstance(source, dict) or not source.get("id"):
                raise ValueError("Control-plane snapshot contains an invalid source")
            source_id = str(source["id"])
            seen.add(source_id)
            values = _server_values(source, by_source.get(source_id))
            existing = by_source.get(source_id)
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

        for source_id, row in by_source.items():
            if source_id not in seen:
                await db.execute(
                    "UPDATE api_servers SET is_active = 0, updated_at = datetime('now', '+7 hours') WHERE id = ?",
                    (row["id"],),
                )
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    await set_setting(REVISION_KEY, str(revision))
    await set_setting(STATUS_KEY, "healthy")
    return revision


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
        if etag:
            headers["If-None-Match"] = etag
        async with client.get(
            url,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=20),
        ) as response:
            if response.status == 304:
                await set_setting(STATUS_KEY, "healthy")
                return await get_setting_int(REVISION_KEY, 0)
            response.raise_for_status()
            snapshot = await response.json()
            response_etag = response.headers.get("ETag", "")
        revision = await apply_snapshot(snapshot)
        if response_etag:
            await set_setting(ETAG_KEY, response_etag)
        if revision:
            try:
                async with client.post(
                    f"{settings.platform_admin_url.rstrip('/')}/api/internal/config/consumers/shopbot/status",
                    json={"revision": revision, "status": "healthy", "checksum": snapshot.get("checksum", "")},
                    headers={"X-Control-Plane-Token": settings.portal_internal_token},
                    timeout=aiohttp.ClientTimeout(total=10),
                ):
                    pass
            except Exception:
                logger.warning("Unable to acknowledge control-plane revision %s", revision)
        return revision
    except Exception as exc:
        await set_setting(STATUS_KEY, "degraded")
        logger.warning("Control-plane sync degraded: %s", exc)
        if isinstance(snapshot, dict):
            try:
                await client.post(
                    f"{settings.platform_admin_url.rstrip('/')}/api/internal/config/consumers/shopbot/status",
                    json={"revision": int(snapshot.get("revision") or 0), "status": "degraded", "error": str(exc)[:1000]},
                    headers={"X-Control-Plane-Token": settings.portal_internal_token},
                    timeout=aiohttp.ClientTimeout(total=10),
                )
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
