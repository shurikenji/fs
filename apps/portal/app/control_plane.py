"""Optional control-plane registry import for pricing-hub."""
from __future__ import annotations

import logging

import httpx

from app.config import get_settings
from db.queries.servers import delete_server, get_all_servers, upsert_server
from db.queries.settings import set_setting

logger = logging.getLogger(__name__)


async def _fetch_control_plane_payloads() -> tuple[list[dict], dict[str, str]]:
    settings = get_settings()
    if not settings.control_plane_sync_enabled or not settings.control_plane_url or not settings.control_plane_token:
        return [], {}

    async with httpx.AsyncClient(timeout=20.0) as client:
        headers = {"X-Control-Plane-Token": settings.control_plane_token}
        base_url = settings.control_plane_url.rstrip("/")
        sources_response = await client.get(
            f"{base_url}/api/internal/service-sources",
            headers=headers,
        )
        sources_response.raise_for_status()
        settings_response = await client.get(
            f"{base_url}/api/internal/pricing-runtime-settings",
            headers=headers,
        )
        settings_response.raise_for_status()

    sources_payload = sources_response.json()
    runtime_payload = settings_response.json()
    return (
        sources_payload.get("service_sources", []),
        runtime_payload.get("settings", {}),
    )


def _as_bool(value: object) -> int:
    try:
        return 1 if int(value or 0) else 0
    except (TypeError, ValueError):
        return 1 if str(value or "").strip().lower() in {"true", "yes", "on"} else 0


async def import_control_plane_state() -> dict[str, int]:
    settings = get_settings()
    if not settings.control_plane_sync_enabled or not settings.control_plane_url or not settings.control_plane_token:
        return {
            "sources_imported": 0,
            "settings_imported": 0,
            "sources_deleted": 0,
        }

    sources, runtime_settings = await _fetch_control_plane_payloads()
    imported = 0
    source_ids: set[str] = set()
    for source in sources:
        source_id = str(source.get("id") or "").strip()
        if not source_id:
            continue

        source_ids.add(source_id)
        await upsert_server(
            source_id,
            name=str(source.get("name") or source_id).strip(),
            base_url=str(source.get("upstream_base_url") or "").strip(),
            type=str(source.get("source_type") or "newapi").strip() or "newapi",
            enabled=_as_bool(source.get("enabled")),
            sort_order=int(source.get("sort_order") or 0),
            quota_multiple=float(source.get("quota_multiple") or 1.0),
            balance_rate=float(source.get("balance_rate") or 1.0),
            public_pricing_enabled=_as_bool(source.get("public_pricing_enabled", 1)),
            public_balance_enabled=_as_bool(source.get("public_balance_enabled", 0)),
            public_keys_enabled=_as_bool(source.get("public_keys_enabled", 1)),
            public_logs_enabled=_as_bool(source.get("public_logs_enabled", 1)),
            supports_group_chain=_as_bool(source.get("supports_group_chain")),
            ratio_config_enabled=_as_bool(source.get("ratio_config_enabled")),
            auth_mode=str(source.get("auth_mode") or "header").strip() or "header",
            auth_user_header=str(source.get("auth_user_header") or "").strip(),
            auth_user_value=str(source.get("auth_user_value") or "").strip(),
            auth_token=str(source.get("auth_token") or "").strip(),
            auth_cookie=str(source.get("auth_cookie") or "").strip(),
            pricing_path=str(source.get("pricing_path") or "/api/pricing").strip(),
            ratio_config_path=str(source.get("ratio_config_path") or "/api/ratio_config").strip(),
            log_path=str(source.get("log_path") or "/api/log/self").strip(),
            token_search_path=str(source.get("token_search_path") or "/api/token/search").strip(),
            groups_path=str(source.get("groups_path") or "").strip(),
            manual_groups=str(source.get("manual_groups") or "").strip(),
            hidden_groups=str(source.get("hidden_groups") or "").strip(),
            excluded_models=str(source.get("excluded_models") or "").strip(),
            parser_override=str(source.get("parser_override") or "").strip(),
            display_profile=str(source.get("display_profile") or "").strip(),
            endpoint_aliases_json=str(source.get("endpoint_aliases_json") or "").strip(),
            variant_pricing_mode=str(source.get("variant_pricing_mode") or "").strip(),
            notes=str(source.get("notes") or "").strip(),
        )
        imported += 1

    deleted = 0
    for server in await get_all_servers():
        existing_id = str(server.get("id") or "").strip()
        if existing_id and existing_id not in source_ids:
            await delete_server(existing_id)
            deleted += 1

    settings_imported = 0
    for key, value in runtime_settings.items():
        await set_setting(str(key), "" if value is None else str(value))
        settings_imported += 1

    logger.info(
        "Imported %s control-plane sources into pricing-hub and %s runtime settings (%s deleted)",
        imported,
        settings_imported,
        deleted,
    )
    return {
        "sources_imported": imported,
        "settings_imported": settings_imported,
        "sources_deleted": deleted,
    }


async def import_control_plane_sources() -> int:
    result = await import_control_plane_state()
    return int(result.get("sources_imported") or 0)
