"""Public proxy status view for the unified portal."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.deps import get_templates
from app.public_registry import load_public_proxy_status

router = APIRouter(tags=["public"])


@router.get("/status", response_class=HTMLResponse)
async def status_page(request: Request):
    templates = get_templates()
    statuses = await load_public_proxy_status()
    return templates.TemplateResponse(
        "status.html",
        {
            "request": request,
            "statuses": statuses,
            "healthy_count": len([item for item in statuses if item.get("status") == "active"]),
        },
    )
