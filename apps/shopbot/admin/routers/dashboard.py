"""
admin/routers/dashboard.py - Dashboard statistics overview.
"""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import HTMLResponse

from admin.deps import get_templates, protected_router
from db.queries.orders import get_order_stats
from db.queries.servers import get_all_servers
from db.queries.users import count_users

router = protected_router(tags=["dashboard"])


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    stats = await get_order_stats()
    stats["total_users"] = await count_users()
    stats["servers"] = await get_all_servers()

    templates = get_templates()
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "stats": stats},
    )
