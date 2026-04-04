"""
db/queries/settings.py — CRUD cho bảng settings (key-value store).
Được dùng để lưu cấu hình MB Bank, VietQR, Bot, v.v.
Ưu tiên: settings DB > .env fallback.
"""
from __future__ import annotations

from typing import Optional

from db.queries._helpers import execute_commit, fetch_all_dicts, fetch_scalar


async def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    """Lấy giá trị setting theo key."""
    value = await fetch_scalar("SELECT value FROM settings WHERE key = ?", (key,))
    if value:
        return str(value)
    return default


async def get_setting_int(key: str, default: int = 0) -> int:
    """Lấy setting dạng integer."""
    val = await get_setting(key)
    if val is not None:
        try:
            return int(val)
        except ValueError:
            pass
    return default


async def set_setting(key: str, value: str, description: Optional[str] = None) -> None:
    """Tạo hoặc cập nhật setting."""
    if description is not None:
        await execute_commit(
            """INSERT INTO settings (key, value, description, updated_at)
               VALUES (?, ?, ?, datetime('now', '+7 hours'))
               ON CONFLICT(key) DO UPDATE
               SET value = excluded.value,
                   description = excluded.description,
                   updated_at = datetime('now', '+7 hours')""",
            (key, value, description),
        )
        return

    await execute_commit(
        """INSERT INTO settings (key, value, updated_at)
           VALUES (?, ?, datetime('now', '+7 hours'))
           ON CONFLICT(key) DO UPDATE
           SET value = excluded.value,
               updated_at = datetime('now', '+7 hours')""",
        (key, value),
    )


async def get_all_settings() -> list[dict]:
    """Lấy tất cả settings."""
    return await fetch_all_dicts("SELECT * FROM settings ORDER BY key ASC")


async def get_settings_dict() -> dict[str, str]:
    """Lấy tất cả settings dưới dạng dict key→value."""
    settings = await get_all_settings()
    return {setting["key"]: setting["value"] for setting in settings}


async def delete_setting(key: str) -> None:
    """Xóa setting."""
    await execute_commit("DELETE FROM settings WHERE key = ?", (key,))
