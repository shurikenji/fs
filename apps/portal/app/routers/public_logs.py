"""Public logs page — SSR shell, data loaded via API."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.deps import get_templates
from app.sanitizer import sanitize_server
from db.queries.servers import get_public_servers

router = APIRouter(tags=["public"])


@router.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request):
    templates = get_templates()
    servers = await get_public_servers("logs")
    public_servers = [sanitize_server(s).model_dump() for s in servers]
    return templates.TemplateResponse("logs.html", {
        "request": request,
        "servers": public_servers,
    })
