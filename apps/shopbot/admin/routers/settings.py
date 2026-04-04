"""
admin/routers/settings.py - Admin settings routes.
"""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from admin.deps import get_templates, protected_router
from bot.services.ai_translator import AITranslator
from db.queries.settings import get_settings_dict, set_setting

router = protected_router(prefix="/settings", tags=["settings"])

_EDITABLE_KEYS = [
    "mb_api_url",
    "mb_api_key",
    "mb_username",
    "mb_password",
    "mb_account_no",
    "mb_account_name",
    "mb_bank_id",
    "poll_interval",
    "key_alert_poll_interval_min",
    "key_alert_thresholds",
    "order_expire_min",
    "vietqr_template",
    "bot_name",
    "bot_description",
    "welcome_message",
    "support_url",
    "support_text",
    "pagination_size",
    "admin_telegram_ids",
    "admin_password",
    "admin_notify_enabled",
    "admin_notify_order_completed",
    "admin_notify_service_paid",
    "admin_notify_service_completed",
    "admin_notify_order_refunded",
    "key_alert_enabled",
    "msg_key_new",
    "msg_key_topup",
    "msg_chatgpt",
    "msg_wallet_topup",
    "ai_provider",
    "ai_api_key",
    "ai_model",
    "ai_base_url",
]

_AI_PROVIDERS = [
    {"value": "openai", "label": "OpenAI"},
    {"value": "openai_compatible", "label": "Tương thích OpenAI (Ollama, LM Studio...)"},
    {"value": "anthropic", "label": "Anthropic"},
    {"value": "gemini", "label": "Google Gemini"},
]

_AI_MODELS = {
    "openai": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
    "openai_compatible": ["llama3", "mistral", "qwen", "phi3", "gemma"],
    "anthropic": [
        "claude-sonnet-4-20250514",
        "claude-opus-4-20250514",
        "claude-3-5-sonnet-20241022",
    ],
    "gemini": ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
}


@router.get("", response_class=HTMLResponse)
async def settings_page(request: Request):
    flash_message = "Đã lưu cài đặt thành công." if request.query_params.get("saved") == "1" else None
    templates = get_templates()
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "all_settings": await get_settings_dict(),
            "ai_providers": _AI_PROVIDERS,
            "ai_models": _AI_MODELS,
            "flash_message": flash_message,
            "flash_type": "success" if flash_message else None,
        },
    )


@router.post("/save")
async def settings_save(request: Request):
    form = await request.form()
    for key in _EDITABLE_KEYS:
        value = form.get(key)
        if value is not None:
            await set_setting(key, value)
    await set_setting("ai_enabled", "true" if form.get("ai_enabled") else "false")
    for key in (
        "admin_notify_enabled",
        "admin_notify_order_completed",
        "admin_notify_service_paid",
        "admin_notify_service_completed",
        "admin_notify_order_refunded",
        "key_alert_enabled",
    ):
        await set_setting(key, "true" if form.get(key) else "false")
    return RedirectResponse("/settings?saved=1", status_code=303)


@router.post("/ai/test")
async def test_ai_connection(request: Request):
    """Test AI connection."""
    form = await request.form()
    translator = AITranslator()
    translator.api_key = form.get("api_key", "")
    translator.provider = form.get("provider", "openai")
    translator.model = form.get("model", "gpt-4o-mini")
    translator.base_url = form.get("base_url", "")
    translator.enabled = True

    success, message = await translator.test_connection()
    return JSONResponse({"success": success, "message": message})
