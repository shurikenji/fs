"""
admin/routers/users.py - User management routes.
"""
from __future__ import annotations

import math
from typing import Annotated

from fastapi import Path, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from admin.deps import get_templates, protected_router
from db.queries.orders import get_orders_by_user
from db.queries.users import (
    count_users,
    get_all_users,
    get_user_by_id,
    set_admin,
    set_banned,
    set_discount_disabled,
)
from db.queries.wallets import add_balance, ensure_wallet

router = protected_router(prefix="/users", tags=["users"])


@router.get("", response_class=HTMLResponse)
async def users_list(request: Request) -> HTMLResponse:
    page = int(request.query_params.get("page", 0))
    search = request.query_params.get("search", "")
    per_page = 20

    users = await get_all_users(
        offset=page * per_page,
        limit=per_page,
        search=search or None,
    )
    total = await count_users(search=search or None)
    total_pages = max(1, math.ceil(total / per_page))

    templates = get_templates()
    return templates.TemplateResponse(
        "users.html",
        {
            "request": request,
            "users": users,
            "page": page,
            "total_pages": total_pages,
            "filter_search": search,
        },
    )


@router.get("/{user_id}", response_class=HTMLResponse)
async def user_detail(request: Request, user_id: Annotated[int, Path()]) -> Response:
    user = await get_user_by_id(user_id)
    if not user:
        return RedirectResponse("/users", status_code=303)

    templates = get_templates()
    return templates.TemplateResponse(
        "user_detail.html",
        {
            "request": request,
            "user": user,
            "wallet": await ensure_wallet(user_id),
            "recent_orders": await get_orders_by_user(user_id, limit=10),
        },
    )


@router.post("/{user_id}/adjust-wallet")
async def adjust_wallet(request: Request, user_id: Annotated[int, Path()]) -> RedirectResponse:
    form = await request.form()
    amount = int(form.get("amount", 0))
    description = form.get("description", "Admin adjustment")
    if amount != 0:
        await add_balance(
            user_id=user_id,
            amount=amount,
            tx_type="admin_adjust",
            description=description,
        )
    return RedirectResponse(f"/users/{user_id}", status_code=303)


@router.get("/{user_id}/toggle-admin")
async def toggle_admin(user_id: Annotated[int, Path()]) -> RedirectResponse:
    user = await get_user_by_id(user_id)
    if user:
        await set_admin(user_id, 0 if user["is_admin"] else 1)
    return RedirectResponse(f"/users/{user_id}", status_code=303)


@router.get("/{user_id}/toggle-ban")
async def toggle_ban(user_id: Annotated[int, Path()]) -> RedirectResponse:
    user = await get_user_by_id(user_id)
    if user:
        await set_banned(user_id, 0 if user["is_banned"] else 1)
    return RedirectResponse(f"/users/{user_id}", status_code=303)


@router.get("/{user_id}/toggle-discounts")
async def toggle_discounts(user_id: Annotated[int, Path()]) -> RedirectResponse:
    user = await get_user_by_id(user_id)
    if user:
        await set_discount_disabled(user_id, 0 if user.get("disable_discounts") else 1)
    return RedirectResponse(f"/users/{user_id}", status_code=303)
