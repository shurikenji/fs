"""
admin/routers/orders.py - Danh sách đơn hàng và các thao tác quản trị.
"""
from __future__ import annotations

import math
from typing import Annotated

from fastapi import HTTPException, Path, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from admin.deps import get_templates, protected_router
from bot.utils.formatting import format_vnd
from db.queries.logs import add_log
from db.queries.orders import (
    cancel_order,
    count_all_orders,
    get_all_orders,
    get_order_by_id,
)
from db.queries.servers import get_server_by_id
from db.queries.wallets import refund_order_to_wallet

router = protected_router(prefix="/orders", tags=["orders"])
_REFUNDABLE_ORDER_STATUSES = frozenset({"paid"})


def _redirect_to_orders() -> RedirectResponse:
    return RedirectResponse("/orders", status_code=303)


def _redirect_to_order_detail(order_id: int) -> RedirectResponse:
    return RedirectResponse(f"/orders/{order_id}", status_code=303)


async def _get_order_or_redirect(order_id: int) -> dict | RedirectResponse:
    order = await get_order_by_id(order_id)
    if order:
        return order
    return _redirect_to_orders()


def _can_refund_order(order: dict) -> bool:
    return (
        order["status"] in _REFUNDABLE_ORDER_STATUSES
        and order["product_type"] != "wallet_topup"
        and not order.get("is_refunded")
        and not order.get("api_key")
        and not order.get("delivery_info")
        and not order.get("api_token_name")
    )


@router.get("", response_class=HTMLResponse)
async def orders_list(request: Request):
    page = int(request.query_params.get("page", 0))
    status = request.query_params.get("status", "")
    search = request.query_params.get("search", "")
    per_page = 20

    orders = await get_all_orders(
        offset=page * per_page,
        limit=per_page,
        status=status or None,
        search=search or None,
    )
    total = await count_all_orders(status=status or None, search=search or None)
    total_pages = max(1, math.ceil(total / per_page))

    templates = get_templates()
    return templates.TemplateResponse(
        "orders.html",
        {
            "request": request,
            "orders": orders,
            "page": page,
            "total_pages": total_pages,
            "filter_status": status,
            "filter_search": search,
        },
    )


@router.get("/reconciliation", response_class=HTMLResponse)
async def reconciliation_page(request: Request):
    """Show bounded financial work needing an operator's attention."""
    from db.database import get_db

    db = await get_db()
    cursor = await db.execute(
        """SELECT id, transaction_id, amount, transaction_time, order_code, status, last_error
           FROM payment_receipts WHERE status IN ('unmatched', 'late', 'needs_review')
           ORDER BY id DESC LIMIT 100"""
    )
    receipts = [dict(row) for row in await cursor.fetchall()]
    cursor = await db.execute(
        """SELECT j.id, j.status, j.last_error, o.id AS order_id, o.order_code, o.product_type
           FROM fulfillment_jobs j JOIN orders o ON o.id = j.order_id
           WHERE j.status IN ('pending', 'processing', 'needs_review') ORDER BY j.id DESC LIMIT 100"""
    )
    jobs = [dict(row) for row in await cursor.fetchall()]
    cursor = await db.execute(
        """SELECT id, event_type, order_id, attempts, last_error FROM notification_outbox
           WHERE status = 'failed' ORDER BY id DESC LIMIT 100"""
    )
    failed_notifications = [dict(row) for row in await cursor.fetchall()]
    return get_templates().TemplateResponse(
        "reconciliation.html",
        {"request": request, "receipts": receipts, "jobs": jobs, "failed_notifications": failed_notifications},
    )


@router.get("/{order_id}", response_class=HTMLResponse)
async def order_detail(request: Request, order_id: Annotated[int, Path()]):
    order = await get_order_by_id(order_id)
    if not order:
        return RedirectResponse("/orders", status_code=303)
    server_name = None
    if order.get("server_id"):
        server = await get_server_by_id(int(order["server_id"]))
        if server:
            server_name = server.get("name")

    can_reconcile_topup = False
    if order["product_type"] == "key_topup" and order["status"] == "processing" and order.get("quantity") == 1:
        from db.database import get_db

        db = await get_db()
        cursor = await db.execute(
            """SELECT 1 FROM fulfillment_jobs j WHERE j.order_id = ? AND j.status = 'needs_review'
               AND NOT EXISTS (SELECT 1 FROM fulfillment_operations f WHERE f.job_id = j.id)""", (order_id,)
        )
        can_reconcile_topup = await cursor.fetchone() is not None

    templates = get_templates()
    return templates.TemplateResponse(
        "order_detail.html",
        {"request": request, "order": order, "server_name": server_name, "can_refund": _can_refund_order(order),
         "can_reconcile_topup": can_reconcile_topup},
    )


@router.post("/{order_id}/complete")
async def order_complete(order_id: Annotated[int, Path()]):
    """Đánh dấu đơn `service_upgrade` là đã hoàn thành."""
    order = await _get_order_or_redirect(order_id)
    if isinstance(order, RedirectResponse):
        return order

    from db.queries.fulfillment import complete_manual_service

    await complete_manual_service(order_id)
    return _redirect_to_order_detail(order_id)


@router.post("/{order_id}/complete-manual-topup")
async def manual_topup_complete(request: Request, order_id: Annotated[int, Path()]):
    from db.queries.manual_topup import complete_manual_topup

    form = await request.form()
    if form.get("confirmed") != "yes":
        raise HTTPException(status_code=400, detail="Cần xác nhận đã kiểm tra upstream")
    admin = request.session.get("admin") or {}
    try:
        completed = await complete_manual_topup(
            order_id, int(form.get("token_id", "")), int(form.get("total_before", "")),
            int(form.get("total_after", "")), int(form.get("quota_added", "")),
            str(form.get("evidence", "")), str(admin.get("source", "")),
        )
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Dữ liệu không hợp lệ hoặc cần kiểm tra thêm") from None
    if not completed:
        raise HTTPException(status_code=409, detail="Đơn chưa ở trạng thái có thể đối soát hoặc đã được xử lý")
    return _redirect_to_order_detail(order_id)


@router.post("/{order_id}/cancel")
async def order_cancel(order_id: Annotated[int, Path()]):
    await cancel_order(order_id)
    return _redirect_to_order_detail(order_id)


@router.post("/{order_id}/refund")
async def order_refund(order_id: Annotated[int, Path()]):
    """Refund a paid order back to the user's wallet."""
    order = await _get_order_or_redirect(order_id)
    if isinstance(order, RedirectResponse):
        return order

    if not _can_refund_order(order):
        return _redirect_to_order_detail(order_id)

    new_balance = await refund_order_to_wallet(
        order_id,
        reason="Admin refund",
        tx_type="admin_refund",
        description=f"Admin refund for order {order['order_code']}",
    )
    if new_balance is None:
        return _redirect_to_order_detail(order_id)
    await add_log(
        f"Admin refunded order {order['order_code']}, amount {format_vnd(order['amount'])}",
        module="admin",
    )
    return _redirect_to_order_detail(order_id)
