"""Runtime application settings stored in SQLite."""
from __future__ import annotations

from db.database import get_db


async def get_setting(key: str, default: str = "") -> str:
    db = await get_db()
    cursor = await db.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
    row = await cursor.fetchone()
    if not row:
        return default
    return str(row[0] or default)


async def get_settings_dict(defaults: dict[str, str] | None = None) -> dict[str, str]:
    db = await get_db()
    cursor = await db.execute("SELECT key, value FROM app_settings")
    rows = await cursor.fetchall()
    data = dict(defaults or {})
    for row in rows:
        data[str(row[0])] = str(row[1] or "")
    return data


async def set_setting(key: str, value: str) -> None:
    db = await get_db()
    await db.execute(
        """
        INSERT INTO app_settings (key, value, updated_at)
        VALUES (?, ?, datetime('now'))
        ON CONFLICT(key) DO UPDATE
        SET value = excluded.value,
            updated_at = excluded.updated_at
        """,
        (key, value),
    )
    await db.commit()
