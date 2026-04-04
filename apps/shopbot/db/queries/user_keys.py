"""
db/queries/user_keys.py — CRUD cho bảng user_keys (Keys của tôi).
Lưu trữ API keys mà user đã mua hoặc đăng ký.
"""
from __future__ import annotations

from typing import Optional

from db.queries._helpers import execute_commit, fetch_all_dicts, fetch_one_dict


def _build_user_keys_filters(
    user_id: int,
    *,
    server_id: Optional[int] = None,
    active_only: bool = True,
) -> tuple[str, tuple[object, ...]]:
    """Tạo phần WHERE và params dùng chung cho truy vấn user keys."""
    clauses = ["user_id = ?"]
    params: list[int] = [user_id]

    if server_id is not None:
        clauses.append("server_id = ?")
        params.append(server_id)
    if active_only:
        clauses.append("is_active = 1")

    where_clause = " WHERE " + " AND ".join(clauses)
    return where_clause, tuple(params)


async def get_user_keys(
    user_id: int,
    server_id: Optional[int] = None,
    active_only: bool = True,
    limit: Optional[int] = None,
) -> list[dict]:
    """Lấy danh sách keys của user, optional filter theo server."""
    where_clause, params = _build_user_keys_filters(
        user_id,
        server_id=server_id,
        active_only=active_only,
    )
    query = f"SELECT * FROM user_keys{where_clause} ORDER BY updated_at DESC, id DESC"
    if limit is not None:
        query += " LIMIT ?"
        params = (*params, limit)
    return await fetch_all_dicts(query, params)


async def get_active_user_keys_for_alerts() -> list[dict]:
    """List all active user keys for background low-balance scans."""
    return await fetch_all_dicts(
        """SELECT *
           FROM user_keys
           WHERE is_active = 1
           ORDER BY server_id ASC, id ASC"""
    )


async def search_user_keys(
    user_id: int,
    *,
    server_id: int,
    keyword: str,
    active_only: bool = True,
    limit: int = 10,
) -> list[dict]:
    """Tìm key đã lưu theo label hoặc chuỗi con của api_key."""
    normalized = keyword.strip()
    if not normalized:
        return []

    where_clause, params = _build_user_keys_filters(
        user_id,
        server_id=server_id,
        active_only=active_only,
    )
    like_pattern = f"%{normalized}%"
    query = (
        "SELECT * FROM user_keys"
        f"{where_clause} AND (api_key LIKE ? OR COALESCE(label, '') LIKE ?)"
        " ORDER BY updated_at DESC, id DESC LIMIT ?"
    )
    return await fetch_all_dicts(query, (*params, like_pattern, like_pattern, limit))


async def get_user_key_by_id(key_id: int) -> Optional[dict]:
    """Lấy user key theo ID."""
    return await fetch_one_dict("SELECT * FROM user_keys WHERE id = ?", (key_id,))


async def create_user_key(
    user_id: int,
    server_id: int,
    api_key: str,
    api_token_id: Optional[int] = None,
    label: Optional[str] = None,
) -> int:
    """Tạo user key mới, trả về ID."""
    cursor = await execute_commit(
        """INSERT INTO user_keys
           (user_id, server_id, api_key, api_token_id, label)
           VALUES (?, ?, ?, ?, ?)""",
        (user_id, server_id, api_key, api_token_id, label),
    )
    return cursor.lastrowid  # type: ignore[return-value]


async def update_user_key(
    key_id: int,
    label: Optional[str] = None,
    is_active: Optional[int] = None,
    api_token_id: Optional[int] = None,
) -> None:
    """Cập nhật user key."""
    fields = []
    values = []

    if label is not None:
        fields.append("label = ?")
        values.append(label)
    if is_active is not None:
        fields.append("is_active = ?")
        values.append(is_active)
    if api_token_id is not None:
        fields.append("api_token_id = ?")
        values.append(api_token_id)

    if not fields:
        return

    fields.append("updated_at = datetime('now', '+7 hours')")
    values.append(key_id)
    query = f"UPDATE user_keys SET {', '.join(fields)} WHERE id = ?"
    await execute_commit(query, tuple(values))


async def find_user_key_by_api_key(
    user_id: int,
    api_key: str,
) -> Optional[dict]:
    """Tìm user key theo api_key string (kiểm tra trùng)."""
    return await fetch_one_dict(
        "SELECT * FROM user_keys WHERE user_id = ? AND api_key = ?",
        (user_id, api_key),
    )


async def upsert_user_key(
    user_id: int,
    server_id: int,
    api_key: str,
    api_token_id: Optional[int] = None,
    label: Optional[str] = None,
) -> int:
    """
    Tạo hoặc cập nhật user key.
    Nếu key đã tồn tại cho user → update label/token_id.
    Nếu chưa → tạo mới.
    Returns key ID.
    """
    existing = await find_user_key_by_api_key(user_id, api_key)
    if existing:
        await update_user_key(
            existing["id"],
            label=label,
            api_token_id=api_token_id,
        )
        return existing["id"]

    return await create_user_key(
        user_id=user_id,
        server_id=server_id,
        api_key=api_key,
        api_token_id=api_token_id,
        label=label,
    )
