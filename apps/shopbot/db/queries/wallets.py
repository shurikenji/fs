"""
db/queries/wallets.py — CRUD operations cho bảng wallets + wallet_transactions.
Tiền tệ luôn dùng INTEGER (VNĐ).
"""
from __future__ import annotations

from bot.utils.time_utils import to_db_time_string
from typing import Optional

from db.database import get_db, open_write_transaction


async def get_wallet(user_id: int) -> Optional[dict]:
    """Lấy ví của user."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM wallets WHERE user_id = ?", (user_id,)
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def ensure_wallet(user_id: int) -> dict:
    """Tạo ví nếu chưa có, trả về ví hiện tại."""
    db = await open_write_transaction()
    try:
        await db.execute("INSERT OR IGNORE INTO wallets (user_id, balance) VALUES (?, 0)", (user_id,))
        cursor = await db.execute("SELECT * FROM wallets WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        await db.commit()
        return dict(row)
    except BaseException:
        await db.rollback()
        raise
    finally:
        await db.close()


async def get_balance(user_id: int) -> int:
    """Lấy số dư ví (tạo ví nếu chưa có)."""
    wallet = await ensure_wallet(user_id)
    return wallet["balance"]


async def add_balance(
    user_id: int,
    amount: int,
    tx_type: str,
    reference_id: Optional[str] = None,
    description: Optional[str] = None,
) -> int:
    """
    Cộng tiền vào ví (amount dương = cộng, âm = trừ).
    Trả về balance sau khi thay đổi.
    Tạo wallet_transaction để audit.
    """
    return await _adjust_balance(user_id, amount, tx_type, reference_id, description)


async def _adjust_balance(
    user_id: int,
    amount: int,
    tx_type: str,
    reference_id: Optional[str],
    description: Optional[str],
    *,
    require_funds: bool = False,
) -> int:
    if type(amount) is not int:
        raise ValueError("Số tiền phải là số nguyên VNĐ")
    db = await open_write_transaction()
    try:
        await db.execute("INSERT OR IGNORE INTO wallets (user_id, balance) VALUES (?, 0)", (user_id,))
        if require_funds:
            cursor = await db.execute("SELECT balance FROM wallets WHERE user_id = ?", (user_id,))
            balance = (await cursor.fetchone())["balance"]
            if balance < -amount:
                raise ValueError(f"Số dư không đủ: hiện có {balance}₫, cần {-amount}₫")
        await db.execute(
            "UPDATE wallets SET balance = balance + ?, updated_at = datetime('now', '+7 hours') WHERE user_id = ?",
            (amount, user_id),
        )
        cursor = await db.execute("SELECT balance FROM wallets WHERE user_id = ?", (user_id,))
        new_balance = (await cursor.fetchone())["balance"]
        await db.execute(
            """INSERT INTO wallet_transactions
               (user_id, amount, balance_after, type, reference_id, description)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, amount, new_balance, tx_type, reference_id, description),
        )
        await db.commit()
        return new_balance
    except BaseException:
        await db.rollback()
        raise
    finally:
        await db.close()


async def deduct_balance(
    user_id: int,
    amount: int,
    reference_id: Optional[str] = None,
    description: Optional[str] = None,
) -> int:
    """
    Trừ tiền từ ví. amount phải > 0.
    Trả về balance mới.
    Raises ValueError nếu không đủ tiền.
    """
    if type(amount) is not int or amount <= 0:
        raise ValueError("Số tiền cần trừ phải lớn hơn 0")
    return await _adjust_balance(user_id, -amount, "purchase", reference_id, description, require_funds=True)


async def charge_pending_order_from_wallet(order_id: int) -> Optional[dict]:
    """
    Thanh toán một đơn pending bằng ví trong cùng một transaction.
    Trả về snapshot order sau khi đã đánh dấu `paid`, hoặc `None` nếu đơn không hợp lệ.
    Raises ValueError nếu số dư không đủ.
    """
    db = await open_write_transaction()

    try:
        cursor = await db.execute(
            "SELECT * FROM orders WHERE id = ?",
            (order_id,),
        )
        row = await cursor.fetchone()
        if not row:
            await db.rollback()
            return None

        order = dict(row)
        if order["status"] != "pending":
            await db.rollback()
            return None

        if type(order["amount"]) is not int or order["amount"] < 0:
            await db.rollback()
            raise ValueError("Số tiền đơn hàng không hợp lệ")

        await db.execute(
            "INSERT OR IGNORE INTO wallets (user_id, balance) VALUES (?, 0)",
            (order["user_id"],),
        )
        cursor = await db.execute(
            "SELECT balance FROM wallets WHERE user_id = ?",
            (order["user_id"],),
        )
        wallet_row = await cursor.fetchone()
        balance = wallet_row["balance"] if wallet_row else 0
        if balance < order["amount"]:
            await db.rollback()
            raise ValueError(
                f"Số dư không đủ: hiện có {balance}₫, cần {order['amount']}₫"
            )

        new_balance = balance - order["amount"]
        paid_at = to_db_time_string()

        await db.execute(
            """UPDATE wallets
               SET balance = ?, updated_at = datetime('now', '+7 hours')
               WHERE user_id = ?""",
            (new_balance, order["user_id"]),
        )
        await db.execute(
            """INSERT INTO wallet_transactions
               (user_id, amount, balance_after, type, reference_id, description, operation_key)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                order["user_id"],
                -order["amount"],
                new_balance,
                "purchase",
                order["order_code"],
                f"Thanh toán đơn {order['order_code']}",
                f"order:{order_id}:debit",
            ),
        )
        await db.execute(
            """UPDATE orders
               SET status = 'paid',
                   payment_method = 'wallet',
                   paid_at = ?,
                   updated_at = datetime('now', '+7 hours')
               WHERE id = ? AND status = 'pending'""",
            (paid_at, order_id),
        )
        from db.queries.fulfillment import enqueue_paid_order

        await enqueue_paid_order(db, order_id)
        await db.commit()

        order["status"] = "paid"
        order["payment_method"] = "wallet"
        order["paid_at"] = paid_at
        return order
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


async def complete_wallet_topup_order(order_id: int, *, claim: Optional[dict] = None) -> Optional[int]:
    """
    Hoàn tất một đơn nạp ví đã thanh toán trong cùng một transaction.
    Trả về số dư mới, hoặc `None` nếu đơn không ở trạng thái hợp lệ.
    """
    db = await open_write_transaction()

    try:
        cursor = await db.execute(
            "SELECT * FROM orders WHERE id = ?",
            (order_id,),
        )
        row = await cursor.fetchone()
        if not row:
            await db.rollback()
            return None

        order = dict(row)
        if (order["status"] not in {"paid", "processing"}
                or order["product_type"] != "wallet_topup" or order["is_refunded"] == 1
                or type(order["amount"]) is not int or order["amount"] <= 0):
            await db.rollback()
            return None
        if claim is not None:
            cursor = await db.execute(
                """SELECT 1 FROM fulfillment_jobs WHERE id = ? AND order_id = ? AND status = 'processing'
                   AND lease_token = ? AND lease_until > CURRENT_TIMESTAMP""",
                (claim["id"], order_id, claim["lease_token"]),
            )
            if order["status"] != "processing" or not await cursor.fetchone():
                await db.rollback()
                return None

        await db.execute(
            "INSERT OR IGNORE INTO wallets (user_id, balance) VALUES (?, 0)",
            (order["user_id"],),
        )
        cursor = await db.execute(
            "SELECT balance FROM wallets WHERE user_id = ?",
            (order["user_id"],),
        )
        wallet_row = await cursor.fetchone()
        balance = wallet_row["balance"] if wallet_row else 0
        new_balance = balance + order["amount"]

        await db.execute(
            """UPDATE wallets
               SET balance = ?, updated_at = datetime('now', '+7 hours')
               WHERE user_id = ?""",
            (new_balance, order["user_id"]),
        )
        await db.execute(
            """INSERT INTO wallet_transactions
               (user_id, amount, balance_after, type, reference_id, description, operation_key)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                order["user_id"],
                order["amount"],
                new_balance,
                "topup",
                order["order_code"],
                f"Nạp ví qua QR - {order['order_code']}",
                f"order:{order_id}:topup",
            ),
        )
        await db.execute(
            """UPDATE orders
               SET status = 'completed',
                   completed_at = ?,
                   updated_at = datetime('now', '+7 hours')
               WHERE id = ? AND status IN ('paid', 'processing')""",
            (to_db_time_string(), order_id),
        )
        if claim is not None:
            from db.queries.notification_outbox import enqueue_order_completion

            await enqueue_order_completion(db, order_id, order["user_id"])
        await db.commit()
        return new_balance
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


async def refund_order_to_wallet(
    order_id: int,
    *,
    reason: str,
    tx_type: str = "refund",
    description: Optional[str] = None,
) -> Optional[int]:
    """
    Hoàn tiền một đơn về ví trong cùng một transaction.
    Trả về số dư mới, hoặc `None` nếu đơn không tồn tại hay đã hoàn trước đó.
    """
    db = await open_write_transaction()

    try:
        cursor = await db.execute(
            "SELECT * FROM orders WHERE id = ?",
            (order_id,),
        )
        row = await cursor.fetchone()
        if not row:
            await db.rollback()
            return None

        order = dict(row)
        # shortcut: processing or completed orders require reconciliation until fulfillment operations are persisted.
        if (order["is_refunded"] == 1 or order["status"] != "paid"
                or type(order["amount"]) is not int or order["amount"] < 0
                or order["product_type"] == "wallet_topup"
                or order.get("api_key") or order.get("delivery_info") or order.get("api_token_name")):
            await db.rollback()
            return None
        cursor = await db.execute(
            """SELECT 1 WHERE EXISTS (SELECT 1 FROM fulfillment_jobs WHERE order_id = ? AND status != 'pending')
               OR EXISTS (SELECT 1 FROM fulfillment_jobs j JOIN fulfillment_operations f ON f.job_id = j.id WHERE j.order_id = ?)
               OR EXISTS (SELECT 1 FROM account_stocks WHERE sold_order_id = ? AND is_sold = 1)""",
            (order_id, order_id, order_id),
        )
        if await cursor.fetchone():
            await db.rollback()
            return None

        await db.execute(
            "INSERT OR IGNORE INTO wallets (user_id, balance) VALUES (?, 0)",
            (order["user_id"],),
        )
        cursor = await db.execute(
            "SELECT balance FROM wallets WHERE user_id = ?",
            (order["user_id"],),
        )
        wallet_row = await cursor.fetchone()
        balance = wallet_row["balance"] if wallet_row else 0
        new_balance = balance + order["amount"]
        refunded_at = to_db_time_string()

        await db.execute(
            """UPDATE wallets
               SET balance = ?, updated_at = datetime('now', '+7 hours')
               WHERE user_id = ?""",
            (new_balance, order["user_id"]),
        )
        await db.execute(
            """INSERT INTO wallet_transactions
               (user_id, amount, balance_after, type, reference_id, description, operation_key)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                order["user_id"],
                order["amount"],
                new_balance,
                tx_type,
                order["order_code"],
                description or f"Hoàn tiền đơn {order['order_code']}",
                f"order:{order_id}:refund",
            ),
        )
        await db.execute(
            """UPDATE orders
               SET is_refunded = 1,
                   refund_reason = ?,
                   refunded_at = ?,
                   status = 'refunded',
                   updated_at = datetime('now', '+7 hours')
               WHERE id = ? AND is_refunded = 0""",
            (reason, refunded_at, order_id),
        )
        await db.execute(
            """UPDATE fulfillment_jobs SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP
               WHERE order_id = ? AND status = 'pending'""",
            (order_id,),
        )
        await db.execute(
            "UPDATE account_stocks SET sold_order_id = NULL WHERE sold_order_id = ? AND is_sold = 0",
            (order_id,),
        )
        from bot.services.spend_ledger import SpendLedgerService
        from db.queries.notification_outbox import enqueue_order_refund

        await SpendLedgerService.record_order_refund(order, _db=db)
        await enqueue_order_refund(db, order_id, order["user_id"])
        await db.commit()
        return new_balance
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


async def get_wallet_transactions(
    user_id: int,
    offset: int = 0,
    limit: int = 10,
) -> list[dict]:
    """Lấy lịch sử giao dịch ví (mới nhất trước)."""
    db = await get_db()
    cursor = await db.execute(
        """SELECT * FROM wallet_transactions
           WHERE user_id = ?
           ORDER BY id DESC LIMIT ? OFFSET ?""",
        (user_id, limit, offset),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def count_wallet_transactions(user_id: int) -> int:
    """Đếm tổng giao dịch ví."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT COUNT(*) FROM wallet_transactions WHERE user_id = ?",
        (user_id,),
    )
    row = await cursor.fetchone()
    return row[0] if row else 0

