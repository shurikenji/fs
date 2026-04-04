"""Translation cache queries."""
from __future__ import annotations

from db.database import get_db


async def get_cached_translations(
    names: list[str], server_type: str
) -> dict[str, dict]:
    if not names:
        return {}
    db = await get_db()
    placeholders = ", ".join("?" * len(names))
    cursor = await db.execute(
        f"""SELECT original_name, name_en, desc_en, category
            FROM translation_cache
            WHERE original_name IN ({placeholders}) AND server_type = ?""",
        (*names, server_type),
    )
    rows = await cursor.fetchall()
    return {
        row[0]: {"name_en": row[1], "desc_en": row[2], "category": row[3]}
        for row in rows
    }


async def save_translations(
    translations: dict[str, dict], server_type: str
) -> None:
    if not translations:
        return
    db = await get_db()
    for name, t in translations.items():
        await db.execute(
            """INSERT INTO translation_cache
               (original_name, server_type, name_en, desc_en, category, updated_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(original_name, server_type) DO UPDATE
               SET name_en = excluded.name_en,
                   desc_en = excluded.desc_en,
                   category = excluded.category,
                   updated_at = excluded.updated_at""",
            (name, server_type, t.get("name_en"), t.get("desc_en"), t.get("category", "Other")),
        )
    await db.commit()


async def count_cached_translations() -> int:
    db = await get_db()
    cursor = await db.execute("SELECT COUNT(*) FROM translation_cache")
    row = await cursor.fetchone()
    return int(row[0]) if row else 0


async def get_cached_text_translations(
    texts: list[str],
    server_type: str,
    text_type: str,
) -> dict[str, str]:
    if not texts:
        return {}
    db = await get_db()
    placeholders = ", ".join("?" * len(texts))
    cursor = await db.execute(
        f"""SELECT original_text, text_en
            FROM text_translation_cache
            WHERE original_text IN ({placeholders})
              AND server_type = ?
              AND text_type = ?""",
        (*texts, server_type, text_type),
    )
    rows = await cursor.fetchall()
    return {
        str(row[0] or ""): str(row[1] or "")
        for row in rows
        if str(row[0] or "").strip()
    }


async def save_text_translations(
    translations: dict[str, str],
    server_type: str,
    text_type: str,
) -> None:
    if not translations:
        return
    db = await get_db()
    for original_text, text_en in translations.items():
        await db.execute(
            """INSERT INTO text_translation_cache
               (original_text, text_type, server_type, text_en, updated_at)
               VALUES (?, ?, ?, ?, datetime('now'))
               ON CONFLICT(original_text, text_type, server_type) DO UPDATE
               SET text_en = excluded.text_en,
                   updated_at = excluded.updated_at""",
            (original_text, text_type, server_type, text_en),
        )
    await db.commit()
