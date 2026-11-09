"""
admin/routers/auth.py - Session-based login and logout for Shopbot admin.
IP-based throttling helps reduce brute-force attempts.
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from admin.deps import get_templates, verify_csrf
from admin.passwords import hash_password, verify_password
from db.database import open_write_transaction
from db.queries.settings import get_setting
from bot.config import settings

router = APIRouter(tags=["auth"])

_login_attempts: dict[str, dict] = {}
MAX_ATTEMPTS = 5
LOCKOUT_MINUTES = 5


@router.get(settings.admin_login_path, response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get("admin"):
        return RedirectResponse("/", status_code=303)
    templates = get_templates()
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "post_url": settings.admin_login_path},
    )


@router.post(settings.admin_login_path, dependencies=[Depends(verify_csrf)])
async def login_submit(request: Request):
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()

    if client_ip in _login_attempts:
        record = _login_attempts[client_ip]
        if record["lockout_until"] > now:
            remain = int((record["lockout_until"] - now) / 60) + 1
            templates = get_templates()
            return templates.TemplateResponse(
                "login.html",
                {
                    "request": request,
                    "error": f"This IP is temporarily locked. Try again in {remain} minute(s).",
                    "post_url": settings.admin_login_path,
                },
            )
        elif record["lockout_until"] != 0 and record["lockout_until"] < now:
            _login_attempts[client_ip] = {"attempts": 0, "lockout_until": 0}

    form = await request.form()
    password = form.get("password", "")

    saved_password = await get_setting("admin_password") or ""
    is_valid, needs_rehash = verify_password(password, saved_password)

    if is_valid:
        if needs_rehash:
            db = await open_write_transaction()
            try:
                cursor = await db.execute(
                    """UPDATE settings SET value = ?, updated_at = datetime('now', '+7 hours')
                       WHERE key = 'admin_password' AND value = ?""",
                    (hash_password(password), saved_password),
                )
                if cursor.rowcount != 1:
                    await db.rollback()
                    is_valid = False
                else:
                    await db.commit()
            except BaseException:
                await db.rollback()
                raise
            finally:
                await db.close()
    if is_valid:
        request.session.clear()
        request.session["admin"] = {"source": "password"}
        _login_attempts.pop(client_ip, None)
        return RedirectResponse("/", status_code=303)

    if client_ip not in _login_attempts:
        _login_attempts[client_ip] = {"attempts": 0, "lockout_until": 0}

    _login_attempts[client_ip]["attempts"] += 1
    if _login_attempts[client_ip]["attempts"] >= MAX_ATTEMPTS:
        _login_attempts[client_ip]["lockout_until"] = now + (LOCKOUT_MINUTES * 60)

    templates = get_templates()
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "error": "Incorrect admin password.",
            "post_url": settings.admin_login_path,
        },
    )


@router.post("/logout", dependencies=[Depends(verify_csrf)])
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(settings.admin_login_path, status_code=303)
