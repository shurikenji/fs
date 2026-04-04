import unittest

from app.log_pricing import enrich_logs_payload
from app.schemas import NormalizedGroup, NormalizedModel, NormalizedPricing, PricingMode


def _sample_pricing() -> NormalizedPricing:
    return NormalizedPricing(
        server_id="server-1",
        server_name="Server 1",
        models=[
            NormalizedModel(
                model_name="gpt-4o-mini",
                pricing_mode=PricingMode.token,
                input_price_per_1m=0.15,
                output_price_per_1m=0.6,
            )
        ],
        groups=[
            NormalizedGroup(
                name="优质gemini",
                display_name="Premium Gemini",
                ratio=1.0,
            )
        ],
        fetched_at="2026-04-04T00:00:00Z",
    )


class EnrichLogsPayloadTests(unittest.TestCase):
    def test_uses_catalog_group_label_when_model_has_no_group_snapshot(self) -> None:
        payload = {
            "items": [
                {
                    "created_at": "2026-04-04T06:00:28Z",
                    "model_name": "gpt-4o-mini",
                    "group": "优质gemini",
                    "prompt_tokens": 15,
                    "completion_tokens": 369,
                }
            ]
        }

        enriched = enrich_logs_payload(payload, _sample_pricing())
        item = enriched["items"][0]

        self.assertEqual(item["group_display_name"], "Premium Gemini")
        self.assertEqual(item["matched_group_display_name"], "Premium Gemini")

    def test_falls_back_to_static_sanitizer_without_pricing(self) -> None:
        enriched = enrich_logs_payload(
            [{"model_name": "gemini-2.5-flash-lite-nothinking", "group": "优质gemini"}],
            None,
        )

        self.assertEqual(enriched[0]["group_display_name"], "Premium gemini")
