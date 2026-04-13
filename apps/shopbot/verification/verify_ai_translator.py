"""Verification for AI translator fallback and cache/merge behavior."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from bot.services.ai_translator import AITranslator


async def main() -> None:
    translator = AITranslator()
    translator.enabled = True
    translator.api_key = "test-key"

    fallback_name = translator._fallback_english_text("\u5b98\u65b9 \u9ad8\u5e76\u53d1 \u5206\u7ec4")
    assert fallback_name == "Official High Concurrency Group"
    print("[OK] _fallback_english_text converts known CJK labels into English fallback text")

    sanitized = translator._sanitize_translation_payload(
        {
            "\u5b98\u65b9\u9ad8\u5e76\u53d1": {
                "name_en": "\u5b98\u65b9\u9ad8\u5e76\u53d1",
                "desc_en": "",
            }
        },
        [
            {
                "name": "\u5b98\u65b9\u9ad8\u5e76\u53d1",
                "translation_source": "\u5b98\u65b9 \u9ad8\u5e76\u53d1 \u6e20\u9053",
            }
        ],
    )
    assert sanitized["\u5b98\u65b9\u9ad8\u5e76\u53d1"]["name_en"] == "Official High Concurrency"
    assert sanitized["\u5b98\u65b9\u9ad8\u5e76\u53d1"]["desc_en"] == "Official High Concurrency Route"
    print("[OK] _sanitize_translation_payload removes CJK from fallback English fields")

    assert translator._needs_translation_refresh(
        {
            "name": "\u5b98\u65b9\u9ad8\u5e76\u53d1",
            "translation_source": "\u5b98\u65b9 \u9ad8\u5e76\u53d1 \u6e20\u9053",
        },
        {
            "name_en": "Official High Concurrency Route",
            "name_vi": "Tuyen chinh thuc tai cao",
            "desc_en": "Official high concurrency route",
        },
    )
    print("[OK] _needs_translation_refresh invalidates old context-derived group names")

    async def _fake_get_cached_translations(group_names: list[str], api_type: str) -> dict[str, dict]:
        _ = (group_names, api_type)
        return {
            "cached-group": {
                "name_en": "Cached Group",
                "name_vi": "Nh\u00f3m cache",
                "category": "OpenAI",
                "desc_en": "Cached description",
                "desc_vi": "M\u00f4 t\u1ea3 cache",
            }
        }

    async def _fake_call_ai(groups: list[dict], api_type: str) -> dict[str, dict]:
        _ = api_type
        assert [group["name"] for group in groups] == ["fresh-group"]
        return {
            "fresh-group": {
                "name_en": "Fresh Group",
                "name_vi": "Nh\u00f3m m\u1edbi",
                "category": "Other",
                "desc_en": "Fresh description",
                "desc_vi": "M\u00f4 t\u1ea3 m\u1edbi",
            }
        }

    saved_translations: dict[str, dict] = {}

    async def _fake_save_translations(translations: dict[str, dict], api_type: str) -> None:
        _ = api_type
        saved_translations.update(translations)

    translator._get_cached_translations = _fake_get_cached_translations  # type: ignore[method-assign]
    translator._call_ai = _fake_call_ai  # type: ignore[method-assign]
    translator._save_translations = _fake_save_translations  # type: ignore[method-assign]

    translated = await translator.translate_groups(
        [
            {"name": "cached-group", "desc": "cached desc"},
            {"name": "fresh-group", "desc": "fresh desc"},
        ],
        "newapi",
    )
    translated_map = {group["name"]: group for group in translated}

    assert translated_map["cached-group"]["label_vi"] == "Nh\u00f3m cache"
    assert translated_map["fresh-group"]["label_en"] == "Fresh Group"
    assert saved_translations["fresh-group"]["name_vi"] == "Nh\u00f3m m\u1edbi"
    print("[OK] translate_groups merges cached and fresh translations without external API calls")

    translator.enabled = False
    cached_only = await translator.translate_groups(
        [{"name": "cached-group", "desc": "cached desc"}],
        "newapi",
    )
    assert cached_only[0]["label_en"] == "Cached Group"
    print("[OK] translate_groups still applies cached translations when AI is disabled")

    print("\n=== AI TRANSLATOR VERIFICATION PASSED ===")


asyncio.run(main())
