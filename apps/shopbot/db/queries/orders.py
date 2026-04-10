"""
db/queries/orders.py - CRUD operations for orders.
"""
from __future__ import annotations

from typing import Optional

from bot.utils.time_utils import to_db_time_string
from db.database import get_db
from db.queries.analytics import get_dashboard_overview
from db.queries._helpers import execute_commit, fetch_all_dicts, fetch_one_dict, fetch_scalar

_ORDER_UPDATEABLE_FIELDS = frozenset(
    {
        "api_key",
        "api_token_id",
        "api_token_name",
        "completed_at",
        "delivery_info",
        "delivery_token_names",
        "expired_at",
        "is_refunded",
        "mb_transaction_id",
        "paid_at",
        "payment_method",
        "pricing_snapshot",
        "promotion_snapshot",
        "quota_after",
        "quota_before",
        "refund_reason",
        "refunded_at",
        "user_input_data",
    }
)
_ORDER_SELECT = "SELECT * FROM orders"


def _build_order_admin_filters(
    *,
    status: Optional[str] = None,
    search: Optional[str] = None,
) -> tuple[str, list[str]]:
    query = " FROM orders WHERE 1=1"
    params: list[str] = []

    if status:
        query += " AND status = ?"
        params.append(status)
    if search:
        query += " AND (order_code LIKE ? OR product_name LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])

    return query, params


async def _fetch_order(where_clause: str, params: tuple[object, ...]) -> Optional[dict]:
    return await fetch_one_dict(f"{_ORDER_SELECT} WHERE {where_clause}", params)


async def create_order(
    order_code: str,
    user_id: int,
    product_type: str,
    amount: int,
    payment_method: str,
    quantity: int = 1,
    product_id: Optional[int] = None,
    product_name: Optional[str] = None,
    server_id: Optional[int] = None,
    group_name: Optional[str] = None,
    existing_key: Optional[str] = None,
    custom_quota: Optional[int] = None,
    qr_content: Optional[str] = None,
    expired_at: Optional[str] = None,
    base_amount: Optional[int] = None,
    discount_amount: int = 0,
    cashback_amount: int = 0,
    spend_credit_amount: int = 0,
    pricing_version_id: Optional[int] = None,
    applied_tier_id: Optional[int] = None,
    pricing_snapshot: Optional[str] = None,
    promotion_snapshot: Optional[str] = None,
) -> int:
    """Create a new order and return its ID."""
    cursor = await execute_commit(
        """INSERT INTO orders
           (order_code, user_id, product_id, product_name, product_type,
            amount, quantity, payment_method, server_id, group_name, existing_key,
            custom_quota, qr_content, expired_at, base_amount, discount_amount,
            cashback_amount, spend_credit_amount, pricing_version_id,
            applied_tier_id, pricing_snapshot, promotion_snapshot)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            order_code,
            user_id,
            product_id,
            product_name,
            product_type,
            amount,
            quantity,
            payment_method,
            server_id,
            group_name,
            existing_key,
            custom_quota,
            qr_content,
            expired_at,
            base_amount,
            discount_amount,
            cashback_amount,
            spend_credit_amount,
            pricing_version_id,
            applied_tier_id,
            pricing_snapshot,
            promotion_snapshot,
        ),
    )
    return cursor.lastrowid  # type: ignore[return-value]


async def get_order_by_id(order_id: int) -> Optional[dict]:
    """Get an order by ID."""
    return await _fetch_order("id = ?", (order_id,))


async def get_order_by_code(order_code: str) -> Optional[dict]:
    """Get an order by code."""
    return await _fetch_order("order_code = ?", (order_code,))


async def get_orders_by_user(
    user_id: int,
    offset: int = 0,
    limit: int = 10,
) -> list[dict]:
    """Get user orders with newest first."""
    return await fetch_all_dicts(
        """SELECT * FROM orders
           WHERE user_id = ?
           ORDER BY id DESC LIMIT ? OFFSET ?""",
        (user_id, limit, offset),
    )


async def count_orders_by_user(user_id: int) -> int:
    """Count all orders for a user."""
    return int(await fetch_scalar("SELECT COUNT(*) FROM orders WHERE user_id = ?", (user_id,)) or 0)


async def get_pending_orders() -> list[dict]:
    """Get all pending orders."""
    return await fetch_all_dicts("SELECT * FROM orders WHERE status = 'pending' ORDER BY id ASC")


async def get_pending_qr_orders() -> list[dict]:
    """Get QR payment orders waiting for payment."""
    return await fetch_all_dicts(
        """SELECT * FROM orders
           WHERE status = 'pending' AND payment_method = 'qr'
           ORDER BY id ASC"""
    )


async def update_order_status(
    order_id: int,
    status: str,
    **kwargs,
) -> None:
    """Update order status and optional fields."""
    db = await get_db()
    fields = ["status = ?", "updated_at = datetime('now', '+7 hours')"]
    values: list[object] = [status]

    if status == "completed" and not kwargs.get("completed_at"):
        kwargs["completed_at"] = to_db_time_string()

    for key, val in kwargs.items():
        if key in _ORDER_UPDATEABLE_FIELDS:
            fields.append(f"{key} = ?")
            values.append(val)

    values.append(order_id)
    query = f"UPDATE orders SET {', '.join(fields)} WHERE id = ?"
    await db.execute(query, tuple(values))
    await db.commit()


async def cancel_order(order_id: int) -> None:
    """Cancel an order and release reserved stock if any."""
    await update_order_status(order_id, "cancelled")
    from db.queries.account_stocks import release_account_by_order

    await release_account_by_order(order_id)


async def expire_order(order_id: int) -> None:
    """Mark order as expired and release reserved stock if any."""
    await update_order_status(order_id, "expired", expired_at=to_db_time_string())
    from db.queries.account_stocks import release_account_by_order

    await release_account_by_order(order_id)


async def mark_refunded(
    order_id: int,
    reason: Optional[str] = None,
) -> None:
    """Mark an order as refunded once."""
    await execute_commit(
        """UPDATE orders
           SET is_refunded = 1, refund_reason = ?, refunded_at = datetime('now', '+7 hours'),
               status = 'refunded', updated_at = datetime('now', '+7 hours')
           WHERE id = ? AND is_refunded = 0""",
        (reason, order_id),
    )


async def get_all_orders(
    offset: int = 0,
    limit: int = 50,
    status: Optional[str] = None,
    search: Optional[str] = None,
) -> list[dict]:
    """Get all orders for admin pages."""
    query, params = _build_order_admin_filters(status=status, search=search)
    query = "SELECT *" + query + " ORDER BY id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    return await fetch_all_dicts(query, tuple(params))


async def count_all_orders(
    status: Optional[str] = None,
    search: Optional[str] = None,
) -> int:
    """Count all orders for admin pages."""
    query, params = _build_order_admin_filters(status=status, search=search)
    return int(await fetch_scalar("SELECT COUNT(*)" + query, tuple(params)) or 0)


async def get_order_stats() -> dict:
    """Backward-compatible dashboard stats wrapper."""
    return await get_dashboard_overview()
