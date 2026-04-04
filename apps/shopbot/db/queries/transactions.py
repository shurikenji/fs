"""
db/queries/transactions.py — Dedup MBBank transactionID.
Bảng processed_transactions ngăn xử lý trùng giao dịch.
"""
from __future__ import annotations

from typing import Optional

from db.queries._helpers import execute_commit, fetch_all_dicts, fetch_scalar


async def is_transaction_processed(transaction_id: str) -> bool:
    """Kiểm tra giao dịch đã được xử lý chưa."""
    processed_id = await fetch_scalar(
        "SELECT id FROM processed_transactions WHERE transaction_id = ?",
        (transaction_id,),
    )
    return processed_id is not None


async def mark_transaction_processed(
    transaction_id: str,
    order_code: Optional[str] = None,
    amount: Optional[int] = None,
) -> None:
    """Đánh dấu giao dịch đã xử lý."""
    await execute_commit(
        """INSERT OR IGNORE INTO processed_transactions
           (transaction_id, order_code, amount)
           VALUES (?, ?, ?)""",
        (transaction_id, order_code, amount),
    )


async def get_processed_transactions(
    offset: int = 0,
    limit: int = 50,
) -> list[dict]:
    """Lấy danh sách giao dịch đã xử lý (admin)."""
    return await fetch_all_dicts(
        """SELECT * FROM processed_transactions
           ORDER BY id DESC LIMIT ? OFFSET ?""",
        (limit, offset),
    )
