"""Shared dependencies for platform-control."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import secrets

from fastapi import HTTPException, Request
from fastapi.templating import Jinja2Templates

_BASE_DIR = Path(__file__).resolve().parent.parent


@lru_cache
def get_templates() -> Jinja2Templates:
    templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))
    templates.env.globals["csrf_token"] = csrf_token
    return templates


def require_admin(request: Request) -> None:
    if not request.session.get("is_admin"):
        raise HTTPException(status_code=401, detail="Unauthorized")


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


async def verify_csrf(request: Request) -> None:
    expected = csrf_token(request)
    provided = request.headers.get("x-csrf-token", "").strip()
    if not provided:
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                payload = await request.json()
            except Exception:
                payload = {}
            if isinstance(payload, dict):
                provided = str(payload.get("csrf_token") or "").strip()
        else:
            form = await request.form()
            provided = str(form.get("csrf_token") or "").strip()
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
