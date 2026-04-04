"""
db/database.py - Quản lý kết nối `aiosqlite` dạng singleton.
Dùng một connection duy nhất cho toàn bộ ứng dụng và mở lại khi cần.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

_db: aiosqlite.Connection | None = None
_lock = asyncio.Lock()


async def _is_connection_alive(connection: aiosqlite.Connection) -> bool:
    """Kiểm tra nhanh xem connection hiện tại còn dùng được hay không."""
    try:
        await connection.execute("SELECT 1")
        return True
    except Exception:
        return False


async def _configure_connection(connection: aiosqlite.Connection) -> aiosqlite.Connection:
    """Áp dụng các PRAGMA và row factory chuẩn cho connection."""
    await connection.execute("PRAGMA journal_mode=WAL")
    await connection.execute("PRAGMA foreign_keys=ON")
    connection.row_factory = aiosqlite.Row
    return connection


async def _open_connection() -> aiosqlite.Connection:
    """Mở connection mới từ `settings.db_path`."""
    from bot.config import settings

    db_path = Path(settings.db_path)
    logger.info("Opening database: %s", db_path)
    connection = await aiosqlite.connect(str(db_path))
    return await _configure_connection(connection)


async def get_db() -> aiosqlite.Connection:
    """Lấy singleton database connection, mở lại nếu connection cũ đã chết."""
    global _db

    if _db is not None and await _is_connection_alive(_db):
        return _db

    async with _lock:
        if _db is not None and await _is_connection_alive(_db):
            return _db

        _db = await _open_connection()
        return _db


async def close_db() -> None:
    """Đóng database connection hiện tại nếu có."""
    global _db

    if _db is None:
        return

    await _db.close()
    _db = None
    logger.info("Database connection closed.")
