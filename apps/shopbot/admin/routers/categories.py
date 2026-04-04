"""
admin/routers/categories.py - Category CRUD routes.
"""
from __future__ import annotations

import aiosqlite
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Path, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from admin.deps import get_templates, protected_router
from db.queries.categories import (
    count_products_by_category,
    create_category,
    delete_category,
    get_all_categories,
    get_category_by_id,
    update_category,
)

router = protected_router(prefix="/categories", tags=["categories"])


def _resolve_redirect_target(candidate: object, fallback: str) -> str:
    if candidate is not None:
        value = str(candidate).strip()
        if value.startswith("/"):
            return value
        parsed = urlsplit(value)
        if parsed.path.startswith("/"):
            return parsed.path + (f"?{parsed.query}" if parsed.query else "")
    return fallback


def _build_flash_context(request: Request) -> dict:
    msg = request.query_params.get("msg", "")
    error = request.query_params.get("error", "")

    if msg == "deleted":
        return {
            "flash_message": "Đã xoá danh mục thành công.",
            "flash_type": "success",
        }

    if error == "not_found":
        return {
            "flash_message": "Danh mục không tồn tại hoặc đã bị xoá.",
            "flash_type": "warning",
        }

    if error == "in_use":
        products = int(request.query_params.get("products", 0))
        detail = f"{products} sản phẩm" if products else "dữ liệu liên quan"
        return {
            "flash_message": f"Không thể xoá danh mục vì còn {detail}. Hãy chuyển hoặc xoá sản phẩm trước.",
            "flash_type": "danger",
        }

    if error == "delete_failed":
        return {
            "flash_message": "Xoá danh mục thất bại do lỗi ràng buộc dữ liệu.",
            "flash_type": "danger",
        }

    return {}


@router.get("", response_class=HTMLResponse)
async def categories_list(request: Request):
    templates = get_templates()
    return templates.TemplateResponse(
        "categories.html",
        {
            "request": request,
            "categories": await get_all_categories(),
            **_build_flash_context(request),
        },
    )


@router.post("/add")
async def categories_add(request: Request):
    form = await request.form()
    await create_category(
        name=form["name"],
        icon=form.get("icon", "📦"),
        cat_type=form.get("cat_type", "general"),
        description=form.get("description"),
        sort_order=int(form.get("sort_order", 0)),
    )
    return RedirectResponse("/categories", status_code=303)


@router.get("/{cat_id}/edit", response_class=HTMLResponse)
async def categories_edit_page(request: Request, cat_id: Annotated[int, Path()]):
    category = await get_category_by_id(cat_id)
    if not category:
        return RedirectResponse("/categories", status_code=303)

    templates = get_templates()
    return templates.TemplateResponse(
        "categories.html",
        {
            "request": request,
            "categories": await get_all_categories(),
            "editing": category,
        },
    )


@router.get("/{cat_id}/edit-modal", response_class=HTMLResponse)
async def categories_edit_modal(request: Request, cat_id: Annotated[int, Path()]) -> HTMLResponse:
    category = await get_category_by_id(cat_id)
    if not category:
        return HTMLResponse("Category not found", status_code=404)

    templates = get_templates()
    return templates.TemplateResponse(
        "_category_edit_modal.html",
        {
            "request": request,
            "editing": category,
        },
    )


@router.post("/{cat_id}/edit")
async def categories_edit_submit(request: Request, cat_id: Annotated[int, Path()]):
    form = await request.form()
    await update_category(
        cat_id,
        name=form.get("name"),
        icon=form.get("icon"),
        cat_type=form.get("cat_type"),
        description=form.get("description"),
        sort_order=int(form.get("sort_order", 0)) if form.get("sort_order") else None,
        is_active=1 if form.get("is_active") else 0,
    )
    return RedirectResponse("/categories", status_code=303)


@router.post("/{cat_id}/toggle-active")
async def categories_toggle_active(request: Request, cat_id: Annotated[int, Path()]):
    category = await get_category_by_id(cat_id)
    if not category:
        return RedirectResponse("/categories?error=not_found", status_code=303)

    form = await request.form()
    redirect_target = _resolve_redirect_target(
        form.get("next") or request.headers.get("referer"),
        "/categories",
    )
    await update_category(cat_id, is_active=0 if category.get("is_active") else 1)
    return RedirectResponse(redirect_target, status_code=303)


@router.get("/{cat_id}/delete")
async def categories_delete(cat_id: Annotated[int, Path()]):
    category = await get_category_by_id(cat_id)
    if not category:
        return RedirectResponse("/categories?error=not_found", status_code=303)

    products = await count_products_by_category(cat_id)
    if products > 0:
        return RedirectResponse(
            f"/categories?error=in_use&products={products}",
            status_code=303,
        )

    try:
        await delete_category(cat_id)
    except aiosqlite.IntegrityError:
        products = await count_products_by_category(cat_id)
        if products > 0:
            return RedirectResponse(
                f"/categories?error=in_use&products={products}",
                status_code=303,
            )
        return RedirectResponse("/categories?error=delete_failed", status_code=303)

    return RedirectResponse("/categories?msg=deleted", status_code=303)
