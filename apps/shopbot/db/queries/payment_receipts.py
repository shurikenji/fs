"""Store incoming bank receipts without losing unmatched or late payments."""
from __future__ import annotations

from datetime import datetime, timedelta

from bot.utils.time_utils import GMT_PLUS_7, get_now_vn, to_gmt7
from db.database import open_write_transaction
from db.queries.fulfillment import enqueue_paid_order


def _bank_time(value: str | None) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.strptime(value, "%d/%m/%Y %H:%M:%S")
    except ValueError:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return parsed.replace(tzinfo=GMT_PLUS_7) if parsed.tzinfo is None else parsed.astimezone(GMT_PLUS_7)


async def record_receipt(
    *, provider: str, account_identity: str, transaction_id: str, amount: int,
    transaction_time: str | None = None, order_code: str | None = None,
    description: str | None = None,
) -> tuple[str, int]:
    """Insert once; conflicting duplicates are held for manual reconciliation."""
    if not all(isinstance(value, str) and value.strip() and len(value) <= 200
               for value in (provider, account_identity, transaction_id)):
        raise ValueError("receipt identity is missing or invalid")
    if type(amount) is not int or not 0 < amount <= 2**63 - 1:
        raise ValueError("receipt amount must be a positive integer")
    if transaction_time is not None and (not isinstance(transaction_time, str) or len(transaction_time) > 100):
        raise ValueError("receipt time is invalid")
    if order_code is not None and (not isinstance(order_code, str) or len(order_code) > 100):
        raise ValueError("order code is invalid")
    if description is not None and (not isinstance(description, str) or len(description) > 2000):
        raise ValueError("receipt description is invalid")
    provider, account_identity, transaction_id = (value.strip() for value in (provider, account_identity, transaction_id))
    db = await open_write_transaction()
    try:
        cursor = await db.execute(
            """INSERT OR IGNORE INTO payment_receipts
               (provider, account_identity, transaction_id, amount, transaction_time, order_code, description, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'unmatched')""",
            (provider, account_identity, transaction_id, amount, transaction_time, order_code, description),
        )
        if cursor.rowcount == 1:
            receipt_id = cursor.lastrowid
            await db.commit()
            return "inserted", receipt_id
        cursor = await db.execute(
            """SELECT id, amount, order_code, order_id FROM payment_receipts
               WHERE provider = ? AND account_identity = ? AND transaction_id = ?""",
            (provider, account_identity, transaction_id),
        )
        receipt = await cursor.fetchone()
        if receipt is None:
            raise RuntimeError("receipt insert rejected without duplicate")
        conflict = receipt["amount"] != amount or (
            receipt["order_code"] and order_code and receipt["order_code"] != order_code
        )
        if conflict:
            await db.execute(
                "UPDATE payment_receipts SET status = 'needs_review', last_error = 'duplicate identity with conflicting data' WHERE id = ?",
                (receipt["id"],),
            )
            if receipt["order_id"] is not None:
                await db.execute(
                    """UPDATE fulfillment_jobs SET status = 'needs_review', last_error = 'receipt conflict',
                       lease_owner = NULL, lease_token = NULL, lease_until = NULL, updated_at = CURRENT_TIMESTAMP
                       WHERE order_id = ? AND status IN ('pending', 'processing')""",
                    (receipt["order_id"],),
                )
                cursor = await db.execute("SELECT user_id FROM orders WHERE id = ?", (receipt["order_id"],))
                order = await cursor.fetchone()
                if order and order["user_id"] is not None:
                    from db.queries.notification_outbox import enqueue_order_review

                    await enqueue_order_review(db, receipt["order_id"], order["user_id"], reference=f"receipt:{receipt['id']}")
        elif not receipt["order_code"] and order_code:
            await db.execute(
                "UPDATE payment_receipts SET order_code = ? WHERE id = ? AND status = 'unmatched'",
                (order_code, receipt["id"]),
            )
        await db.commit()
        return ("conflict" if conflict else "duplicate"), receipt["id"]
    except BaseException:
        await db.rollback()
        raise
    finally:
        await db.close()


async def match_receipt(receipt_id: int, *, account_verified: bool = False) -> str:
    """Match once and atomically mark paid, deduplicate and enqueue fulfillment."""
    db = await open_write_transaction()
    try:
        cursor = await db.execute("SELECT * FROM payment_receipts WHERE id = ?", (receipt_id,))
        receipt = await cursor.fetchone()
        if receipt is None:
            raise ValueError("receipt not found")
        if receipt["status"] != "unmatched":
            await db.rollback()
            return receipt["status"]
        if account_verified is not True:
            await db.rollback()
            return "identity_unverified"
        cursor = await db.execute("SELECT * FROM orders WHERE order_code = ?", (receipt["order_code"],))
        order = await cursor.fetchone()
        if order is None:
            await db.rollback()
            return "unmatched"
        error = None
        if order["status"] in ("cancelled", "expired"):
            status, error = "late", "order closed before receipt was matched"
        elif order["status"] != "pending" or order["payment_method"] != "qr" or order["is_refunded"] != 0:
            status, error = "needs_review", "order is not pending QR payment"
        elif type(order["amount"]) is not int or order["amount"] != receipt["amount"]:
            status, error = "needs_review", "amount mismatch"
        else:
            transaction_time = _bank_time(receipt["transaction_time"])
            created_at = to_gmt7(order["created_at"])
            expired_at = to_gmt7(order["expired_at"]) if order["expired_at"] else None
            if not transaction_time or not created_at or (order["expired_at"] and not expired_at):
                status, error = "needs_review", "receipt or order timestamp is invalid"
            elif transaction_time < created_at or transaction_time > get_now_vn() + timedelta(minutes=5):
                status, error = "needs_review", "receipt time is outside the valid window"
            elif expired_at and transaction_time > expired_at:
                status, error = "late", "receipt arrived after the order expired"
            else:
                cursor = await db.execute(
                    "SELECT 1 FROM processed_transactions WHERE transaction_id = ?", (receipt["transaction_id"],)
                )
                if await cursor.fetchone():
                    status, error = "needs_review", "transaction ID was already processed"
                else:
                    cursor = await db.execute(
                        """UPDATE orders SET status = 'paid', paid_at = datetime('now', '+7 hours'),
                           mb_transaction_id = ?, updated_at = datetime('now', '+7 hours')
                           WHERE id = ? AND status = 'pending' AND payment_method = 'qr' AND amount = ?""",
                        (receipt["transaction_id"], order["id"], receipt["amount"]),
                    )
                    if cursor.rowcount != 1:
                        raise RuntimeError("order changed during receipt matching")
                    await db.execute(
                        "INSERT INTO processed_transactions (transaction_id, order_code, amount) VALUES (?, ?, ?)",
                        (receipt["transaction_id"], order["order_code"], receipt["amount"]),
                    )
                    await enqueue_paid_order(db, order["id"])
                    status = "matched"
        await db.execute(
            "UPDATE payment_receipts SET status = ?, order_id = ?, last_error = ? WHERE id = ?",
            (status, order["id"], error, receipt_id),
        )
        if status != "matched" and order["user_id"] is not None:
            from db.queries.notification_outbox import enqueue_order_review

            await enqueue_order_review(db, order["id"], order["user_id"], reference=f"receipt:{receipt_id}")
        await db.commit()
        return status
    except BaseException:
        await db.rollback()
        raise
    finally:
        await db.close()
