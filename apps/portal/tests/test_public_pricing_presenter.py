import unittest
from unittest.mock import AsyncMock, patch

from app.public_pricing_presenter import (
    catalog_matches_pricing_groups,
    prepare_public_pricing_presentation,
)
from app.sanitizer import sanitize_pricing
from app.schemas import NormalizedGroup, NormalizedPricing


def _sample_pricing() -> NormalizedPricing:
    return NormalizedPricing(
        server_id="server-1",
        server_name="Server 1",
        models=[],
        groups=[NormalizedGroup(name="g1", display_name="Group 1", ratio=1.0)],
        fetched_at="2026-04-05T00:00:00Z",
    )


class PublicPricingPresenterTests(unittest.IsolatedAsyncioTestCase):
    async def test_prepare_builds_visible_catalog_when_groups_match(self) -> None:
        pricing = _sample_pricing()
        server = {"id": "server-1", "hidden_groups": "", "excluded_models": ""}
        catalog_rows = [{"name": "g1", "label_en": "Group 1", "ratio": 1.0, "desc": "", "category": "General"}]

        with patch(
            "app.public_pricing_presenter.ensure_server_group_catalog",
            AsyncMock(return_value=catalog_rows),
        ):
            presentation = await prepare_public_pricing_presentation(pricing, server)

        self.assertEqual(presentation.hidden_groups, set())
        self.assertEqual(presentation.excluded_models, set())
        self.assertEqual(set((presentation.group_catalog or {}).keys()), {"g1"})

    async def test_prepare_drops_stale_catalog_when_groups_do_not_match(self) -> None:
        pricing = _sample_pricing()
        server = {"id": "server-1", "hidden_groups": "", "excluded_models": ""}
        stale_rows = [{"name": "other", "label_en": "Other", "ratio": 1.0, "desc": "", "category": "General"}]

        with patch(
            "app.public_pricing_presenter.ensure_server_group_catalog",
            AsyncMock(return_value=stale_rows),
        ):
            presentation = await prepare_public_pricing_presentation(pricing, server)

        self.assertIsNone(presentation.group_catalog)

    def test_catalog_match_helper_requires_overlap(self) -> None:
        pricing = _sample_pricing()
        self.assertTrue(catalog_matches_pricing_groups([{"name": "g1"}], pricing))
        self.assertFalse(catalog_matches_pricing_groups([{"name": "g2"}], pricing))

    def test_sanitize_pricing_prefers_original_ascii_name_when_catalog_label_is_description_based(self) -> None:
        pricing = NormalizedPricing(
            server_id="server-1",
            server_name="Server 1",
            models=[],
            groups=[NormalizedGroup(name="Gemini-Vertex", display_name="Gemini - Vertex Ai Channel", ratio=1.0)],
            fetched_at="2026-04-05T00:00:00Z",
        )

        sanitized = sanitize_pricing(
            pricing,
            group_catalog={
                "Gemini-Vertex": {
                    "name": "Gemini-Vertex",
                    "label_en": "Gemini - Vertex Ai Channel",
                    "ratio": 1.0,
                    "desc": "",
                    "category": "General",
                }
            },
        )

        self.assertEqual(sanitized.groups[0].display_name, "Gemini-Vertex")
