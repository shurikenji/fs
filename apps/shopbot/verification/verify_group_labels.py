"""Verification for translated group labels used in bot displays."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from db.database import close_db
import bot.utils.group_labels as group_labels
from bot.utils.group_labels import format_group_display_names


async def main() -> None:
    server = {
        "api_type": "newapi",
        "groups_cache": (
            '[{"name":"premium","label_en":"Premium"},'
            '{"name":"vip","label_en":"Priority"},'
            '{"name":"basic","label_en":""}]'
        ),
    }

    translated = await format_group_display_names("premium,vip", server)
    assert translated == "Premium, Priority"
    print("[OK] format_group_display_names prefers English labels from server cache")

    untranslated = await format_group_display_names("basic", server)
    assert untranslated == "basic"
    print("[OK] format_group_display_names falls back to original names when no translation exists")

    mixed_groups = (
        "gemini-cli,default,企业级高可用大模型,优质banana,Codex专属,"
        "MJ慢速,优质gemini,纯AZ,逆向,限时特价"
    )
    translated_mixed = await format_group_display_names(mixed_groups, {"api_type": "newapi"})
    assert translated_mixed == (
        "gemini-cli, default, Enterprise High Availability Model Pool, "
        "Premium banana, Codex Dedicated, MJ Slow, Premium gemini, "
        "Pure AZ, Reverse, Limited Time Discount"
    )
    print("[OK] format_group_display_names rewrites untranslated CJK group names for Telegram display")

    class _FakeTranslator:
        is_configured = True

        async def translate_groups(self, groups: list[dict], api_type: str) -> list[dict]:
            _ = api_type
            return [
                {
                    **group,
                    "label_en": "AI Backfilled Group",
                    "name_en": "AI Backfilled Group",
                }
                for group in groups
            ]

    original_get_translator = group_labels.get_translator

    async def _fake_get_translator() -> _FakeTranslator:
        return _FakeTranslator()

    group_labels.get_translator = _fake_get_translator  # type: ignore[assignment]
    try:
        ai_backfilled = await format_group_display_names(
            "\u6d4b\u8bd5AI\u56de\u586b",
            {"api_type": "newapi"},
        )
        assert ai_backfilled == "AI Backfilled Group"
        print("[OK] format_group_display_names backfills missing translations through AI before rendering")
    finally:
        group_labels.get_translator = original_get_translator  # type: ignore[assignment]

    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
