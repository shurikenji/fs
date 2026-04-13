import unittest

from app.schemas import NormalizedGroup, NormalizedPricing
from app.translation_groups import (
    apply_group_translation_map,
    build_fallback_group_translations,
    build_group_translation_fields,
    collect_groups_for_translation,
    group_row_payload,
    needs_group_translation_refresh,
    sanitize_group_translation_payload,
    translate_group_rows_from_map,
)


def _sample_pricing() -> NormalizedPricing:
    return NormalizedPricing(
        server_id="server-1",
        server_name="Server 1",
        models=[],
        groups=[
            NormalizedGroup(
                name="azure",
                display_name="Azure 路线",
                ratio=1.0,
                description="官方稳定线路",
                category="Other",
            ),
            NormalizedGroup(
                name="openai",
                display_name="OpenAI",
                ratio=1.0,
                description="",
                category="General",
            ),
        ],
        fetched_at="2026-04-05T00:00:00Z",
    )


class TranslationGroupsTests(unittest.TestCase):
    def test_collect_groups_only_emits_cjk_candidates(self) -> None:
        self.assertEqual(
            collect_groups_for_translation(_sample_pricing()),
            [
                {
                    "original_name": "azure",
                    "display_name": "Azure 路线",
                    "description": "官方稳定线路",
                    "source_text": "azure",
                    "context_text": "官方稳定线路",
                }
            ],
        )

    def test_build_fields_normalizes_name_and_invalid_category(self) -> None:
        normalized = build_group_translation_fields(
            {
                "original_name": "azure",
                "display_name": "Azure 路线",
                "description": "官方稳定线路",
                "source_text": "azure",
                "context_text": "官方稳定线路",
            },
            {
                "name_en": "",
                "desc_en": "",
                "category": "Invalid",
            },
        )

        self.assertEqual(normalized["name_en"], "Azure")
        self.assertEqual(normalized["category"], "Other")

    def test_apply_translation_map_updates_matching_groups(self) -> None:
        translated = apply_group_translation_map(
            _sample_pricing(),
            {
                "azure": {
                    "name_en": "Azure Official",
                    "desc_en": "Official stable route",
                    "category": "Official",
                }
            },
        )

        self.assertEqual(translated.groups[0].display_name, "Azure")
        self.assertEqual(translated.groups[0].description, "Official stable route")
        self.assertEqual(translated.groups[0].category, "Official")
        self.assertEqual(translated.groups[1].display_name, "OpenAI")

    def test_translate_group_rows_from_map_fills_public_fields(self) -> None:
        rows = translate_group_rows_from_map(
            [
                {
                    "name": "azure",
                    "label_en": "Azure 路线",
                    "desc": "官方稳定线路",
                    "category": "",
                }
            ],
            {
                "azure": {
                    "name_en": "Azure Official",
                    "desc_en": "Official stable route",
                    "category": "Official",
                }
            },
        )

        self.assertEqual(rows[0]["name_en"], "Azure")
        self.assertEqual(rows[0]["desc_en"], "Official stable route")
        self.assertEqual(rows[0]["category"], "Official")

    def test_sanitize_payload_and_refresh_follow_group_rules(self) -> None:
        payload = group_row_payload(
            {
                "name": "aws-claude1",
                "label_en": "AWS Claude1 - Low Concurrency (2 CNY/Token)",
                "translation_source": "AWS Claude1 - Low Concurrency (2 CNY/Token)",
            }
        )
        sanitized = sanitize_group_translation_payload(
            {
                "aws-claude1": {
                    "name_en": "AWS Claude1 - Low Concurrency (2 CNY/Token)",
                    "desc_en": "",
                    "category": "Premium",
                }
            },
            [payload],
        )

        self.assertFalse(needs_group_translation_refresh(payload, sanitized["aws-claude1"]))
        self.assertEqual(
            build_fallback_group_translations([payload])["aws-claude1"]["name_en"],
            "aws-claude1",
        )

    def test_refresh_rejects_cached_name_derived_from_context(self) -> None:
        payload = group_row_payload(
            {
                "name": "官方高并发",
                "translation_source": "官方 高并发 渠道",
            }
        )

        self.assertTrue(
            needs_group_translation_refresh(
                payload,
                {
                    "name_en": "Official High Concurrency Route",
                    "desc_en": "Official high-concurrency route",
                    "category": "Official",
                },
            )
        )
