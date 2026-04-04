"""Public pricing page - SSR with Jinja2."""
from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from app.cache import fetch_pricing
from app.deps import get_templates
from app.public_pricing_cache import get_cached_public_pricing
from app.sanitizer import sanitize_server
from db.queries.servers import get_public_servers

router = APIRouter(tags=["public"])


@router.get("/pricing", response_class=HTMLResponse)
async def pricing_page(request: Request, server: str = Query("")):
    templates = get_templates()
    servers = await get_public_servers("pricing")

    selected_id = server
    selected_server = next((item for item in servers if item["id"] == selected_id), None) if server else None
    pricing = None

    # If the user did not explicitly choose a server, prefer the first enabled
    # source that actually has pricing models so the landing experience is not empty.
    if not selected_server:
        for candidate in servers:
            raw_pricing = await fetch_pricing(candidate["id"], allow_upstream=False)
            if not raw_pricing:
                continue
            candidate_public_pricing = await get_cached_public_pricing(
                raw_pricing,
                candidate,
            )
            if candidate_public_pricing.models:
                selected_server = candidate
                selected_id = str(candidate["id"])
                pricing = candidate_public_pricing
                break

    # Fallback to the requested server or the first enabled server even if empty.
    if not selected_server and servers:
        selected_server = servers[0]
        selected_id = str(selected_server["id"])

    if selected_server and pricing is None:
        raw_pricing = await fetch_pricing(str(selected_server["id"]), allow_upstream=False)
        if raw_pricing:
            pricing = await get_cached_public_pricing(
                raw_pricing,
                selected_server,
            )

    public_servers = [sanitize_server(item) for item in servers]
    return templates.TemplateResponse(
        "pricing.html",
        {
            "request": request,
            "servers": [item.model_dump() for item in public_servers],
            "selected_server_id": selected_id,
            "pricing": pricing.model_dump() if pricing else None,
            "model_count": len(pricing.models) if pricing else 0,
            "group_count": len(pricing.groups) if pricing else 0,
        },
    )
