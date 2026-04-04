"""
admin/routers/account_stock.py - Shared account stock management routes.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Path, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from admin.deps import get_templates, protected_router
from db.queries.account_stocks import (
    add_account,
    bulk_add_accounts,
    count_stock,
    delete_account,
    get_accounts_by_product,
)
from db.queries.categories import get_all_categories
from db.queries.products import get_all_products, get_product_by_id

router = protected_router(prefix="/account-stock", tags=["account_stock"])

_STOCK_TYPES = ("account_stocked",)


@router.get("", response_class=HTMLResponse)
async def account_stock_page(request: Request):
    categories = await get_all_categories()
    cat_map = {category["id"]: category for category in categories}

    stock_products = [
        product
        for product in await get_all_products(limit=200)
        if product["product_type"] in _STOCK_TYPES
    ]

    stock_by_product = {}
    for product in stock_products:
        stock_info = await count_stock(product["id"])
        accounts = await get_accounts_by_product(product["id"], limit=50)
        category = cat_map.get(product.get("category_id"), {})
        stock_by_product[product["id"]] = {
            "product_name": product["name"],
            "product_type": product["product_type"],
            "format_template": product.get("format_template") or "",
            "cat_name": category.get("name", ""),
            "cat_icon": category.get("icon", "📁"),
            **stock_info,
            "accounts": accounts,
        }

    templates = get_templates()
    return templates.TemplateResponse(
        "account_stock.html",
        {
            "request": request,
            "stock_by_product": stock_by_product,
            "stock_products": stock_products,
            "cat_map": cat_map,
        },
    )


@router.post("/add")
async def account_stock_add(request: Request):
    """Add one or many accounts to stock for a product."""
    form = await request.form()
    product_id = int(form["product_id"])
    raw_data = form.get("accounts_data", "")
    product = await get_product_by_id(product_id)
    if not product or product.get("product_type") not in _STOCK_TYPES:
        return RedirectResponse("/account-stock", status_code=303)

    lines = [line.strip() for line in raw_data.strip().splitlines() if line.strip()]
    if len(lines) == 1:
        await add_account(product_id, lines[0])
    elif len(lines) > 1:
        await bulk_add_accounts(product_id, lines)

    return RedirectResponse("/account-stock", status_code=303)


@router.get("/{account_id}/delete")
async def account_stock_delete(account_id: Annotated[int, Path()]):
    await delete_account(account_id)
    return RedirectResponse("/account-stock", status_code=303)
