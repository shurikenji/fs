"""
admin/routers/broadcast.py - Broadcast messages to all users.
"""
from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

from admin.deps import get_templates, protected_router
from bot.services.notifier import broadcast_text
from db.queries.logs import add_log
from db.queries.users import count_users, get_all_user_telegram_ids

logger = logging.getLogger(__name__)

router = protected_router(prefix="/broadcast", tags=["broadcast"])


@router.get("", response_class=HTMLResponse)
async def broadcast_page(request: Request):
    templates = get_templates()
    return templates.TemplateResponse(
        "broadcast.html",
        {"request": request, "total_users": await count_users()},
    )


@router.post("/send")
async def broadcast_send(request: Request):
    form = await request.form()
    message = form.get("message", "").strip()
    if not message:
        return RedirectResponse("/broadcast", status_code=303)

    try:
        sent, failed = await broadcast_text(await get_all_user_telegram_ids(), message)
        await add_log(
            f"Broadcast sent: {sent} success, {failed} failed",
            module="broadcast",
        )
    except Exception as exc:
        logger.error("Broadcast error: %s", exc)
        await add_log(f"Broadcast error: {exc}", level="error", module="broadcast")

    return RedirectResponse("/broadcast", status_code=303)
