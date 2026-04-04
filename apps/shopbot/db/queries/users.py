"""
db/queries/users.py - CRUD operations for users.
"""
from __future__ import annotations

from typing import Optional

from db.database import get_db
from db.queries._helpers import execute_commit, fetch_all_dicts, fetch_one_dict, fetch_scalar


def _build_user_search_filters(search: Optional[str]) -> tuple[str, tuple[str, ...]]:
    """Build a shared WHERE clause for user search."""
    if not search:
        return "", ()

    keyword = f"%{search}%"
    return (
        " WHERE username LIKE ? OR full_name LIKE ? OR CAST(telegram_id AS TEXT) LIKE ?",
        (keyword, keyword, keyword),
    )


async def get_user_by_telegram_id(telegram_id: int) -> Optional[dict]:
    """Fetch a user by Telegram ID."""
    return await fetch_one_dict("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))


async def get_user_by_id(user_id: int) -> Optional[dict]:
    """Fetch a user by internal ID."""
    db = await get_db()
    cursor = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def create_user(
    telegram_id: int,
    username: Optional[str] = None,
    full_name: Optional[str] = None,
) -> dict:
    """Create a user and return the stored row."""
    cursor = await execute_commit(
        """INSERT OR IGNORE INTO users (telegram_id, username, full_name)
           VALUES (?, ?, ?)""",
        (telegram_id, username, full_name),
    )
    if cursor.lastrowid and cursor.rowcount > 0:
        return await get_user_by_id(cursor.lastrowid)  # type: ignore[return-value]
    return await get_user_by_telegram_id(telegram_id)  # type: ignore[return-value]


async def update_user(
    user_id: int,
    username: Optional[str] = None,
    full_name: Optional[str] = None,
) -> None:
    """Update mutable profile fields."""
    await execute_commit(
        """UPDATE users
           SET username = COALESCE(?, username),
               full_name = COALESCE(?, full_name),
               updated_at = datetime('now', '+7 hours')
           WHERE id = ?""",
        (username, full_name, user_id),
    )


async def set_admin(user_id: int, is_admin: int = 1) -> None:
    """Grant or revoke admin role."""
    await execute_commit(
        "UPDATE users SET is_admin = ?, updated_at = datetime('now', '+7 hours') WHERE id = ?",
        (is_admin, user_id),
    )


async def set_discount_disabled(user_id: int, disable_discounts: int = 1) -> None:
    """Enable or disable discounts for a user."""
    await execute_commit(
        "UPDATE users SET disable_discounts = ?, updated_at = datetime('now', '+7 hours') WHERE id = ?",
        (disable_discounts, user_id),
    )


async def set_banned(user_id: int, is_banned: int = 1) -> None:
    """Ban or unban a user."""
    await execute_commit(
        "UPDATE users SET is_banned = ?, updated_at = datetime('now', '+7 hours') WHERE id = ?",
        (is_banned, user_id),
    )


async def get_all_users(
    offset: int = 0,
    limit: int = 50,
    search: Optional[str] = None,
) -> list[dict]:
    """Return paginated users."""
    where_clause, search_params = _build_user_search_filters(search)
    query = f"SELECT * FROM users{where_clause} ORDER BY id DESC LIMIT ? OFFSET ?"
    return await fetch_all_dicts(query, (*search_params, limit, offset))


async def count_users(search: Optional[str] = None) -> int:
    """Count users."""
    where_clause, search_params = _build_user_search_filters(search)
    total = await fetch_scalar(f"SELECT COUNT(*) FROM users{where_clause}", search_params)
    return int(total or 0)


async def get_all_user_telegram_ids() -> list[int]:
    """Return Telegram IDs for non-banned users."""
    db = await get_db()
    cursor = await db.execute("SELECT telegram_id FROM users WHERE is_banned = 0")
    rows = await cursor.fetchall()
    return [row[0] for row in rows]
