"""
Helper dùng chung cho các query đơn giản, không có transaction nhiều bước.
Không dùng cho các flow cần BEGIN/ROLLBACK thủ công như wallet/order processing.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from aiosqlite import Cursor

from db.database import get_db


Params = Sequence[Any]


async def fetch_scalar(query: str, params: Params = ()) -> Any | None:
    """Lấy cột đầu tiên của dòng đầu tiên, hoặc None nếu không có kết quả."""
    db = await get_db()
    cursor = await db.execute(query, tuple(params))
    row = await cursor.fetchone()
    return row[0] if row else None


async def fetch_all_dicts(query: str, params: Params = ()) -> list[dict]:
    """Lấy toàn bộ kết quả và chuyển mỗi dòng sang dict."""
    db = await get_db()
    cursor = await db.execute(query, tuple(params))
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def fetch_one_dict(query: str, params: Params = ()) -> dict | None:
    """Lấy dòng đầu tiên và chuyển sang dict."""
    db = await get_db()
    cursor = await db.execute(query, tuple(params))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def execute_commit(query: str, params: Params = ()) -> Cursor:
    """Chạy query ghi dữ liệu và commit ngay, trả về cursor để lấy metadata."""
    db = await get_db()
    cursor = await db.execute(query, tuple(params))
    await db.commit()
    return cursor
