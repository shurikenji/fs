"""
admin/routers/servers.py - API server CRUD and group inspection routes.
"""
from __future__ import annotations

import json
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Path, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from admin.deps import get_templates, protected_router
from bot.services.ai_translator import get_translator
from bot.services.api_clients import get_api_client
from bot.utils.time_utils import get_now_vn
from db.queries.pricing import (
    get_server_discount_tiers,
    list_server_pricing_versions,
    replace_server_discount_tiers,
    sync_server_pricing_version,
)
from db.queries.servers import (
    create_server,
    delete_server,
    get_all_servers,
    get_server_by_id,
    update_server,
)

router = protected_router(prefix="/servers", tags=["servers"])

_API_TYPES = [
    {"value": "newapi", "label": "NewAPI"},
    {"value": "rixapi", "label": "RixAPI"},
    {"value": "other", "label": "Khác (tùy chỉnh)"},
]

_AUTH_TYPES = [
    {"value": "header", "label": "Header + Bearer"},
    {"value": "bearer_only", "label": "Chỉ dùng Bearer"},
    {"value": "cookie", "label": "Xác thực bằng cookie"},
    {"value": "none", "label": "Không xác thực"},
]

_DISCOUNT_STACK_MODES = [
    {"value": "exclusive", "label": "Chỉ lấy ưu đãi tốt nhất"},
    {"value": "combine_selected_types", "label": "Cộng dồn các loại đã chọn"},
]


def _clean_str(value: object, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _parse_discount_tiers_json(raw_value: object) -> list[dict]:
    raw_text = _clean_str(raw_value)
    if not raw_text:
        return []

    payload = json.loads(raw_text)
    if not isinstance(payload, list):
        raise ValueError("Discount tiers JSON must be an array.")

    tiers: list[dict] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("Each discount tier must be an object.")
        benefits = item.get("benefits") or []
        if not isinstance(benefits, list):
            raise ValueError("Tier benefits must be an array.")
        tiers.append(
            {
                "name": _clean_str(item.get("name"), "Tier"),
                "min_spend_vnd": int(item.get("min_spend_vnd") or 0),
                "is_active": bool(item.get("is_active", True)),
                "benefits": [
                    {
                        "type": _clean_str(benefit.get("type")),
                        "value": benefit.get("value"),
                        "config": benefit.get("config") if isinstance(benefit, dict) else {},
                        "is_active": bool(benefit.get("is_active", True)) if isinstance(benefit, dict) else True,
                    }
                    for benefit in benefits
                    if isinstance(benefit, dict) and _clean_str(benefit.get("type"))
                ],
            }
        )
    return tiers


def _server_page_context(*, request: Request, servers: list[dict], **extra: object) -> dict[str, object]:
    return {
        "request": request,
        "servers": servers,
        "api_types": _API_TYPES,
        "auth_types": _AUTH_TYPES,
        "discount_stack_modes": _DISCOUNT_STACK_MODES,
        **_build_server_flash_context(request),
        **extra,
    }


async def _load_servers_for_page() -> list[dict]:
    servers = await get_all_servers()
    for server in servers:
        if _clean_str(server.get("api_type", "newapi"), "newapi").lower() == "rixapi":
            server["supports_multi_group"] = 1
    return servers


def _build_server_flash_context(request: Request) -> dict[str, str]:
    error = _clean_str(request.query_params.get("error"))
    if error == "invalid_discount_tiers":
        return {
            "flash_message": "Cấu hình discount tiers không hợp lệ. Vui lòng kiểm tra lại JSON.",
            "flash_type": "danger",
        }
    return {}


async def _hydrate_server_pricing_context(server: dict) -> dict:
    tiers = await get_server_discount_tiers(server["id"])
    server["discount_tiers_json"] = json.dumps(
        [
            {
                "name": tier.get("name"),
                "min_spend_vnd": tier.get("min_spend_vnd"),
                "is_active": bool(tier.get("is_active", 1)),
                "benefits": [
                    {
                        "type": benefit.get("benefit_type") or benefit.get("type"),
                        "value": benefit.get("value_amount") if "value_amount" in benefit else benefit.get("value"),
                        "config": benefit.get("config", {}),
                        "is_active": bool(benefit.get("is_active", 1)),
                    }
                    for benefit in tier.get("benefits", [])
                ],
            }
            for tier in tiers
        ],
        indent=2,
        ensure_ascii=True,
    )
    server["pricing_versions"] = await list_server_pricing_versions(server["id"])
    return server


async def _build_server_edit_context(server_id: int) -> dict | None:
    server = await get_server_by_id(server_id)
    if not server:
        return None

    return {
        "editing": await _hydrate_server_pricing_context(_normalize_server_for_form(server)),
        "api_types": _API_TYPES,
        "auth_types": _AUTH_TYPES,
        "discount_stack_modes": _DISCOUNT_STACK_MODES,
    }


def _redirect_to_servers() -> RedirectResponse:
    return RedirectResponse("/servers", status_code=303)


def _resolve_redirect_target(candidate: object, fallback: str) -> str:
    if candidate is not None:
        value = str(candidate).strip()
        if value.startswith("/"):
            return value
        parsed = urlsplit(value)
        if parsed.path.startswith("/"):
            return parsed.path + (f"?{parsed.query}" if parsed.query else "")
    return fallback


def _server_not_found_payload() -> dict[str, object]:
    return {"success": False, "message": "Server not found"}


def _split_group_names(value: str) -> list[str]:
    return [name.strip() for name in value.split(",") if name.strip()]


def _groups_source_label(source: str) -> str:
    labels = {
        "manual": "Manual override",
        "cache": "Saved cache",
        "remote": "Remote refresh",
        "empty": "No groups available",
    }
    return labels.get(source, source.title())


async def _get_server_or_redirect(server_id: int) -> dict | RedirectResponse:
    server = await get_server_by_id(server_id)
    if server:
        return server
    return _redirect_to_servers()


async def _get_server_or_json(server_id: int) -> dict | JSONResponse:
    server = await get_server_by_id(server_id)
    if server:
        return server
    return JSONResponse(_server_not_found_payload())


def _build_manual_group_rows(manual_groups: str) -> list[dict]:
    return [
        {
            "name": name.strip(),
            "label_en": name.strip(),
            "ratio": 1.0,
            "desc": "",
            "category": "Other",
        }
        for name in _split_group_names(manual_groups)
    ]


async def _load_manual_group_rows(server: dict) -> list[dict]:
    manual_groups = _clean_str(server.get("manual_groups"))
    if not manual_groups:
        return []
    return _normalize_group_rows(
        await _translate_groups_for_server(
            _build_manual_group_rows(manual_groups),
            server,
        )
    )


def _get_supports_multi_group(server: dict) -> bool:
    return get_api_client(server).get_supports_multi_group(server)


def _load_cached_group_rows(server: dict) -> list[dict]:
    raw_cache = server.get("groups_cache")
    if not raw_cache:
        return []

    try:
        payload = json.loads(raw_cache)
    except (TypeError, json.JSONDecodeError):
        return []

    if not isinstance(payload, list):
        return []

    rows = [item for item in payload if isinstance(item, dict)]
    return _normalize_group_rows(rows)


async def _store_groups_cache(server: dict, groups_data: list[dict]) -> None:
    server_id = server.get("id")
    if not server_id:
        return

    timestamp = get_now_vn().isoformat()
    cache_payload = json.dumps(groups_data, ensure_ascii=True)
    server["groups_cache"] = cache_payload
    server["groups_updated_at"] = timestamp
    await update_server(
        server_id,
        groups_cache=cache_payload,
        groups_updated_at=timestamp,
    )


async def _load_catalog_groups(
    server: dict,
    *,
    force_refresh: bool = False,
) -> tuple[list[dict], str]:
    if not force_refresh:
        cached_groups = _load_cached_group_rows(server)
        if cached_groups:
            return cached_groups, "cache"

    remote_groups = await _load_and_translate_groups(server)
    if remote_groups:
        await _store_groups_cache(server, remote_groups)
        return remote_groups, "remote"

    cached_groups = _load_cached_group_rows(server)
    if cached_groups:
        return cached_groups, "cache"

    manual_groups = server.get("manual_groups", "")
    if manual_groups:
        return await _load_manual_group_rows(server), "manual"

    return [], "empty"


async def _resolve_groups_data(server: dict) -> list[dict]:
    manual_groups = server.get("manual_groups", "")
    if manual_groups:
        return await _load_manual_group_rows(server)
    groups_data, _ = await _load_catalog_groups(server)
    return groups_data


def _build_groups_lookup(groups_data: list[dict]) -> dict[str, dict]:
    return {
        group["name"]: group
        for group in groups_data
        if group.get("name")
    }


async def _build_groups_page_context(request: Request, server: dict) -> dict[str, object]:
    server = {
        **server,
        "default_group": _clean_str(server.get("default_group")),
        "manual_groups": _clean_str(server.get("manual_groups")),
    }
    cached_groups = _load_cached_group_rows(server)
    if server["manual_groups"] and not cached_groups:
        catalog_groups = await _load_manual_group_rows(server)
        catalog_source = "manual"
    else:
        catalog_groups, catalog_source = await _load_catalog_groups(server)
    effective_source = "manual" if server.get("manual_groups", "") else catalog_source
    return _server_page_context(
        request=request,
        servers=await _load_servers_for_page(),
        groups_server=server,
        groups_data=catalog_groups,
        groups_source=catalog_source,
        groups_source_label=_groups_source_label(catalog_source),
        effective_source=effective_source,
        effective_source_label=_groups_source_label(effective_source),
        current_default_groups=_split_group_names(server.get("default_group", "")),
        groups_updated_at=server.get("groups_updated_at"),
        supports_multi_group=_get_supports_multi_group(server),
    )


def _build_groups_json_payload(server: dict, groups_data: list[dict]) -> dict[str, object]:
    return {
        "success": True,
        "data": _build_groups_lookup(groups_data),
        "supports_multi_group": _get_supports_multi_group(server),
        "api_type": server.get("api_type", "newapi"),
    }


def _build_groups_preview_payload(server: dict, groups_data: list[dict]) -> dict[str, object]:
    return {
        "success": True,
        "data": groups_data,
        "supports_multi_group": _get_supports_multi_group(server),
        "api_type": server.get("api_type", "newapi"),
    }


def _get_server_form_payload(form) -> dict:
    api_type = _clean_str(form.get("api_type", "newapi"), "newapi").lower()
    legacy_user_id = _clean_str(form.get("auth_user_value") or form.get("user_id_header"))
    legacy_token = _clean_str(form.get("auth_token") or form.get("access_token"))

    payload = {
        "name": _clean_str(form.get("name")),
        "base_url": _clean_str(form.get("base_url")),
        "price_per_unit": int(form["price_per_unit"]) if form.get("price_per_unit") else None,
        "quota_per_unit": int(form["quota_per_unit"]) if form.get("quota_per_unit") else None,
        "dollar_per_unit": float(form.get("dollar_per_unit", 10.0)),
        "quota_multiple": float(form.get("quota_multiple", 1.0)),
        "default_group": _clean_str(form.get("default_group")),
        "api_type": api_type,
        "import_spend_accrual_enabled": 1 if form.get("import_spend_accrual_enabled") else 0,
        "discount_stack_mode": _clean_str(form.get("discount_stack_mode"), "exclusive"),
        "discount_allowed_stack_types": _clean_str(form.get("discount_allowed_stack_types"), "cashback"),
    }

    if api_type == "newapi":
        payload.update(
            {
                "user_id_header": legacy_user_id,
                "access_token": legacy_token,
                "supports_multi_group": 1 if form.get("supports_multi_group") else 0,
                "manual_groups": _clean_str(form.get("manual_groups")),
                "auth_type": "header",
                "auth_user_header": "new-api-user",
                "auth_user_value": legacy_user_id,
                "auth_token": legacy_token,
                "auth_cookie": "",
                "custom_headers": "",
                "groups_endpoint": "",
            }
        )
        return payload

    if api_type == "rixapi":
        payload.update(
            {
                "user_id_header": legacy_user_id,
                "access_token": legacy_token,
                "supports_multi_group": 1,
                "manual_groups": _clean_str(form.get("manual_groups")),
                "auth_type": "header",
                "auth_user_header": "rix-api-user",
                "auth_user_value": legacy_user_id,
                "auth_token": legacy_token,
                "auth_cookie": "",
                "custom_headers": "",
                "groups_endpoint": "",
            }
        )
        return payload

    auth_type = _clean_str(form.get("auth_type", "header"), "header")
    auth_user_header = _clean_str(form.get("auth_user_header"), "new-api-user")
    auth_user_value = _clean_str(form.get("auth_user_value"))
    auth_token = _clean_str(form.get("auth_token"))
    auth_cookie = _clean_str(form.get("auth_cookie"))

    payload.update(
        {
            "user_id_header": auth_user_value,
            "access_token": auth_token,
            "supports_multi_group": 1 if form.get("supports_multi_group") else 0,
            "manual_groups": _clean_str(form.get("manual_groups")),
            "auth_type": auth_type,
            "auth_user_header": auth_user_header,
            "auth_user_value": auth_user_value,
            "auth_token": auth_token,
            "auth_cookie": auth_cookie,
            "custom_headers": _clean_str(form.get("custom_headers")),
            "groups_endpoint": _clean_str(form.get("groups_endpoint")),
        }
    )
    return payload


def _normalize_server_for_form(server: dict) -> dict:
    api_type = _clean_str(server.get("api_type", "newapi"), "newapi").lower()
    legacy_user_id = _clean_str(server.get("auth_user_value") or server.get("user_id_header"))
    token = _clean_str(server.get("auth_token") or server.get("access_token"))

    server["api_type"] = api_type
    server["supports_multi_group"] = server.get("supports_multi_group", 0)
    server["manual_groups"] = server.get("manual_groups", "") or ""
    server["custom_headers"] = server.get("custom_headers", "") or ""
    server["groups_endpoint"] = server.get("groups_endpoint", "") or ""
    server["auth_cookie"] = server.get("auth_cookie", "") or ""
    server["auth_token"] = token
    server["auth_user_value"] = legacy_user_id
    server["import_spend_accrual_enabled"] = server.get("import_spend_accrual_enabled", 0)
    server["discount_stack_mode"] = server.get("discount_stack_mode", "exclusive") or "exclusive"
    server["discount_allowed_stack_types"] = (
        server.get("discount_allowed_stack_types", "cashback") or "cashback"
    )

    if api_type == "rixapi":
        server["supports_multi_group"] = 1
        if not server["manual_groups"] and "," in server.get("default_group", ""):
            server["manual_groups"] = server.get("default_group", "")
        server["auth_type"] = "header"
        server["auth_user_header"] = "rix-api-user"
    elif api_type == "newapi":
        if not server["manual_groups"] and "," in server.get("default_group", ""):
            server["manual_groups"] = server.get("default_group", "")
        server["auth_type"] = "header"
        server["auth_user_header"] = "new-api-user"
    else:
        server["auth_type"] = server.get("auth_type", "header") or "header"
        server["auth_user_header"] = (
            server.get("auth_user_header", "new-api-user") or "new-api-user"
        )

    return server


async def _load_and_translate_groups(server: dict) -> list[dict]:
    groups = await _load_remote_groups(server)
    groups = await _translate_groups_for_server(groups, server)
    return _normalize_group_rows(groups)


async def _load_remote_groups(server: dict) -> list[dict]:
    client = get_api_client(server)
    return await client.get_groups(server)


async def _translate_groups_for_server(groups: list[dict], server: dict) -> list[dict]:
    """Translate group metadata when the AI translator is configured."""
    translator = await get_translator()
    if translator.is_configured:
        return await translator.translate_groups(groups, server.get("api_type", "newapi"))
    return groups


def _normalize_group_rows(groups: list[dict]) -> list[dict]:
    """Normalize group records into the shape expected by admin templates and APIs."""
    return [
        {
            "name": group.get("name", ""),
            "label_en": group.get("label_en") or group.get("name_en") or group.get("name", ""),
            "label_vi": group.get("label_vi") or group.get("name_vi") or group.get("name", ""),
            "ratio": group.get("ratio", 1.0),
            "desc": group.get("desc_en") or group.get("desc", ""),
            "category": group.get("category", "Other"),
        }
        for group in groups
    ]


@router.get("", response_class=HTMLResponse)
async def servers_list(request: Request):
    templates = get_templates()
    return templates.TemplateResponse(
        "servers.html",
        _server_page_context(request=request, servers=await _load_servers_for_page()),
    )


@router.post("/add")
async def servers_add(request: Request):
    form = await request.form()
    try:
        tiers = _parse_discount_tiers_json(form.get("discount_tiers_json"))
    except ValueError:
        return RedirectResponse("/servers?error=invalid_discount_tiers", status_code=303)

    server_id = await create_server(**_get_server_form_payload(form))
    await sync_server_pricing_version(server_id)
    await replace_server_discount_tiers(server_id, tiers)
    return RedirectResponse("/servers", status_code=303)


@router.get("/{server_id}/edit", response_class=HTMLResponse)
async def servers_edit_page(request: Request, server_id: Annotated[int, Path()]):
    edit_context = await _build_server_edit_context(server_id)
    if not edit_context:
        return _redirect_to_servers()

    templates = get_templates()
    return templates.TemplateResponse(
        "servers.html",
        _server_page_context(
            request=request,
            servers=await _load_servers_for_page(),
            editing=edit_context["editing"],
        ),
    )


@router.get("/{server_id}/edit-modal", response_class=HTMLResponse)
async def servers_edit_modal(request: Request, server_id: Annotated[int, Path()]) -> HTMLResponse:
    edit_context = await _build_server_edit_context(server_id)
    if not edit_context:
        return HTMLResponse("Server not found", status_code=404)

    templates = get_templates()
    return templates.TemplateResponse(
        "_server_edit_modal.html",
        {
            "request": request,
            **edit_context,
        },
    )


@router.post("/{server_id}/edit")
async def servers_edit_submit(request: Request, server_id: Annotated[int, Path()]):
    form = await request.form()
    try:
        tiers = _parse_discount_tiers_json(form.get("discount_tiers_json"))
    except ValueError:
        return RedirectResponse(f"/servers/{server_id}/edit?error=invalid_discount_tiers", status_code=303)
    payload = _get_server_form_payload(form)
    payload["is_active"] = 1 if form.get("is_active") else 0
    await update_server(server_id, **payload)
    await sync_server_pricing_version(server_id)
    await replace_server_discount_tiers(server_id, tiers)
    return _redirect_to_servers()


@router.post("/{server_id}/toggle-active")
async def servers_toggle_active(request: Request, server_id: Annotated[int, Path()]):
    server = await get_server_by_id(server_id)
    if not server:
        return _redirect_to_servers()

    form = await request.form()
    redirect_target = _resolve_redirect_target(
        form.get("next") or request.headers.get("referer"),
        "/servers",
    )
    await update_server(server_id, is_active=0 if server.get("is_active") else 1)
    return RedirectResponse(redirect_target, status_code=303)


@router.get("/{server_id}/delete")
async def servers_delete(server_id: Annotated[int, Path()]):
    await delete_server(server_id)
    return _redirect_to_servers()


@router.get("/{server_id}/groups", response_class=HTMLResponse)
async def servers_groups(request: Request, server_id: Annotated[int, Path()]):
    """Fetch groups from a server and show them in the admin UI."""
    server = await _get_server_or_redirect(server_id)
    if isinstance(server, RedirectResponse):
        return server

    templates = get_templates()
    return templates.TemplateResponse(
        "servers.html",
        await _build_groups_page_context(request, server),
    )


@router.post("/{server_id}/groups/refresh", response_class=HTMLResponse)
async def servers_groups_refresh(request: Request, server_id: Annotated[int, Path()]):
    """Refresh cached groups from remote server and reopen the config page."""
    server = await _get_server_or_redirect(server_id)
    if isinstance(server, RedirectResponse):
        return server

    groups_data, source = await _load_catalog_groups(server, force_refresh=True)
    flash_type = "success" if groups_data and source == "remote" else "warning"
    flash_message = (
        "Groups refreshed from remote server."
        if groups_data and source == "remote"
        else "Could not refresh remote groups. Showing the latest available data."
    )

    templates = get_templates()
    context = await _build_groups_page_context(request, server)
    context["group_flash_message"] = flash_message
    context["group_flash_type"] = flash_type
    return templates.TemplateResponse("servers.html", context)


@router.post("/{server_id}/groups/save", response_class=HTMLResponse)
async def servers_groups_save(request: Request, server_id: Annotated[int, Path()]):
    """Persist default group and optional manual override for a server."""
    server = await _get_server_or_redirect(server_id)
    if isinstance(server, RedirectResponse):
        return server

    form = await request.form()
    selected_groups = _split_group_names(_clean_str(form.get("default_group")))
    if not selected_groups:
        fallback_group = _clean_str(form.get("group_radio"))
        if fallback_group:
            selected_groups = [fallback_group]
    manual_groups = ",".join(_split_group_names(_clean_str(form.get("manual_groups"))))

    if _get_supports_multi_group(server):
        default_group = ",".join(selected_groups)
    else:
        default_group = selected_groups[0] if selected_groups else ""

    await update_server(
        server_id,
        default_group=default_group,
        manual_groups=manual_groups,
    )

    refreshed_server = await get_server_by_id(server_id)
    if not refreshed_server:
        return _redirect_to_servers()

    templates = get_templates()
    context = await _build_groups_page_context(request, refreshed_server)
    context["group_flash_message"] = "Group configuration saved."
    context["group_flash_type"] = "success"
    return templates.TemplateResponse("servers.html", context)


@router.get("/{server_id}/api/groups")
async def api_servers_groups(server_id: Annotated[int, Path()]):
    """Fetch groups from a server and return JSON."""
    server = await _get_server_or_json(server_id)
    if isinstance(server, JSONResponse):
        return server

    return JSONResponse(
        _build_groups_json_payload(server, await _resolve_groups_data(server))
    )


@router.post("/preview-groups")
async def preview_groups(request: Request):
    """Preview groups from unsaved form data."""
    form = await request.form()
    server = _get_server_form_payload(form)
    if not server.get("name"):
        server["name"] = "Preview Server"

    groups_data = await _resolve_groups_data(server)
    return JSONResponse(
        _build_groups_preview_payload(server, groups_data)
    )
