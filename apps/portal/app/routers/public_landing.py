"""Public landing page for the customer-facing Shupremium portal."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.deps import get_templates
from app.public_registry import load_public_balance_sources
from db.queries.servers import get_public_servers

router = APIRouter(tags=["public"])


@router.get("/", response_class=HTMLResponse)
async def landing_page(request: Request):
    templates = get_templates()
    pricing_servers = await get_public_servers("pricing")
    balance_sources = await load_public_balance_sources()
    return templates.TemplateResponse(
        "landing.html",
        {
            "request": request,
            "server_count": len(pricing_servers),
            "balance_source_count": len(balance_sources),
            "featured_servers": pricing_servers[:4],
        },
    )
