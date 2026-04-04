"""Admin authentication and dashboard routes."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import get_settings
from app.deps import get_templates
from app.sync_service import refresh_server_snapshot
from db.queries.servers import get_enabled_servers, get_recent_sync_logs
from db.queries.translations import count_cached_translations

router = APIRouter(prefix="/control", tags=["admin"])


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    templates = get_templates()
    return templates.TemplateResponse(
        "control/login.html",
        {
            "request": request,
            "error": "",
        },
    )


@router.post("/login")
async def login_submit(request: Request):
    form = await request.form()
    secret = str(form.get("secret", "")).strip()
    settings = get_settings()

    if secret == settings.admin_secret:
        request.session["is_admin"] = True
        return RedirectResponse("/control", status_code=303)

    templates = get_templates()
    return templates.TemplateResponse(
        "control/login.html",
        {
            "request": request,
            "error": "Invalid secret.",
        },
    )


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/control/login", status_code=303)


@router.post("/translations/refresh")
async def refresh_translations(request: Request):
    if not request.session.get("is_admin"):
        return RedirectResponse("/control/login", status_code=303)

    total_written = 0
    for server in await get_enabled_servers():
        result = await refresh_server_snapshot(str(server["id"]), trigger="manual")
        total_written += result.translated_count

    request.session["flash_message"] = f"Translation refresh completed. {total_written} cache entries updated."
    return RedirectResponse("/control", status_code=303)


@router.get("", response_class=HTMLResponse)
async def control_dashboard(request: Request):
    if not request.session.get("is_admin"):
        return RedirectResponse("/control/login", status_code=303)

    templates = get_templates()
    servers = await get_enabled_servers()
    recent_sync_logs = await get_recent_sync_logs(8)
    flash_message = request.session.pop("flash_message", "")

    return templates.TemplateResponse(
        "control/dashboard.html",
        {
            "request": request,
            "flash_message": flash_message,
            "enabled_server_count": len(servers),
            "cached_translation_count": await count_cached_translations(),
            "recent_sync_logs": recent_sync_logs,
        },
    )
