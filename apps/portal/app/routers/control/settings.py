"""Admin runtime settings for AI translation and automatic sync."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.config import get_settings
from app.deps import get_templates
from app.translation_service import test_ai_connection
from db.queries.settings import get_settings_dict, set_setting

router = APIRouter(prefix="/control/settings", tags=["admin"])

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

_EDITABLE_KEYS = (
    "ai_provider",
    "ai_api_key",
    "ai_model",
    "ai_base_url",
)


def _default_settings() -> dict[str, str]:
    settings = get_settings()
    return {
        "ai_provider": settings.ai_provider,
        "ai_api_key": settings.ai_api_key,
        "ai_model": settings.ai_model,
        "ai_base_url": settings.ai_base_url,
        "ai_enabled": "true" if settings.ai_enabled else "false",
        "auto_sync_enabled": "false",
        "auto_sync_interval_minutes": "15",
    }


@router.get("", response_class=HTMLResponse)
async def settings_page(request: Request):
    if not request.session.get("is_admin"):
        return RedirectResponse("/control/login", status_code=303)

    templates = get_templates()
    flash_message = "AI translation settings saved." if request.query_params.get("saved") == "1" else ""
    return templates.TemplateResponse(
        "control/settings.html",
        {
            "request": request,
            "flash_message": flash_message,
            "all_settings": await get_settings_dict(_default_settings()),
            "ai_providers": _AI_PROVIDERS,
            "ai_models": _AI_MODELS,
        },
    )


@router.post("/save")
async def settings_save(request: Request):
    if not request.session.get("is_admin"):
        return RedirectResponse("/control/login", status_code=303)

    form = await request.form()
    for key in _EDITABLE_KEYS:
        await set_setting(key, str(form.get(key, "")).strip())
    await set_setting("ai_enabled", "true" if form.get("ai_enabled") else "false")
    try:
        interval_minutes = int(str(form.get("auto_sync_interval_minutes", "15")).strip() or "15")
    except ValueError:
        interval_minutes = 15
    await set_setting("auto_sync_interval_minutes", str(max(1, interval_minutes)))
    await set_setting("auto_sync_enabled", "true" if form.get("auto_sync_enabled") else "false")
    return RedirectResponse("/control/settings?saved=1", status_code=303)


@router.post("/ai/test")
async def settings_ai_test(request: Request):
    if not request.session.get("is_admin"):
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=401)

    form = await request.form()
    success, message = await test_ai_connection(
        provider=str(form.get("provider", "")).strip(),
        api_key=str(form.get("api_key", "")).strip(),
        model=str(form.get("model", "")).strip(),
        base_url=str(form.get("base_url", "")).strip(),
    )
    status_code = 200 if success else 400
    return JSONResponse({"success": success, "message": message}, status_code=status_code)
