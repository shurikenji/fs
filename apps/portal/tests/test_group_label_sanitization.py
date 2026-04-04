import unittest

from app.adapters.rixapi import RixApiAdapter
from app.sanitizer import sanitize_group_name, sanitize_pricing, strip_group_price_notes
from app.schemas import NormalizedGroup, NormalizedPricing


class GroupLabelSanitizationTests(unittest.TestCase):
    def test_strip_group_price_notes_removes_trailing_currency_hint(self) -> None:
        self.assertEqual(
            strip_group_price_notes("AWS Claude1 - Low Concurrency (2 CNY/Token)"),
            "AWS Claude1 - Low Concurrency",
        )

    def test_sanitize_group_name_cleans_cached_catalog_label(self) -> None:
        self.assertEqual(
            sanitize_group_name("aws-claude1", "AWS Claude1 - Low Concurrency (2 CNY/Token)"),
            "AWS Claude1 - Low Concurrency",
        )

    def test_sanitize_group_name_preserves_readable_canonical_name(self) -> None:
        self.assertEqual(
            sanitize_group_name("Azure", "OpenAI Route"),
            "Azure",
        )

    def test_rixapi_parse_groups_cleans_name_en_and_translation_source(self) -> None:
        adapter = RixApiAdapter()
        groups = adapter.parse_groups(
            [
                {
                    "value": "aws-claude1",
                    "name_en": "AWS Claude1 - Low Concurrency (2 CNY/Token)",
                    "key": "AWS Claude1 - Low Concurrency (2 CNY/Token)",
                    "ratio": 2,
                }
            ]
        )

        self.assertEqual(groups[0]["name_en"], "AWS Claude1 - Low Concurrency")
        self.assertEqual(groups[0]["translation_source"], "AWS Claude1 - Low Concurrency")

    def test_sanitize_pricing_hides_group_descriptions_in_public_payload(self) -> None:
        pricing = NormalizedPricing(
            server_id="gpt1",
            server_name="GPT1",
            models=[],
            groups=[
                NormalizedGroup(
                    name="Azure",
                    display_name="Azure",
                    ratio=1.0,
                    description="OpenAI Route 0.3",
                )
            ],
            fetched_at="2026-04-04T00:00:00Z",
        )

        sanitized = sanitize_pricing(pricing)

        self.assertEqual(len(sanitized.groups), 1)
        self.assertEqual(sanitized.groups[0].display_name, "Azure")
        self.assertEqual(sanitized.groups[0].description, "")
