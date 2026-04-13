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
    assert translated == "Premium, Vip"
    print("[OK] format_group_display_names derives display labels from original ASCII names instead of stale cache labels")

    untranslated = await format_group_display_names("basic", server)
    assert untranslated == "Basic"
    print("[OK] format_group_display_names falls back to original names when no translation exists")

    normalized_ascii = await format_group_display_names(
        "Gemini-Vertex",
        {
            "api_type": "newapi",
            "groups_cache": '[{"name":"Gemini-Vertex","label_en":"Gemini - Vertex Ai Channel"}]',
        },
    )
    assert normalized_ascii == "Gemini-Vertex"
    print("[OK] format_group_display_names prefers original ASCII names over cached description labels")

    normalized_cjk = await format_group_display_names(
        "Claude\u4e13\u7528",
        {
            "api_type": "newapi",
            "groups_cache": '[{"name":"Claude\\u4e13\\u7528","label_en":"Dedicated Route"}]',
        },
    )
    assert normalized_cjk == "Claude Dedicated"
    print("[OK] format_group_display_names rejects stale context-derived labels for CJK groups")

    mixed_groups = (
        "gemini-cli,default,\u4f01\u4e1a\u7ea7\u9ad8\u53ef\u7528\u5927\u6a21\u578b,\u4f18\u8d28banana,Codex\u4e13\u5c5e,"
        "MJ\u6162\u901f,\u4f18\u8d28gemini,\u7eafAZ,\u9006\u5411,\u9650\u65f6\u7279\u4ef7"
    )
    translated_mixed = await format_group_display_names(mixed_groups, {"api_type": "newapi"})
    assert translated_mixed == (
        "gemini-cli, Default, Enterprise High Availability Model Pool, "
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
    original_get_cached_group_labels = group_labels._get_cached_group_labels

    async def _fake_get_translator() -> _FakeTranslator:
        return _FakeTranslator()

    async def _fake_get_cached_group_labels(group_names: list[str], api_type: str) -> dict[str, str]:
        _ = (group_names, api_type)
        return {}

    group_labels.get_translator = _fake_get_translator  # type: ignore[assignment]
    group_labels._get_cached_group_labels = _fake_get_cached_group_labels  # type: ignore[assignment]
    try:
        ai_backfilled = await format_group_display_names(
            "\u6d4b\u8bd5AI\u56de\u586b",
            {"api_type": "newapi"},
        )
        assert ai_backfilled == "AI"
        print("[OK] format_group_display_names backfills missing translations through AI before rendering")
    finally:
        group_labels.get_translator = original_get_translator  # type: ignore[assignment]
        group_labels._get_cached_group_labels = original_get_cached_group_labels  # type: ignore[assignment]

    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
