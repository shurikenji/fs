"""
db/queries/logs.py — CRUD cho bảng logs.
Ghi log hoạt động hệ thống (payment, order processing, errors).
"""
from __future__ import annotations

from typing import Optional

from db.database import get_db
from db.queries._helpers import execute_commit, fetch_all_dicts, fetch_scalar


def _build_logs_filters(
    *,
    level: Optional[str] = None,
    module: Optional[str] = None,
    search: Optional[str] = None,
) -> tuple[str, list[str]]:
    """Tạo phần WHERE dùng chung cho filter logs."""
    clauses: list[str] = []
    params: list[str] = []

    if level:
        clauses.append("level = ?")
        params.append(level)
    if module:
        clauses.append("module = ?")
        params.append(module)
    if search:
        clauses.append("(message LIKE ? OR detail LIKE ?)")
        keyword = f"%{search}%"
        params.extend([keyword, keyword])

    where_clause = " WHERE " + " AND ".join(clauses) if clauses else ""
    return where_clause, params


async def add_log(
    message: str,
    level: str = "info",
    module: Optional[str] = None,
    detail: Optional[str] = None,
) -> int:
    """Ghi log mới, trả về ID."""
    cursor = await execute_commit(
        """INSERT INTO logs (level, module, message, detail)
           VALUES (?, ?, ?, ?)""",
        (level, module, message, detail),
    )
    return cursor.lastrowid  # type: ignore[return-value]


async def get_logs(
    offset: int = 0,
    limit: int = 50,
    level: Optional[str] = None,
    module: Optional[str] = None,
    search: Optional[str] = None,
) -> list[dict]:
    """Lấy logs (mới nhất trước, phân trang, filter)."""
    where_clause, params = _build_logs_filters(level=level, module=module, search=search)
    query = f"SELECT * FROM logs{where_clause} ORDER BY id DESC LIMIT ? OFFSET ?"
    query_params = [*params, limit, offset]
    return await fetch_all_dicts(query, query_params)


async def count_logs(
    level: Optional[str] = None,
    module: Optional[str] = None,
    search: Optional[str] = None,
) -> int:
    """Đếm tổng logs."""
    where_clause, params = _build_logs_filters(level=level, module=module, search=search)
    total = await fetch_scalar(f"SELECT COUNT(*) FROM logs{where_clause}", params)
    return int(total or 0)


async def clear_old_logs(days: int = 30) -> int:
    """Xóa logs cũ hơn N ngày, trả về số lượng đã xóa."""
    db = await get_db()
    cursor = await db.execute(
        """DELETE FROM logs
           WHERE created_at < datetime('now', '+7 hours', ? || ' days')""",
        (f"-{days}",),
    )
    await db.commit()
    return cursor.rowcount

