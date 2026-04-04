"""
bot/services/spend_ledger.py - Append-only spend ledger and summary updates.
"""
from __future__ import annotations

import json
from typing import Any

from db.database import get_db


KEY_PRODUCT_TYPES = frozenset({"key_new", "key_topup"})


class SpendLedgerService:
    @staticmethod
    async def record(
        *,
        user_id: int,
        server_id: int,
        source_type: str,
        source_ref: str,
        amount: int,
        description: str = "",
        detail: dict[str, Any] | None = None,
    ) -> int | None:
        db = await get_db()
        await db.execute("BEGIN IMMEDIATE")
        try:
            cursor = await db.execute(
                """SELECT id
                   FROM spend_ledger
                   WHERE source_type = ? AND source_ref = ?""",
                (source_type, source_ref),
            )
            if await cursor.fetchone():
                await db.rollback()
                return None

            cursor = await db.execute(
                """INSERT INTO spend_ledger
                   (user_id, server_id, source_type, source_ref, amount, direction, description, detail_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    user_id,
                    server_id,
                    source_type,
                    source_ref,
                    amount,
                    "credit" if amount >= 0 else "debit",
                    description,
                    json.dumps(detail or {}, ensure_ascii=True),
                ),
            )
            ledger_id = int(cursor.lastrowid)

            summary_cursor = await db.execute(
                """SELECT total_spend_vnd
                   FROM user_server_spend_summary
                   WHERE user_id = ? AND server_id = ?""",
                (user_id, server_id),
            )
            summary_row = await summary_cursor.fetchone()
            new_total = max(0, int((summary_row["total_spend_vnd"] if summary_row else 0) + amount))
            await db.execute(
                """INSERT INTO user_server_spend_summary
                   (user_id, server_id, total_spend_vnd, last_ledger_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))
                   ON CONFLICT(user_id, server_id) DO UPDATE SET
                       total_spend_vnd = excluded.total_spend_vnd,
                       last_ledger_id = excluded.last_ledger_id,
                       updated_at = datetime('now')""",
                (user_id, server_id, new_total, ledger_id),
            )
            await db.commit()
            return ledger_id
        except Exception:
            await db.rollback()
            raise

    @staticmethod
    async def record_order_completion(order: dict[str, Any]) -> int | None:
        if order.get("product_type") not in KEY_PRODUCT_TYPES:
            return None
        server_id = order.get("server_id")
        if not server_id:
            return None
        amount = int(order.get("spend_credit_amount") or order.get("amount") or 0)
        if amount <= 0:
            return None
        return await SpendLedgerService.record(
            user_id=order["user_id"],
            server_id=server_id,
            source_type="order_completion",
            source_ref=str(order["id"]),
            amount=amount,
            description=f"Spend credit from order {order['order_code']}",
            detail={
                "order_code": order["order_code"],
                "pricing_version_id": order.get("pricing_version_id"),
                "tier_id": order.get("applied_tier_id"),
            },
        )

    @staticmethod
    async def record_order_refund(order: dict[str, Any]) -> int | None:
        if order.get("product_type") not in KEY_PRODUCT_TYPES:
            return None
        server_id = order.get("server_id")
        if not server_id:
            return None
        db = await get_db()
        cursor = await db.execute(
            """SELECT id
               FROM spend_ledger
               WHERE source_type = 'order_completion' AND source_ref = ?""",
            (str(order["id"]),),
        )
        if not await cursor.fetchone():
            return None
        amount = int(order.get("spend_credit_amount") or order.get("amount") or 0)
        if amount <= 0:
            return None
        return await SpendLedgerService.record(
            user_id=order["user_id"],
            server_id=server_id,
            source_type="order_refund",
            source_ref=str(order["id"]),
            amount=-amount,
            description=f"Spend reversal for refunded order {order['order_code']}",
            detail={
                "order_code": order["order_code"],
                "pricing_version_id": order.get("pricing_version_id"),
                "tier_id": order.get("applied_tier_id"),
            },
        )
