"""Pricing admin routes for platform-control."""
from __future__ import annotations

import json
from typing import Any

from fastapi import Depends, FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.config import get_settings
from app.deps import get_templates, verify_csrf
from app.pricing_hub_client import (
    pricing_get_groups,
    pricing_get_latest_sync_runs,
    pricing_get_models,
    pricing_get_settings,
    pricing_get_sync_runs,
    pricing_import_control_plane,
    pricing_refresh_groups,
    pricing_sync_source,
    pricing_test_ai,
)
from app.security import require_control_plane_token
from db.queries import (
    create_activity_log,
    create_pricing_sync_run,
    delete_service_source,
    get_internal_balance_sources,
    get_latest_pricing_sync_map,
    get_pricing_runtime_settings,
    get_pricing_sync_runs,
    get_service_source,
    get_service_sources,
    set_pricing_runtime_settings,
    upsert_service_source,
)

_AI_PROVIDERS = [
    {"value": "openai", "label": "OpenAI"},
    {"value": "openai_compatible", "label": "OpenAI Compatible"},
    {"value": "anthropic", "label": "Anthropic"},
    {"value": "gemini", "label": "Gemini"},
]

_AI_MODELS = {
    "openai": ["gpt-4o-mini", "gpt-4.1-mini", "gpt-4.1"],
    "openai_compatible": ["gpt-4o-mini", "gpt-4.1-mini", "llama3.1:8b"],
    "anthropic": ["claude-3-5-sonnet-latest", "claude-3-7-sonnet-latest"],
    "gemini": ["gemini-2.0-flash", "gemini-1.5-pro"],
}

_PRICING_SETTINGS_DEFAULTS = {
    "ai_provider": "openai",
    "ai_api_key": "",
    "ai_model": "gpt-4o-mini",
    "ai_base_url": "",
    "ai_enabled": "false",
    "auto_sync_enabled": "false",
    "auto_sync_interval_minutes": "15",
}

_SERVER_TYPES = [
    {"value": "newapi", "label": "NewAPI Standard"},
    {"value": "rixapi", "label": "RixAPI (Inline Ratio)"},
    {"value": "custom", "label": "Custom Manual"},
]

_AUTH_MODES = [
    {"value": "header", "label": "Header + Bearer"},
    {"value": "bearer", "label": "Bearer only"},
    {"value": "cookie", "label": "Cookie"},
    {"value": "none", "label": "None"},
]


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def _client_ip(request: Request) -> str:
    return request.headers.get("x-forwarded-for", request.client.host if request.client else "unknown").split(",")[0].strip()


def _require_admin(request: Request) -> RedirectResponse | None:
    if not request.session.get("is_admin"):
        return _redirect("/control/login")
    return None


async def _require_admin_post(request: Request) -> RedirectResponse | None:
    redirect = _require_admin(request)
    if redirect:
        return redirect
    await verify_csrf(request)
    return None


def _dump_names(items: list[str]) -> str:
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = str(item or "").strip()
        if value and value not in seen:
            cleaned.append(value)
            seen.add(value)
    return json.dumps(cleaned, ensure_ascii=False)


def _parse_names(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        items = raw
    else:
        text = str(raw).strip()
        if not text:
            return []
        try:
            decoded = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            decoded = [part.strip() for part in text.split(",")]
        items = decoded if isinstance(decoded, list) else []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = str(item or "").strip()
        if value and value not in seen:
            cleaned.append(value)
            seen.add(value)
    return cleaned


def _source_name_map(sources: list[dict[str, Any]]) -> dict[str, str]:
    return {
        str(source.get("id") or "").strip(): str(source.get("name") or source.get("id") or "").strip()
        for source in sources
        if str(source.get("id") or "").strip()
    }


def _normalize_runtime_run(row: dict[str, Any], source_names: dict[str, str]) -> dict[str, Any]:
    source_id = str(row.get("source_id") or "").strip()
    return {
        "id": row.get("id"),
        "source_id": source_id,
        "source_name": source_names.get(source_id, source_id),
        "origin": "runtime",
        "status": str(row.get("status") or "").strip(),
        "trigger": str(row.get("trigger") or "manual").strip(),
        "model_count": int(row.get("model_count") or 0),
        "group_count": int(row.get("group_count") or 0),
        "translated_count": None,
        "duration_ms": int(row.get("duration_ms") or 0),
        "error_message": str(row.get("error_message") or "").strip(),
        "created_at": str(row.get("created_at") or "").strip(),
    }


def _normalize_control_run(row: dict[str, Any], source_names: dict[str, str]) -> dict[str, Any]:
    source_id = str(row.get("source_id") or "").strip()
    return {
        "id": row.get("id"),
        "source_id": source_id,
        "source_name": source_names.get(source_id, source_id),
        "origin": "control-plane",
        "status": str(row.get("status") or "").strip(),
        "trigger": str(row.get("trigger") or "manual").strip(),
        "model_count": int(row.get("model_count") or 0),
        "group_count": int(row.get("group_count") or 0),
        "translated_count": int(row.get("translated_count")) if row.get("translated_count") is not None else None,
        "duration_ms": int(row.get("duration_ms") or 0),
        "error_message": str(row.get("error_message") or "").strip(),
        "created_at": str(row.get("created_at") or "").strip(),
    }


def _sort_sync_runs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda item: (
            str(item.get("created_at") or ""),
            int(item.get("id") or 0),
            str(item.get("source_id") or ""),
        ),
        reverse=True,
    )


async def _load_runtime_sync_state(
    *,
    source_id: str | None = None,
    status: str | None = None,
    trigger: str | None = None,
    limit: int = 200,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], str]:
    try:
        runs_payload = await pricing_get_sync_runs(
            source_id=source_id,
            status=status,
            trigger=trigger,
            limit=limit,
        )
        latest_payload = await pricing_get_latest_sync_runs()
    except Exception as exc:
        return [], {}, str(exc)

    runs = runs_payload.get("runs", []) if isinstance(runs_payload, dict) else []
    latest = latest_payload.get("latest", {}) if isinstance(latest_payload, dict) else {}
    runtime_runs = [row for row in runs if isinstance(row, dict)]
    runtime_latest = {
        str(source_key): value
        for source_key, value in latest.items()
        if isinstance(value, dict)
    }
    return runtime_runs, runtime_latest, ""


async def _import_runtime_registry(*, request: Request | None = None) -> dict[str, Any]:
    result = await pricing_import_control_plane()
    if request is not None:
        ip = _client_ip(request)
        await create_activity_log("PRICING_IMPORT", f"Push control-plane registry to pricing runtime ({result})", ip)
    return result


async def _sync_one_source(source_id: str, *, trigger: str) -> dict[str, Any]:
    result = await pricing_sync_source(source_id, trigger=trigger)
    await create_pricing_sync_run(
        source_id,
        trigger=trigger,
        status="success" if result.get("success") else "failed",
        model_count=int(result.get("models") or 0),
        group_count=int(result.get("groups") or 0),
        translated_count=int(result.get("translations") or 0),
        duration_ms=int(result.get("duration_ms") or 0),
        error_message=str(result.get("error") or ""),
    )
    return result


def register_pricing_admin_routes(app: FastAPI) -> None:
    @app.get("/api/internal/balance-sources", dependencies=[Depends(require_control_plane_token)])
    async def internal_balance_sources():
        return {"servers": await get_internal_balance_sources()}

    @app.get("/api/internal/pricing-runtime-settings", dependencies=[Depends(require_control_plane_token)])
    async def internal_pricing_runtime_settings():
        return {"settings": await get_pricing_runtime_settings(_PRICING_SETTINGS_DEFAULTS)}

    @app.get("/control/pricing/sources", response_class=HTMLResponse)
    async def pricing_sources_page(request: Request, edit: str = Query(default="")):
        redirect = _require_admin(request)
        if redirect:
            return redirect
        templates = get_templates()
        sources = await get_service_sources(enabled_only=False)
        source_form = await get_service_source(edit) if edit else None
        local_latest_sync_map = await get_latest_pricing_sync_map()
        _, runtime_latest_sync_map, runtime_error = await _load_runtime_sync_state(limit=200)
        source_names = _source_name_map(sources)
        latest_sync_map: dict[str, dict[str, Any]] = {}
        for source in sources:
            source_id = str(source.get("id") or "").strip()
            runtime_row = runtime_latest_sync_map.get(source_id)
            local_row = local_latest_sync_map.get(source_id)
            if runtime_row:
                latest_sync_map[source_id] = _normalize_runtime_run(runtime_row, source_names)
            elif local_row:
                latest_sync_map[source_id] = _normalize_control_run(local_row, source_names)
        return templates.TemplateResponse(
            "pricing_sources.html",
            {
                "request": request,
                "sources": sources,
                "source_form": source_form,
                "latest_sync_map": latest_sync_map,
                "server_types": _SERVER_TYPES,
                "auth_modes": _AUTH_MODES,
                "runtime_sync_warning": runtime_error,
                "flash_message": request.session.pop("flash_message", ""),
                "flash_error": request.session.pop("flash_error", ""),
            },
        )

    @app.post("/control/pricing/sources/save")
    async def pricing_sources_save(
        request: Request,
        source_id: str = Form(...),
        name: str = Form(...),
        upstream_base_url: str = Form(...),
        public_base_url: str = Form(""),
        source_type: str = Form("newapi"),
        enabled: str | None = Form(default=None),
        sort_order: int = Form(0),
        quota_multiple: float = Form(1.0),
        supports_group_chain: str | None = Form(default=None),
        ratio_config_enabled: str | None = Form(default=None),
        public_pricing_enabled: str | None = Form(default=None),
        public_balance_enabled: str | None = Form(default=None),
        public_keys_enabled: str | None = Form(default=None),
        public_logs_enabled: str | None = Form(default=None),
        balance_rate: float = Form(1.0),
        auth_mode: str = Form("header"),
        auth_user_header: str = Form(""),
        auth_user_value: str = Form(""),
        auth_token: str = Form(""),
        auth_cookie: str = Form(""),
        pricing_path: str = Form("/api/pricing"),
        ratio_config_path: str = Form("/api/ratio_config"),
        log_path: str = Form("/api/log/self"),
        token_search_path: str = Form("/api/token/search"),
        groups_path: str = Form(""),
        manual_groups: str = Form(""),
        hidden_groups: str = Form("[]"),
        excluded_models: str = Form("[]"),
        notes: str = Form(""),
    ):
        redirect = await _require_admin_post(request)
        if redirect:
            return redirect
        ip = _client_ip(request)
        await upsert_service_source(
            source_id.strip(),
            name=name.strip(),
            upstream_base_url=upstream_base_url.strip(),
            public_base_url=public_base_url.strip(),
            source_type=source_type.strip() or "newapi",
            enabled=1 if enabled else 0,
            sort_order=sort_order,
            quota_multiple=quota_multiple,
            supports_group_chain=1 if supports_group_chain else 0,
            ratio_config_enabled=1 if ratio_config_enabled else 0,
            public_pricing_enabled=1 if public_pricing_enabled else 0,
            public_balance_enabled=1 if public_balance_enabled else 0,
            public_keys_enabled=1 if public_keys_enabled else 0,
            public_logs_enabled=1 if public_logs_enabled else 0,
            balance_rate=balance_rate,
            auth_mode=auth_mode.strip() or "header",
            auth_user_header=auth_user_header.strip(),
            auth_user_value=auth_user_value.strip(),
            auth_token=auth_token.strip(),
            auth_cookie=auth_cookie.strip(),
            pricing_path=pricing_path.strip(),
            ratio_config_path=ratio_config_path.strip(),
            log_path=log_path.strip(),
            token_search_path=token_search_path.strip(),
            groups_path=groups_path.strip(),
            manual_groups=manual_groups.strip(),
            hidden_groups=_dump_names(_parse_names(hidden_groups)),
            excluded_models=_dump_names(_parse_names(excluded_models)),
            notes=notes.strip(),
        )
        await create_activity_log("SAVE_PRICING_SOURCE", f"Luu pricing source: {source_id.strip()}", ip)
        try:
            result = await _import_runtime_registry(request=request)
            request.session["flash_message"] = f"Da luu source {source_id.strip()} va push runtime ({result.get('sources_imported', 0)} sources)."
        except Exception as exc:
            request.session["flash_error"] = f"Source da luu nhung pricing runtime chua import duoc: {exc}"
        return _redirect(f"/control/pricing/sources?edit={source_id.strip()}")

    @app.post("/control/pricing/sources/delete")
    async def pricing_sources_delete(request: Request, source_id: str = Form(...)):
        redirect = await _require_admin_post(request)
        if redirect:
            return redirect
        ip = _client_ip(request)
        await delete_service_source(source_id)
        await create_activity_log("DELETE_PRICING_SOURCE", f"Xoa pricing source: {source_id}", ip)
        try:
            await _import_runtime_registry(request=request)
            request.session["flash_message"] = f"Da xoa source {source_id} va dong bo runtime."
        except Exception as exc:
            request.session["flash_error"] = f"Source da xoa nhung pricing runtime chua import duoc: {exc}"
        return _redirect("/control/pricing/sources")

    @app.post("/control/pricing/sources/import-runtime")
    async def pricing_sources_import_runtime(request: Request):
        redirect = await _require_admin_post(request)
        if redirect:
            return redirect
        try:
            result = await _import_runtime_registry(request=request)
            request.session["flash_message"] = f"Pricing runtime imported {result.get('sources_imported', 0)} sources."
        except Exception as exc:
            request.session["flash_error"] = f"Import pricing runtime loi: {exc}"
        return _redirect("/control/pricing/sources")

    @app.post("/control/pricing/sources/sync-all")
    async def pricing_sources_sync_all(request: Request):
        redirect = await _require_admin_post(request)
        if redirect:
            return redirect
        ip = _client_ip(request)
        try:
            await _import_runtime_registry(request=request)
            sources = await get_service_sources(enabled_only=True)
            success_count = 0
            for source in sources:
                result = await _sync_one_source(str(source["id"]), trigger="manual")
                success_count += 1 if result.get("success") else 0
            await create_activity_log("SYNC_ALL_PRICING", f"Sync all pricing sources: {success_count}/{len(sources)}", ip)
            request.session["flash_message"] = f"Da sync {success_count}/{len(sources)} pricing sources."
        except Exception as exc:
            request.session["flash_error"] = f"Sync all pricing loi: {exc}"
        return _redirect("/control/pricing/sources")

    @app.post("/control/pricing/sources/{source_id}/sync")
    async def pricing_source_sync(request: Request, source_id: str):
        redirect = await _require_admin_post(request)
        if redirect:
            return redirect
        ip = _client_ip(request)
        try:
            await _import_runtime_registry(request=request)
            result = await _sync_one_source(source_id, trigger="manual")
            await create_activity_log("SYNC_PRICING_SOURCE", f"Sync pricing source {source_id}: {result}", ip)
            request.session["flash_message"] = (
                f"Sync {source_id} thanh cong: {result.get('models', 0)} models, "
                f"{result.get('groups', 0)} groups, {result.get('translations', 0)} translations."
            )
        except Exception as exc:
            await create_pricing_sync_run(source_id, trigger="manual", status="failed", error_message=str(exc))
            request.session["flash_error"] = f"Sync {source_id} loi: {exc}"
        return _redirect("/control/pricing/sources")

    @app.get("/control/pricing/sources/{source_id}/groups", response_class=HTMLResponse)
    async def pricing_source_groups_page(request: Request, source_id: str):
        redirect = _require_admin(request)
        if redirect:
            return redirect
        source = await get_service_source(source_id)
        if not source:
            request.session["flash_error"] = "Pricing source khong ton tai."
            return _redirect("/control/pricing/sources")
        templates = get_templates()
        groups_payload = await pricing_get_groups(source_id)
        return templates.TemplateResponse(
            "pricing_groups.html",
            {
                "request": request,
                "source": source,
                "groups_data": groups_payload.get("groups", []),
                "visible_groups": groups_payload.get("visible_groups", []),
                "source_label": groups_payload.get("source_label", "Runtime catalog"),
                "hidden_group_count": len(_parse_names(source.get("hidden_groups"))),
                "flash_message": request.session.pop("flash_message", ""),
                "flash_error": request.session.pop("flash_error", ""),
            },
        )

    @app.post("/control/pricing/sources/{source_id}/groups/refresh")
    async def pricing_source_groups_refresh(request: Request, source_id: str):
        redirect = await _require_admin_post(request)
        if redirect:
            return redirect
        try:
            await pricing_refresh_groups(source_id)
            request.session["flash_message"] = f"Da refresh group catalog cho {source_id}."
        except Exception as exc:
            request.session["flash_error"] = f"Refresh groups loi: {exc}"
        return _redirect(f"/control/pricing/sources/{source_id}/groups")

    @app.post("/control/pricing/sources/{source_id}/groups/save")
    async def pricing_source_groups_save(request: Request, source_id: str):
        redirect = await _require_admin_post(request)
        if redirect:
            return redirect
        source = await get_service_source(source_id)
        if not source:
            request.session["flash_error"] = "Pricing source khong ton tai."
            return _redirect("/control/pricing/sources")
        form = await request.form()
        current_catalog = await pricing_get_groups(source_id)
        catalog_names = [
            str(group.get("name") or "").strip()
            for group in current_catalog.get("groups", [])
            if str(group.get("name") or "").strip()
        ]
        visible_groups = set(_parse_names(form.getlist("visible_groups")))
        hidden_groups = [name for name in catalog_names if name not in visible_groups]
        await upsert_service_source(
            source_id,
            hidden_groups=_dump_names(hidden_groups),
        )
        await _import_runtime_registry(request=request)
        request.session["flash_message"] = f"Da cap nhat group visibility cho {source_id}."
        return _redirect(f"/control/pricing/sources/{source_id}/groups")

    @app.get("/control/pricing/sources/{source_id}/models", response_class=HTMLResponse)
    async def pricing_source_models_page(request: Request, source_id: str):
        redirect = _require_admin(request)
        if redirect:
            return redirect
        source = await get_service_source(source_id)
        if not source:
            request.session["flash_error"] = "Pricing source khong ton tai."
            return _redirect("/control/pricing/sources")
        templates = get_templates()
        models_payload = await pricing_get_models(source_id)
        return templates.TemplateResponse(
            "pricing_models.html",
            {
                "request": request,
                "source": source,
                "models_data": models_payload.get("models", []),
                "visible_models": models_payload.get("visible_models", []),
                "excluded_model_count": len(_parse_names(source.get("excluded_models"))),
                "flash_message": request.session.pop("flash_message", ""),
                "flash_error": request.session.pop("flash_error", ""),
            },
        )

    @app.post("/control/pricing/sources/{source_id}/models/save")
    async def pricing_source_models_save(request: Request, source_id: str):
        redirect = await _require_admin_post(request)
        if redirect:
            return redirect
        source = await get_service_source(source_id)
        if not source:
            request.session["flash_error"] = "Pricing source khong ton tai."
            return _redirect("/control/pricing/sources")
        form = await request.form()
        current_catalog = await pricing_get_models(source_id)
        catalog_names = [
            str(model.get("model_name") or "").strip()
            for model in current_catalog.get("models", [])
            if str(model.get("model_name") or "").strip()
        ]
        visible_models = set(_parse_names(form.getlist("visible_models")))
        excluded_models = [name for name in catalog_names if name not in visible_models]
        await upsert_service_source(
            source_id,
            excluded_models=_dump_names(excluded_models),
        )
        await _import_runtime_registry(request=request)
        request.session["flash_message"] = f"Da cap nhat model visibility cho {source_id}."
        return _redirect(f"/control/pricing/sources/{source_id}/models")

    @app.get("/control/pricing/settings", response_class=HTMLResponse)
    async def pricing_settings_page(request: Request):
        redirect = _require_admin(request)
        if redirect:
            return redirect
        templates = get_templates()
        runtime_settings = await get_pricing_runtime_settings(_PRICING_SETTINGS_DEFAULTS)
        try:
            runtime_state = await pricing_get_settings()
        except Exception as exc:
            runtime_state = {"error": str(exc)}
        return templates.TemplateResponse(
            "pricing_settings.html",
            {
                "request": request,
                "all_settings": runtime_settings,
                "runtime_state": runtime_state,
                "ai_providers": _AI_PROVIDERS,
                "ai_models": _AI_MODELS,
                "flash_message": request.session.pop("flash_message", ""),
                "flash_error": request.session.pop("flash_error", ""),
            },
        )

    @app.post("/control/pricing/settings/save")
    async def pricing_settings_save(
        request: Request,
        ai_provider: str = Form("openai"),
        ai_api_key: str = Form(""),
        ai_model: str = Form("gpt-4o-mini"),
        ai_base_url: str = Form(""),
        ai_enabled: str | None = Form(default=None),
        auto_sync_enabled: str | None = Form(default=None),
        auto_sync_interval_minutes: int = Form(15),
    ):
        redirect = await _require_admin_post(request)
        if redirect:
            return redirect
        ip = _client_ip(request)
        await set_pricing_runtime_settings(
            {
                "ai_provider": ai_provider.strip() or "openai",
                "ai_api_key": ai_api_key.strip(),
                "ai_model": ai_model.strip(),
                "ai_base_url": ai_base_url.strip(),
                "ai_enabled": "true" if ai_enabled else "false",
                "auto_sync_enabled": "true" if auto_sync_enabled else "false",
                "auto_sync_interval_minutes": str(max(1, auto_sync_interval_minutes)),
            }
        )
        await create_activity_log("SAVE_PRICING_SETTINGS", "Cap nhat pricing runtime settings", ip)
        try:
            result = await _import_runtime_registry(request=request)
            request.session["flash_message"] = f"Da luu pricing settings va import runtime ({result.get('settings_imported', 0)} settings)."
        except Exception as exc:
            request.session["flash_error"] = f"Pricing settings da luu nhung runtime chua import duoc: {exc}"
        return _redirect("/control/pricing/settings")

    @app.post("/control/pricing/settings/ai/test")
    async def pricing_settings_ai_test(
        request: Request,
        ai_provider: str = Form("openai"),
        ai_api_key: str = Form(""),
        ai_model: str = Form("gpt-4o-mini"),
        ai_base_url: str = Form(""),
    ):
        redirect = await _require_admin_post(request)
        if redirect:
            return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=401)
        try:
            result = await pricing_test_ai(
                {
                    "provider": ai_provider.strip(),
                    "api_key": ai_api_key.strip(),
                    "model": ai_model.strip(),
                    "base_url": ai_base_url.strip(),
                }
            )
            return JSONResponse(result, status_code=200 if result.get("success") else 400)
        except Exception as exc:
            return JSONResponse({"success": False, "message": str(exc)}, status_code=502)

    @app.get("/control/pricing/sync-runs", response_class=HTMLResponse)
    async def pricing_sync_runs_page(
        request: Request,
        source_id: str = Query(default=""),
        status: str = Query(default=""),
        trigger: str = Query(default=""),
        origin: str = Query(default=""),
    ):
        redirect = _require_admin(request)
        if redirect:
            return redirect
        templates = get_templates()
        sources = await get_service_sources(enabled_only=False)
        source_names = _source_name_map(sources)
        local_runs = await get_pricing_sync_runs(
            source_id=source_id or None,
            status=status or None,
            trigger=trigger or None,
            limit=200,
        )
        runtime_runs, _, runtime_error = await _load_runtime_sync_state(
            source_id=source_id or None,
            status=status or None,
            trigger=trigger or None,
            limit=200,
        )
        unified_runs = [
            *[_normalize_runtime_run(row, source_names) for row in runtime_runs],
            *[_normalize_control_run(row, source_names) for row in local_runs],
        ]
        if origin:
            unified_runs = [row for row in unified_runs if row["origin"] == origin]
        runs = _sort_sync_runs(unified_runs)[:200]
        return templates.TemplateResponse(
            "pricing_sync_runs.html",
            {
                "request": request,
                "runs": runs,
                "sources": sources,
                "source_id": source_id,
                "status": status,
                "trigger": trigger,
                "origin": origin,
                "runtime_sync_warning": runtime_error,
                "flash_message": request.session.pop("flash_message", ""),
                "flash_error": request.session.pop("flash_error", ""),
            },
        )
