"""
admin/routers/orders.py - Danh sách đơn hàng và các thao tác quản trị.
"""
from __future__ import annotations

import math
from typing import Annotated

from fastapi import Path, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from admin.deps import get_templates, protected_router
from bot.services.admin_order_notifications import (
    notify_admin_order_refunded,
    notify_admin_service_completed,
)
from bot.services.notifier import notify_user
from bot.services.spend_ledger import SpendLedgerService
from bot.utils.formatting import format_vnd
from db.queries.logs import add_log
from db.queries.orders import (
    cancel_order,
    count_all_orders,
    get_all_orders,
    get_order_by_id,
    update_order_status,
)
from db.queries.servers import get_server_by_id
from db.queries.wallets import refund_order_to_wallet

router = protected_router(prefix="/orders", tags=["orders"])
_REFUNDABLE_ORDER_STATUSES = frozenset({"paid", "processing", "completed"})


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
    )


def _completed_service_upgrade_message(order: dict) -> str:
    return (
        f"✅ Đơn dịch vụ <b>{order['order_code']}</b> của bạn đã được Admin xử lý hoàn tất!\n\n"
        "🎉 Cảm ơn bạn đã sử dụng dịch vụ."
    )


def _refund_notification_message(order: dict, new_balance: int) -> str:
    return (
        f"↩️ Đơn <b>{order['order_code']}</b> đã bị hủy.\n\n"
        f"💳 Bạn được hoàn <b>{format_vnd(order['amount'])}</b> vào số dư ví.\n"
        f"👛 Số dư mới: <b>{format_vnd(new_balance)}</b>"
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

    templates = get_templates()
    return templates.TemplateResponse(
        "order_detail.html",
        {"request": request, "order": order, "server_name": server_name},
    )


@router.post("/{order_id}/complete")
async def order_complete(order_id: Annotated[int, Path()]):
    """Đánh dấu đơn `service_upgrade` là đã hoàn thành."""
    order = await _get_order_or_redirect(order_id)
    if isinstance(order, RedirectResponse):
        return order

    await update_order_status(order_id, "completed")
    await notify_user(order["user_id"], _completed_service_upgrade_message(order))
    completed_order = await get_order_by_id(order_id)
    if completed_order:
        await notify_admin_service_completed(completed_order)
    return _redirect_to_order_detail(order_id)


@router.get("/{order_id}/cancel")
async def order_cancel(order_id: Annotated[int, Path()]):
    await cancel_order(order_id)
    return _redirect_to_order_detail(order_id)


@router.get("/{order_id}/refund")
async def order_refund(order_id: Annotated[int, Path()]):
    """Hoàn tiền đơn đã thanh toán về ví của người dùng."""
    order = await _get_order_or_redirect(order_id)
    if isinstance(order, RedirectResponse):
        return order

    if not _can_refund_order(order):
        return _redirect_to_order_detail(order_id)

    new_balance = await refund_order_to_wallet(
        order_id,
        reason="Admin hoàn tiền",
        tx_type="admin_refund",
        description=f"Admin hoàn tiền đơn {order['order_code']}",
    )
    if new_balance is None:
        return _redirect_to_order_detail(order_id)
    await SpendLedgerService.record_order_refund(order)

    await add_log(
        f"Admin hoàn tiền đơn {order['order_code']}, số tiền {format_vnd(order['amount'])}",
        module="admin",
    )
    await notify_user(order["user_id"], _refund_notification_message(order, new_balance))
    refunded_order = await get_order_by_id(order_id)
    if refunded_order:
        await notify_admin_order_refunded(refunded_order, reason="Admin hoàn tiền")

    return _redirect_to_order_detail(order_id)
