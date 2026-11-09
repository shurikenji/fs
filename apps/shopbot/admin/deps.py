"""
admin/deps.py - Shared helpers and dependencies for admin routers.
"""
from __future__ import annotations

import math
import secrets
from pathlib import Path
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from bot.config import settings
from bot.utils.formatting import (
    format_time_vn,
    format_vnd,
    status_emoji,
    status_text_vi,
)

_BASE_DIR = Path(__file__).resolve().parent
_templates: Optional[Jinja2Templates] = None


def get_templates() -> Jinja2Templates:
    """Return the singleton Jinja2 template environment for admin pages."""
    global _templates
    if _templates is None:
        _templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))
        _templates.env.globals["format_vnd"] = format_vnd
        _templates.env.globals["status_emoji"] = status_emoji
        _templates.env.globals["status_text_vi"] = status_text_vi
        _templates.env.globals["platform_admin_url"] = settings.platform_admin_url.rstrip("/")
        _templates.env.globals["csrf_token"] = csrf_token
        _templates.env.filters["time_vn"] = format_time_vn
    return _templates


def require_admin(request: Request) -> dict:
    """Ensure the current request has an authenticated admin session."""
    admin = request.session.get("admin")
    if not admin:
        raise HTTPException(
            status_code=303,
            headers={"Location": settings.admin_login_path},
        )
    return {"admin": True}


async def get_admin_or_redirect(request: Request) -> Optional[dict]:
    """Return the admin session payload when present."""
    return request.session.get("admin")


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


async def verify_csrf(request: Request) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    expected = request.session.get("csrf_token")
    provided = request.headers.get("x-csrf-token", "")
    if not provided:
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                payload = await request.json()
            except ValueError:
                payload = {}
            provided = str(payload.get("csrf_token") or "") if isinstance(payload, dict) else ""
        else:
            form = await request.form()
            provided = str(form.get("csrf_token") or "")
    if not isinstance(expected, str) or not provided or not secrets.compare_digest(provided.encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="CSRF validation failed")


def protected_router(*, prefix: str = "", tags: list[str] | None = None) -> APIRouter:
    """Create an admin router protected by the session dependency."""
    return APIRouter(
        prefix=prefix,
        tags=tags,
        dependencies=[Depends(require_admin), Depends(verify_csrf)],
    )


# Type aliases for dependencies (FastAPI best practices)
AdminDep = Annotated[dict, Depends(require_admin)]
TemplatesDep = Annotated[Jinja2Templates, Depends(get_templates)]


# ── Pagination helpers ─────────────────────────────────────────────────────────

def get_pagination_params(request: Request, default_per_page: int = 20) -> dict:
    """
    Extract common pagination parameters from request query string.
    
    Returns:
        dict with keys: page (int), offset (int), per_page (int), search (str)
    """
    page = int(request.query_params.get("page", 0))
    per_page = int(request.query_params.get("per_page", default_per_page))
    search = request.query_params.get("search", "")
    return {
        "page": page,
        "offset": page * per_page,
        "per_page": per_page,
        "search": search,
    }


def build_pagination_context(
    page: int,
    per_page: int,
    total: int,
    base_url: str,
    extra_params: dict | None = None,
) -> dict:
    """
    Build pagination context for templates.
    
    Args:
        page: Current page (0-indexed)
        per_page: Items per page
        total: Total number of items
        base_url: Base URL for pagination links
        extra_params: Additional query parameters
    
    Returns:
        dict with keys: page, total_pages, has_prev, has_next, prev_url, next_url
    """
    total_pages = max(1, math.ceil(total / per_page))
    page = max(0, min(page, total_pages - 1))
    
    params = "&".join(f"{k}={v}" for k, v in (extra_params or {}).items())
    separator = "&" if params else ""
    
    return {
        "page": page,
        "total_pages": total_pages,
        "has_prev": page > 0,
        "has_next": page < total_pages - 1,
        "prev_url": f"{base_url}?page={page - 1}{separator}{params}" if page > 0 else None,
        "next_url": f"{base_url}?page={page + 1}{separator}{params}" if page < total_pages - 1 else None,
    }
