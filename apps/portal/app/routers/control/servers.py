"""Admin server management: CRUD + sync."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

from app.control_plane import import_control_plane_sources
from app.deps import get_templates
from app.group_catalog import ensure_server_group_catalog
from app.server_profiles import describe_server_profile
from app.schemas import NormalizedPricing
from app.sync_service import refresh_enabled_server_snapshots, refresh_server_snapshot
from app.visibility import (
    dump_visibility_names,
    excluded_model_names,
    hidden_group_names,
    parse_visibility_names,
)
from db.queries.servers import (
    delete_server,
    get_all_servers,
    get_latest_sync_map,
    get_server,
    upsert_server,
)

router = APIRouter(prefix="/control/servers", tags=["admin"])

_SERVER_TYPES = [
    {"value": "newapi", "label": "NewAPI Standard"},
    {"value": "rixapi", "label": "RixAPI (Inline Ratio)"},
    {"value": "custom", "label": "Custom Manual"},
]
_DEFAULT_USER_HEADER = "New-Api-User"


@router.get("", response_class=HTMLResponse)
async def servers_page(request: Request):
    if not request.session.get("is_admin"):
        return RedirectResponse("/control/login", status_code=303)

    templates = get_templates()
    sync_map = await get_latest_sync_map()
    flash_message = request.session.pop("flash_message", "")
    servers = []
    for server in await get_all_servers():
        server_copy = dict(server)
        server_copy["latest_sync"] = sync_map.get(server["id"])
        server_copy["hidden_group_count"] = len(parse_visibility_names(server.get("hidden_groups")))
        server_copy["excluded_model_count"] = len(parse_visibility_names(server.get("excluded_models")))
        server_copy["active_profile"] = describe_server_profile(server_copy)
        servers.append(server_copy)

    return templates.TemplateResponse(
        "control/servers.html",
        {
            "request": request,
            "flash_message": flash_message,
            "servers": servers,
            "server_types": _SERVER_TYPES,
        },
    )


@router.post("/save")
async def servers_save(request: Request):
    if not request.session.get("is_admin"):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    form = await request.form()
    server_id = str(form.get("id", "")).strip()
    if not server_id:
        return RedirectResponse("/control/servers", status_code=303)

    server_type = str(form.get("type", "newapi")).strip()
    auth_mode = str(form.get("auth_mode", "header")).strip()
    auth_user_header = str(form.get("auth_user_header", "")).strip()
    if server_type in {"newapi", "rixapi"} and auth_mode == "header":
        auth_user_header = _DEFAULT_USER_HEADER

    fields = {
        "name": str(form.get("name", "")).strip(),
        "base_url": str(form.get("base_url", "")).strip(),
        "type": server_type,
        "enabled": 1 if form.get("enabled") else 0,
        "sort_order": int(form.get("sort_order", 0) or 0),
        "quota_multiple": float(form.get("quota_multiple", 1.0) or 1.0),
        "supports_group_chain": 1 if form.get("supports_group_chain") else 0,
        "ratio_config_enabled": 1 if form.get("ratio_config_enabled") else 0,
        "auth_mode": auth_mode,
        "auth_user_header": auth_user_header,
        "auth_user_value": str(form.get("auth_user_value", "")).strip(),
        "auth_token": str(form.get("auth_token", "")).strip(),
        "auth_cookie": str(form.get("auth_cookie", "")).strip(),
        "pricing_path": str(form.get("pricing_path", "/api/pricing")).strip(),
        "ratio_config_path": str(form.get("ratio_config_path", "/api/ratio_config")).strip(),
        "log_path": str(form.get("log_path", "/api/log/self")).strip(),
        "token_search_path": str(form.get("token_search_path", "/api/token/search")).strip(),
        "groups_path": str(form.get("groups_path", "")).strip(),
        "manual_groups": str(form.get("manual_groups", "")).strip(),
        "parser_override": str(form.get("parser_override", "")).strip(),
        "display_profile": str(form.get("display_profile", "")).strip(),
        "endpoint_aliases_json": str(form.get("endpoint_aliases_json", "")).strip(),
        "variant_pricing_mode": str(form.get("variant_pricing_mode", "")).strip(),
        "notes": str(form.get("notes", "")).strip(),
    }

    await upsert_server(server_id, **fields)
    return RedirectResponse("/control/servers", status_code=303)


@router.get("/{server_id}/delete")
async def servers_delete(request: Request, server_id: str):
    if not request.session.get("is_admin"):
        return RedirectResponse("/control/login", status_code=303)
    await delete_server(server_id)
    return RedirectResponse("/control/servers", status_code=303)


@router.post("/sync-all")
async def servers_sync_all(request: Request):
    if not request.session.get("is_admin"):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    await refresh_enabled_server_snapshots(trigger="manual")
    return RedirectResponse("/control/servers", status_code=303)


@router.post("/import-control-plane")
async def servers_import_control_plane(request: Request):
    if not request.session.get("is_admin"):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    imported = await import_control_plane_sources()
    request.session["flash_message"] = f"Imported {imported} service sources from control plane."
    return RedirectResponse("/control/servers", status_code=303)


@router.post("/{server_id}/sync")
async def servers_sync(request: Request, server_id: str):
    if not request.session.get("is_admin"):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    result = await refresh_server_snapshot(server_id, trigger="manual")
    if result.pricing:
        return {
            "success": True,
            "models": len(result.pricing.models),
            "groups": len(result.pricing.groups),
            "translations": result.translated_count,
        }
    return JSONResponse({"error": "Sync failed"}, status_code=500)


def _redirect_with_flash(request: Request, url: str, message: str) -> RedirectResponse:
    request.session["flash_message"] = message
    return RedirectResponse(url, status_code=303)


def _load_cached_pricing(server: dict) -> NormalizedPricing | None:
    raw = str(server.get("pricing_cache") or "").strip()
    if not raw:
        return None
    try:
        return NormalizedPricing.model_validate_json(raw)
    except Exception:
        return None


def _source_label(server: dict) -> str:
    if str(server.get("manual_groups") or "").strip():
        return "Manual override"
    if str(server.get("groups_cache") or "").strip():
        return "Cached remote catalog"
    return "Remote catalog"


@router.get("/{server_id}/groups", response_class=HTMLResponse)
async def server_groups_page(request: Request, server_id: str):
    if not request.session.get("is_admin"):
        return RedirectResponse("/control/login", status_code=303)

    server = await get_server(server_id)
    if not server:
        return _redirect_with_flash(request, "/control/servers", "Server not found.")

    templates = get_templates()
    groups_data = await ensure_server_group_catalog(server)
    hidden_groups = hidden_group_names(server)
    flash_message = request.session.pop("flash_message", "")

    return templates.TemplateResponse(
        "control/server_groups.html",
        {
            "request": request,
            "flash_message": flash_message,
            "server": server,
            "groups_data": groups_data,
            "visible_groups": [
                str(group.get("name") or "").strip()
                for group in groups_data
                if str(group.get("name") or "").strip() not in hidden_groups
            ],
            "hidden_group_count": len(hidden_groups),
            "source_label": _source_label(server),
        },
    )


@router.post("/{server_id}/groups/save")
async def server_groups_save(request: Request, server_id: str):
    if not request.session.get("is_admin"):
        return RedirectResponse("/control/login", status_code=303)

    server = await get_server(server_id)
    if not server:
        return _redirect_with_flash(request, "/control/servers", "Server not found.")

    groups_data = await ensure_server_group_catalog(server)
    catalog_names = [
        str(group.get("name") or "").strip()
        for group in groups_data
        if str(group.get("name") or "").strip()
    ]
    form = await request.form()
    visible_groups = set(parse_visibility_names(form.getlist("visible_groups")))
    hidden_groups = [name for name in catalog_names if name not in visible_groups]
    await upsert_server(server_id, hidden_groups=dump_visibility_names(hidden_groups))
    return _redirect_with_flash(
        request,
        f"/control/servers/{server_id}/groups",
        "Group visibility updated.",
    )


@router.post("/{server_id}/groups/refresh")
async def server_groups_refresh(request: Request, server_id: str):
    if not request.session.get("is_admin"):
        return RedirectResponse("/control/login", status_code=303)

    server = await get_server(server_id)
    if not server:
        return _redirect_with_flash(request, "/control/servers", "Server not found.")

    await ensure_server_group_catalog(server, force=True)
    return _redirect_with_flash(
        request,
        f"/control/servers/{server_id}/groups",
        "Group catalog refreshed.",
    )


@router.get("/{server_id}/models", response_class=HTMLResponse)
async def server_models_page(request: Request, server_id: str):
    if not request.session.get("is_admin"):
        return RedirectResponse("/control/login", status_code=303)

    server = await get_server(server_id)
    if not server:
        return _redirect_with_flash(request, "/control/servers", "Server not found.")

    templates = get_templates()
    flash_message = request.session.pop("flash_message", "")
    pricing = _load_cached_pricing(server)
    hidden_groups = hidden_group_names(server)
    excluded_models = excluded_model_names(server)

    model_rows = []
    if pricing:
        for model in pricing.models:
            group_names = sorted(set(model.enable_groups) | set(model.group_prices))
            visible_group_count = len([
                group_name
                for group_name in group_names
                if group_name not in hidden_groups
            ])
            model_rows.append(
                {
                    "model_name": model.model_name,
                    "vendor_name": model.vendor_name,
                    "pricing_mode": model.pricing_mode.value,
                    "group_count": len(group_names),
                    "visible_group_count": visible_group_count,
                }
            )
        model_rows.sort(key=lambda item: item["model_name"].lower())

    return templates.TemplateResponse(
        "control/server_models.html",
        {
            "request": request,
            "flash_message": flash_message,
            "server": server,
            "models_data": model_rows,
            "visible_models": [
                row["model_name"]
                for row in model_rows
                if row["model_name"] not in excluded_models
            ],
            "excluded_model_count": len(excluded_models),
        },
    )


@router.post("/{server_id}/models/save")
async def server_models_save(request: Request, server_id: str):
    if not request.session.get("is_admin"):
        return RedirectResponse("/control/login", status_code=303)

    server = await get_server(server_id)
    if not server:
        return _redirect_with_flash(request, "/control/servers", "Server not found.")

    pricing = _load_cached_pricing(server)
    if not pricing:
        return _redirect_with_flash(
            request,
            f"/control/servers/{server_id}/models",
            "No pricing cache found. Sync pricing first.",
        )

    catalog_names = parse_visibility_names([model.model_name for model in pricing.models])
    form = await request.form()
    visible_models = set(parse_visibility_names(form.getlist("visible_models")))
    excluded_models = [name for name in catalog_names if name not in visible_models]
    await upsert_server(server_id, excluded_models=dump_visibility_names(excluded_models))
    return _redirect_with_flash(
        request,
        f"/control/servers/{server_id}/models",
        "Model visibility updated.",
    )
