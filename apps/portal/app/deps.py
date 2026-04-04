"""Shared dependencies: templates, admin auth guard."""
from __future__ import annotations

from pathlib import Path
from functools import lru_cache

from fastapi import Request, HTTPException
from fastapi.templating import Jinja2Templates

from app.config import get_settings

_BASE_DIR = Path(__file__).resolve().parent.parent
_TEMPLATES_DIR = _BASE_DIR / "templates"


@lru_cache
def get_templates() -> Jinja2Templates:
    return Jinja2Templates(directory=str(_TEMPLATES_DIR))


def require_admin(request: Request) -> None:
    """Raise 401 if the session is not authenticated as admin."""
    if not request.session.get("is_admin"):
        raise HTTPException(status_code=401, detail="Unauthorized")
