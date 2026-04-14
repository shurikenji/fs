"""Internal pricing admin bridge for platform-control."""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

from app.config import get_settings
from app.control_plane import import_control_plane_state
from app.group_catalog import ensure_server_group_catalog
from app.server_profiles import describe_server_profile
from app.sync_service import refresh_enabled_server_snapshots, refresh_server_snapshot
from app.translation_service import test_ai_connection
from app.visibility import dump_visibility_names, excluded_model_names, hidden_group_names, parse_visibility_names
from db.queries.servers import (
    get_enabled_servers,
    get_latest_sync_map,
    get_server,
    get_sync_runs,
    upsert_server,
)
from db.queries.settings import get_settings_dict, set_setting
from app.schemas import NormalizedPricing

router = APIRouter(prefix="/api/internal/admin/pricing", tags=["internal"])

_SETTINGS_DEFAULTS = {
    "ai_provider": get_settings().ai_provider,
    "ai_api_key": get_settings().ai_api_key,
    "ai_model": get_settings().ai_model,
    "ai_base_url": get_settings().ai_base_url,
    "ai_enabled": "true" if get_settings().ai_enabled else "false",
    "auto_sync_enabled": "false",
    "auto_sync_interval_minutes": "15",
}


class VisibilityPayload(BaseModel):
    visible_groups: list[str] = []
    visible_models: list[str] = []


class SettingsPayload(BaseModel):
    ai_provider: str = "openai"
    ai_api_key: str = ""
    ai_model: str = "gpt-4o-mini"
    ai_base_url: str = ""
    ai_enabled: bool = False
    auto_sync_enabled: bool = False
    auto_sync_interval_minutes: int = 15


class AITestPayload(BaseModel):
    provider: str = "openai"
    api_key: str = ""
    model: str = "gpt-4o-mini"
    base_url: str = ""


def _require_admin_token(token: str | None) -> None:
    expected = get_settings().pricing_admin_token
    if not expected or token != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _load_cached_pricing(server: dict[str, Any]) -> NormalizedPricing | None:
    raw = str(server.get("pricing_cache") or "").strip()
    if not raw:
        return None
    try:
        return NormalizedPricing.model_validate_json(raw)
    except Exception:
        return None


def _serialize_sync_run(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "source_id": str(row.get("server_id") or "").strip(),
        "status": str(row.get("status") or "").strip(),
        "trigger": str(row.get("trigger") or "manual").strip(),
        "model_count": int(row.get("model_count") or 0),
        "group_count": int(row.get("group_count") or 0),
        "translated_count": None,
        "duration_ms": int(row.get("duration_ms") or 0),
        "error_message": str(row.get("error_message") or "").strip(),
        "created_at": str(row.get("created_at") or "").strip(),
        "origin": "runtime",
    }


def _serialize_model_rows(server: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    pricing = _load_cached_pricing(server)
    if not pricing:
        return [], []
    hidden_groups = hidden_group_names(server)
    excluded_models = excluded_model_names(server)
    rows: list[dict[str, Any]] = []
    for model in pricing.models:
        group_names = sorted(set(model.enable_groups) | set(model.group_prices))
        visible_group_count = len([name for name in group_names if name not in hidden_groups])
        rows.append(
            {
                "model_name": model.model_name,
                "vendor_name": model.vendor_name,
                "display_mode": model.display_mode,
                "pricing_mode": model.pricing_mode.value,
                "variant_count": len(model.pricing_variants),
                "group_count": len(group_names),
                "visible_group_count": visible_group_count,
            }
        )
    rows.sort(key=lambda item: item["model_name"].lower())
    visible_models = [row["model_name"] for row in rows if row["model_name"] not in excluded_models]
    return rows, visible_models


@router.post("/import-control-plane")
async def import_control_plane(x_pricing_admin_token: str | None = Header(default=None)):
    _require_admin_token(x_pricing_admin_token)
    result = await import_control_plane_state()
    return {"success": True, **result}


@router.post("/sources/sync-all")
async def sync_all_sources(
    x_pricing_admin_token: str | None = Header(default=None),
    trigger: str = Query(default="manual"),
):
    _require_admin_token(x_pricing_admin_token)
    started_at = time.perf_counter()
    results = await refresh_enabled_server_snapshots(trigger=trigger)
    return {
        "success": True,
        "sources": len(results),
        "models": sum(len(result.pricing.models) for result in results if result.pricing),
        "groups": sum(len(result.pricing.groups) for result in results if result.pricing),
        "translations": sum(result.translated_count for result in results),
        "duration_ms": int((time.perf_counter() - started_at) * 1000),
    }


@router.post("/sources/{source_id}/sync")
async def sync_source(
    source_id: str,
    x_pricing_admin_token: str | None = Header(default=None),
    trigger: str = Query(default="manual"),
):
    _require_admin_token(x_pricing_admin_token)
    if not await get_server(source_id):
        raise HTTPException(status_code=404, detail="Source not found")
    started_at = time.perf_counter()
    result = await refresh_server_snapshot(source_id, trigger=trigger)
    latest_sync = (await get_latest_sync_map()).get(source_id, {})
    return {
        "success": result.pricing is not None,
        "source_id": source_id,
        "models": len(result.pricing.models) if result.pricing else 0,
        "groups": len(result.pricing.groups) if result.pricing else 0,
        "translations": result.translated_count,
        "duration_ms": int(latest_sync.get("duration_ms") or int((time.perf_counter() - started_at) * 1000)),
        "status": latest_sync.get("status") or ("success" if result.pricing else "failed"),
        "error": latest_sync.get("error_message") or "",
    }


@router.get("/sync-runs")
async def sync_runs(
    x_pricing_admin_token: str | None = Header(default=None),
    source_id: str = Query(default=""),
    status: str = Query(default=""),
    trigger: str = Query(default=""),
    limit: int = Query(default=200, ge=1, le=500),
):
    _require_admin_token(x_pricing_admin_token)
    runs = await get_sync_runs(
        source_id=source_id or None,
        status=status or None,
        trigger=trigger or None,
        limit=limit,
    )
    return {
        "success": True,
        "runs": [_serialize_sync_run(row) for row in runs if row],
    }


@router.get("/sync-runs/latest")
async def latest_sync_runs(x_pricing_admin_token: str | None = Header(default=None)):
    _require_admin_token(x_pricing_admin_token)
    latest_map = await get_latest_sync_map()
    return {
        "success": True,
        "latest": {
            source_id: _serialize_sync_run(row)
            for source_id, row in latest_map.items()
            if row
        },
    }


@router.get("/sources/{source_id}/groups")
async def source_groups(source_id: str, x_pricing_admin_token: str | None = Header(default=None)):
    _require_admin_token(x_pricing_admin_token)
    server = await get_server(source_id)
    if not server:
        raise HTTPException(status_code=404, detail="Source not found")
    groups = await ensure_server_group_catalog(server)
    hidden_groups = hidden_group_names(server)
    profile = describe_server_profile(server)
    return {
        "success": True,
        "source_id": source_id,
        "source_label": "Manual override" if str(server.get("manual_groups") or "").strip() else "Runtime catalog",
        "parser_id": profile["parser_id"],
        "display_profile": profile["display_profile"],
        "variant_pricing_mode": profile["variant_pricing_mode"],
        "groups": groups,
        "visible_groups": [
            str(group.get("name") or "").strip()
            for group in groups
            if str(group.get("name") or "").strip() and str(group.get("name") or "").strip() not in hidden_groups
        ],
    }


@router.post("/sources/{source_id}/groups/refresh")
async def refresh_source_groups(source_id: str, x_pricing_admin_token: str | None = Header(default=None)):
    _require_admin_token(x_pricing_admin_token)
    server = await get_server(source_id)
    if not server:
        raise HTTPException(status_code=404, detail="Source not found")
    groups = await ensure_server_group_catalog(server, force=True)
    return {"success": True, "source_id": source_id, "groups": len(groups)}


@router.post("/sources/{source_id}/groups/save")
async def save_source_groups(
    source_id: str,
    body: VisibilityPayload,
    x_pricing_admin_token: str | None = Header(default=None),
):
    _require_admin_token(x_pricing_admin_token)
    server = await get_server(source_id)
    if not server:
        raise HTTPException(status_code=404, detail="Source not found")
    groups = await ensure_server_group_catalog(server)
    catalog_names = [
        str(group.get("name") or "").strip()
        for group in groups
        if str(group.get("name") or "").strip()
    ]
    visible_groups = set(parse_visibility_names(body.visible_groups))
    hidden_groups = [name for name in catalog_names if name not in visible_groups]
    await upsert_server(source_id, hidden_groups=dump_visibility_names(hidden_groups))
    return {"success": True, "source_id": source_id, "hidden_groups": hidden_groups}


@router.get("/sources/{source_id}/models")
async def source_models(source_id: str, x_pricing_admin_token: str | None = Header(default=None)):
    _require_admin_token(x_pricing_admin_token)
    server = await get_server(source_id)
    if not server:
        raise HTTPException(status_code=404, detail="Source not found")
    rows, visible_models = _serialize_model_rows(server)
    profile = describe_server_profile(server)
    return {
        "success": True,
        "source_id": source_id,
        "parser_id": profile["parser_id"],
        "display_profile": profile["display_profile"],
        "variant_pricing_mode": profile["variant_pricing_mode"],
        "models": rows,
        "visible_models": visible_models,
    }


@router.post("/sources/{source_id}/models/save")
async def save_source_models(
    source_id: str,
    body: VisibilityPayload,
    x_pricing_admin_token: str | None = Header(default=None),
):
    _require_admin_token(x_pricing_admin_token)
    server = await get_server(source_id)
    if not server:
        raise HTTPException(status_code=404, detail="Source not found")
    rows, _ = _serialize_model_rows(server)
    catalog_names = [row["model_name"] for row in rows]
    visible_models = set(parse_visibility_names(body.visible_models))
    excluded_models = [name for name in catalog_names if name not in visible_models]
    await upsert_server(source_id, excluded_models=dump_visibility_names(excluded_models))
    return {"success": True, "source_id": source_id, "excluded_models": excluded_models}


@router.get("/settings")
async def runtime_settings(x_pricing_admin_token: str | None = Header(default=None)):
    _require_admin_token(x_pricing_admin_token)
    return {"success": True, "settings": await get_settings_dict(_SETTINGS_DEFAULTS)}


@router.post("/settings/save")
async def save_runtime_settings(
    body: SettingsPayload,
    x_pricing_admin_token: str | None = Header(default=None),
):
    _require_admin_token(x_pricing_admin_token)
    values = {
        "ai_provider": body.ai_provider.strip() or "openai",
        "ai_api_key": body.ai_api_key.strip(),
        "ai_model": body.ai_model.strip(),
        "ai_base_url": body.ai_base_url.strip(),
        "ai_enabled": "true" if body.ai_enabled else "false",
        "auto_sync_enabled": "true" if body.auto_sync_enabled else "false",
        "auto_sync_interval_minutes": str(max(1, body.auto_sync_interval_minutes)),
    }
    for key, value in values.items():
        await set_setting(key, value)
    return {"success": True, "settings": await get_settings_dict(_SETTINGS_DEFAULTS)}


@router.post("/settings/ai/test")
async def test_runtime_ai(
    body: AITestPayload,
    x_pricing_admin_token: str | None = Header(default=None),
):
    _require_admin_token(x_pricing_admin_token)
    success, message = await test_ai_connection(
        provider=body.provider.strip(),
        api_key=body.api_key.strip(),
        model=body.model.strip(),
        base_url=body.base_url.strip(),
    )
    return {"success": success, "message": message}
