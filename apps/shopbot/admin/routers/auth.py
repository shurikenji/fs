"""
admin/routers/auth.py - Session-based login and logout for Shopbot admin.
IP-based throttling helps reduce brute-force attempts.
"""
from __future__ import annotations

import hashlib
import time

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from admin.deps import get_templates
from db.queries.settings import get_setting
from bot.config import settings

router = APIRouter(tags=["auth"])

_login_attempts: dict[str, dict] = {}
MAX_ATTEMPTS = 5
LOCKOUT_MINUTES = 5


def _hash_password(raw_password: str) -> str:
    """Hash the password before comparison to avoid plaintext-only checks."""
    return hashlib.sha256(raw_password.encode("utf-8")).hexdigest()


@router.get(settings.admin_login_path, response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get("admin"):
        return RedirectResponse("/", status_code=303)
    templates = get_templates()
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "post_url": settings.admin_login_path},
    )


@router.post(settings.admin_login_path)
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

    saved_password = await get_setting("admin_password") or "admin123"

    hashed_input = _hash_password(password)
    is_valid = (password == saved_password) or (hashed_input == saved_password)

    if is_valid:
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


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(settings.admin_login_path, status_code=303)
