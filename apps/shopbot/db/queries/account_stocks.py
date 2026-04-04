"""
db/queries/account_stocks.py — CRUD cho kho tài khoản.
Tất cả account_stocked đều dùng bảng account_stocks.
"""
from __future__ import annotations

from typing import Optional

from db.database import get_db
from db.queries._helpers import execute_commit, fetch_all_dicts, fetch_one_dict


async def get_available_account(product_id: int) -> Optional[dict]:
    """Lấy 1 tài khoản chưa bán & CHƯA ĐẶT CHỖ cho product_id (FIFO)."""
    return await fetch_one_dict(
        """SELECT * FROM account_stocks
           WHERE product_id = ? AND is_sold = 0 AND (sold_order_id IS NULL OR sold_order_id = 0)
           ORDER BY id ASC LIMIT 1""",
        (product_id,),
    )

async def reserve_account(product_id: int, order_id: int) -> Optional[dict]:
    """
    Xí chỗ 1 tài khoản cho đơn hàng (tránh Race Condition lúc Checkout).
    Cập nhật sold_order_id = order_id nhưng is_sold vẫn = 0.
    Trả về tài khoản vừa được xí chỗ, hoặc None nếu hết hàng.
    """
    db = await get_db()
    
    # Do SQLite không có cơ chế khoá hàng (row-level lock) tốt như Postgres, 
    # ta update luôn 1 row thỏa mãn và lấy row đó ra bằng returning (hoặc select lại)
    # Tuy nhiên SQLite < 3.35 không hỗ trợ RETURNING, nên ta dùng cách loop/check an toàn nhất.
    
    # 1. Tìm 1 account chưa bán và chưa bị xí chỗ
    cursor = await db.execute(
        """SELECT id FROM account_stocks
           WHERE product_id = ? AND is_sold = 0 AND (sold_order_id IS NULL OR sold_order_id = 0)
           ORDER BY id ASC LIMIT 1""",
        (product_id,)
    )
    row = await cursor.fetchone()
    if not row:
        return None
        
    acc_id = row[0]
    
    # 2. Xí chỗ bằng Update
    cursor = await db.execute(
        """UPDATE account_stocks 
           SET sold_order_id = ?
           WHERE id = ? AND is_sold = 0 AND (sold_order_id IS NULL OR sold_order_id = 0)""",
        (order_id, acc_id)
    )
    await db.commit()
    
    if cursor.rowcount == 0:
        # Xí chỗ thất bại (bị request khác cuỗm mất)
        return None
        
    # Xí chỗ thành công, lấy chi tiết
    cursor = await db.execute("SELECT * FROM account_stocks WHERE id = ?", (acc_id,))
    row_details = await cursor.fetchone()
    return dict(row_details) if row_details else None


async def reserve_accounts(product_id: int, order_id: int, quantity: int) -> list[dict]:
    """Xí chỗ nhiều tài khoản cho cùng một đơn; rollback nếu không đủ."""
    reserved: list[dict] = []
    for _ in range(max(1, quantity)):
        account = await reserve_account(product_id, order_id)
        if not account:
            if reserved:
                await release_account_by_order(order_id)
            return []
        reserved.append(account)
    return reserved

async def release_account_by_order(order_id: int) -> None:
    """Hủy xí chỗ cho đơn bị hủy/lỗi trước khi thanh toán."""
    db = await get_db()
    await db.execute(
        """UPDATE account_stocks
           SET sold_order_id = NULL
           WHERE sold_order_id = ? AND is_sold = 0""",
        (order_id,)
    )
    await db.commit()

async def get_reserved_account(order_id: int) -> Optional[dict]:
    """Lấy đúng tài khoản đã xí chỗ cho đơn này (dùng lúc thanh toán xong)."""
    db = await get_db()
    cursor = await db.execute(
        """SELECT * FROM account_stocks
           WHERE sold_order_id = ? AND is_sold = 0
           LIMIT 1""",
        (order_id,)
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def get_reserved_accounts(order_id: int) -> list[dict]:
    """Lấy toàn bộ tài khoản đã xí chỗ cho một đơn."""
    return await fetch_all_dicts(
        """SELECT * FROM account_stocks
           WHERE sold_order_id = ? AND is_sold = 0
           ORDER BY id ASC""",
        (order_id,),
    )


async def mark_account_sold(
    account_id: int,
    user_id: int,
    order_id: int,
    product_id: int = 0,
) -> None:
    """Đánh dấu tài khoản đã bán."""
    await execute_commit(
        """UPDATE account_stocks
           SET is_sold = 1, sold_to_user = ?, sold_order_id = ?,
               sold_at = datetime('now', '+7 hours')
           WHERE id = ?""",
        (user_id, order_id, account_id),
    )


async def unmark_account_sold(account_id: int, product_id: int = 0) -> None:
    """Hoàn lại tài khoản (khi refund)."""
    await execute_commit(
        """UPDATE account_stocks
           SET is_sold = 0, sold_to_user = NULL, sold_order_id = NULL,
               sold_at = NULL
           WHERE id = ?""",
        (account_id,),
    )


async def add_account(
    product_id: int,
    account_data: str,
) -> int:
    """Thêm 1 tài khoản vào stock, trả về ID."""
    cursor = await execute_commit(
        """INSERT INTO account_stocks (product_id, account_data)
           VALUES (?, ?)""",
        (product_id, account_data),
    )
    return cursor.lastrowid  # type: ignore[return-value]


async def bulk_add_accounts(
    product_id: int,
    accounts_data: list[str],
) -> int:
    """Thêm nhiều tài khoản cùng lúc, trả về số lượng đã thêm."""
    db = await get_db()
    await db.executemany(
        "INSERT INTO account_stocks (product_id, account_data) VALUES (?, ?)",
        [(product_id, data) for data in accounts_data],
    )
    await db.commit()
    return len(accounts_data)


async def count_stock(product_id: int) -> dict:
    """Đếm stock: tổng, đã bán, còn lại."""
    db = await get_db()

    cursor = await db.execute(
        "SELECT COUNT(*) FROM account_stocks WHERE product_id = ?",
        (product_id,),
    )
    total = (await cursor.fetchone())[0]

    cursor = await db.execute(
        "SELECT COUNT(*) FROM account_stocks WHERE product_id = ? AND is_sold = 1",
        (product_id,),
    )
    sold = (await cursor.fetchone())[0]

    return {
        "total": total,
        "sold": sold,
        "available": total - sold,
    }


async def get_accounts_by_product(
    product_id: int,
    offset: int = 0,
    limit: int = 50,
    show_sold: bool = True,
) -> list[dict]:
    """Lấy danh sách tài khoản theo product (admin)."""
    query = "SELECT * FROM account_stocks WHERE product_id = ?"
    params: list = [product_id]

    if not show_sold:
        query += " AND is_sold = 0"

    query += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    return await fetch_all_dicts(query, tuple(params))


async def delete_account(account_id: int) -> None:
    """Xóa tài khoản khỏi stock."""
    await execute_commit(
        "DELETE FROM account_stocks WHERE id = ?", (account_id,)
    )
