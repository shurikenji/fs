"""JSON API: /api/keys - resolve key info, list groups, change group."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.adapters import get_adapter
from app.cache import fetch_pricing
from app.group_catalog import ensure_server_group_catalog
from app.rate_limit import enforce_rate_limit
from app.sanitizer import sanitize_group_name
from app.translation_service import build_public_pricing
from app.visibility import (
    filter_group_rows,
    hidden_group_names,
    split_visible_and_hidden_groups,
    visibility_warning,
)
from db.queries.servers import get_public_server

router = APIRouter(prefix="/api", tags=["api"])


class KeyResolveRequest(BaseModel):
    server_id: str
    api_key: str


class KeyUpdateRequest(BaseModel):
    server_id: str
    api_key: str
    groups: list[str]


def _normalize_groups(raw: dict[str, Any]) -> list[str]:
    direct = raw.get("TokenGroup") or raw.get("group") or raw.get("selected_groups")
    if isinstance(direct, list):
        return [str(value).strip() for value in direct if str(value).strip()]
    if isinstance(direct, str):
        return [value.strip() for value in direct.split(",") if value.strip()]
    return []


def _selection_mode(server: dict) -> str:
    return "multiple" if bool(server.get("supports_group_chain")) else "single"


def _display_group_ratio(server: dict, ratio: object) -> float:
    try:
        group_ratio = float(ratio or 1.0)
    except (TypeError, ValueError):
        group_ratio = 1.0
    try:
        multiple = float(server.get("quota_multiple") or 1.0)
    except (TypeError, ValueError):
        multiple = 1.0
    if multiple <= 0:
        multiple = 1.0
    return round(group_ratio / multiple, 6)


def _normalize_selected_groups(groups: list[str], selection_mode: str) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for group in groups:
        value = str(group).strip()
        if value and value not in seen:
            seen.add(value)
            cleaned.append(value)
    if selection_mode == "single":
        return cleaned[:1]
    return cleaned


def _build_update_payload(server_type: str, raw: dict[str, Any], groups: list[str]) -> dict[str, Any] | None:
    joined = ",".join(groups)
    remain_quota = raw.get("remain_quota")
    if not isinstance(remain_quota, (int, float)):
        remain_quota = raw.get("remainQuota")
    if not isinstance(remain_quota, (int, float)):
        remain_quota = 0

    if server_type == "rixapi":
        return {
            "id": raw.get("id"),
            "remain_quota": remain_quota,
            "name": raw.get("name"),
            "group": joined,
            "TokenGroup": joined,
            "expired_time": raw.get("expired_time", -1),
            "key": raw.get("key"),
            "user_id": raw.get("user_id"),
            "created_time": raw.get("created_time"),
            "updated_time": raw.get("updated_time"),
            "status": raw.get("status"),
            "is_active": raw.get("is_active"),
            "mj_mode": raw.get("mj_mode", "default"),
            "mj_cdn": raw.get("mj_cdn", "default"),
            "mj_cdn_addr": raw.get("mj_cdn_addr", ""),
            "remain_count": raw.get("remain_count", 0),
            "unlimited_count": raw.get("unlimited_count", True),
            "model_limits_enabled": raw.get("model_limits_enabled", False),
            "model_limits": raw.get("model_limits", ""),
            "allow_ips": raw.get("allow_ips", ""),
            "exclude_ips": raw.get("exclude_ips", ""),
            "rate_limits_enabled": raw.get("rate_limits_enabled", False),
            "rate_limits_time": raw.get("rate_limits_time", 10),
            "rate_limits_count": raw.get("rate_limits_count", 900),
            "rate_limits_content": raw.get("rate_limits_content", ""),
        }

    if server_type == "newapi":
        return {
            "id": raw.get("id"),
            "remain_quota": remain_quota,
            "name": raw.get("name"),
            "group": joined,
            "selected_groups": groups if len(groups) > 1 else None,
            "expired_time": raw.get("expired_time", -1),
            "unlimited_quota": raw.get("unlimited_quota", False),
            "model_limits_enabled": raw.get("model_limits_enabled", False),
            "model_limits": raw.get("model_limits", ""),
            "allow_ips": raw.get("allow_ips", ""),
            "key": raw.get("key"),
            "user_id": raw.get("user_id"),
            "created_time": raw.get("created_time"),
            "updated_time": raw.get("updated_time"),
            "status": raw.get("status"),
            "is_active": raw.get("is_active"),
        }

    return None


@router.post("/keys/resolve")
async def api_key_resolve(body: KeyResolveRequest, request: Request):
    """Resolve API key to current groups and available group choices."""
    await enforce_rate_limit(
        request,
        bucket="key-resolve",
        limit=20,
        window_seconds=60,
        detail="Too many key lookups. Please wait a moment and try again.",
    )
    server = await get_public_server(body.server_id, "keys")
    if not server:
        return JSONResponse({"error": "Server not found"}, status_code=404)

    adapter = get_adapter(server)
    try:
        token = await adapter.search_token(server, body.api_key)
    except Exception:
        return JSONResponse({"error": "Could not resolve the provided API key."}, status_code=502)
    if not token:
        return JSONResponse({"error": "Token not found"}, status_code=404)

    pricing = await fetch_pricing(body.server_id, allow_upstream=False)
    public_pricing = await build_public_pricing(pricing, server) if pricing else None
    selection_mode = _selection_mode(server)
    hidden_groups = hidden_group_names(server)
    raw_groups = _normalize_selected_groups(_normalize_groups(token), selection_mode)
    visible_groups, hidden_selected_groups = split_visible_and_hidden_groups(
        raw_groups,
        hidden_groups=hidden_groups,
    )
    available_groups = []
    catalog_rows = await ensure_server_group_catalog(server)
    if catalog_rows:
        catalog_rows = filter_group_rows(catalog_rows, hidden_groups=hidden_groups)
        available_groups = [
            {
                "name": str(group.get("name") or ""),
                "display_name": sanitize_group_name(
                    str(group.get("name") or ""),
                    str(group.get("label_en") or group.get("name") or ""),
                ),
                "ratio": _display_group_ratio(server, group.get("ratio")),
                "category": str(group.get("category") or "Other"),
            }
            for group in catalog_rows
            if str(group.get("name") or "").strip()
        ]
    elif public_pricing:
        available_groups = [
            {
                "name": group.name,
                "display_name": sanitize_group_name(group.name, group.display_name),
                "ratio": _display_group_ratio(server, group.ratio),
                "category": group.category,
            }
            for group in public_pricing.groups
        ]

    return {
        "token": {
            "groups": visible_groups,
            "display_groups": [sanitize_group_name(group) for group in visible_groups],
        },
        "available_groups": available_groups,
        "supports_group_chain": bool(server.get("supports_group_chain")),
        "selection_mode": selection_mode,
        "has_hidden_groups": bool(hidden_selected_groups),
        "visibility_warning": visibility_warning(hidden_selected_groups),
    }


@router.put("/keys")
async def api_key_update(body: KeyUpdateRequest, request: Request):
    """Update token groups for a resolved API key."""
    await enforce_rate_limit(
        request,
        bucket="key-update",
        limit=10,
        window_seconds=60,
        detail="Too many key updates. Please wait a moment and try again.",
    )
    server = await get_public_server(body.server_id, "keys")
    if not server:
        return JSONResponse({"error": "Server not found"}, status_code=404)

    if not server.get("auth_token"):
        return JSONResponse(
            {"error": "Server admin token is not configured."},
            status_code=400,
        )

    selection_mode = _selection_mode(server)
    groups = _normalize_selected_groups(body.groups, selection_mode)
    if not groups:
        return JSONResponse({"error": "Select at least one group."}, status_code=400)
    if selection_mode == "single" and len(body.groups) > 1:
        return JSONResponse({"error": "This server allows only one group."}, status_code=400)

    hidden_groups = hidden_group_names(server)
    visible_group_names: set[str] = set()
    catalog_rows = await ensure_server_group_catalog(server)
    if catalog_rows:
        visible_group_names = {
            str(item.get("name") or "").strip()
            for item in filter_group_rows(catalog_rows, hidden_groups=hidden_groups)
            if str(item.get("name") or "").strip()
        }
    else:
        pricing = await fetch_pricing(body.server_id, allow_upstream=False)
        public_pricing = await build_public_pricing(pricing, server) if pricing else None
        if public_pricing:
            visible_group_names = {group.name for group in public_pricing.groups}

    if visible_group_names and any(group not in visible_group_names for group in groups):
        return JSONResponse({"error": "One or more groups are hidden or unavailable."}, status_code=400)

    adapter = get_adapter(server)
    try:
        token = await adapter.search_token(server, body.api_key)
    except Exception:
        return JSONResponse({"error": "Could not resolve the provided API key."}, status_code=502)
    if not token:
        return JSONResponse({"error": "Token not found"}, status_code=404)

    payload = _build_update_payload(str(server.get("type") or "newapi"), token, groups)
    if not payload:
        return JSONResponse(
            {"error": "This server type does not support token group updates yet."},
            status_code=400,
        )

    try:
        response = await adapter.update_token(server, payload)
    except Exception:
        return JSONResponse({"error": "Key update failed. Please try again later."}, status_code=502)

    if not response.get("success"):
        message = response.get("message") if isinstance(response, dict) else None
        return JSONResponse(
            {"error": message or "Upstream token update failed."},
            status_code=502,
        )

    return {
        "success": True,
        "groups": groups,
        "display_groups": [sanitize_group_name(group) for group in groups],
    }
