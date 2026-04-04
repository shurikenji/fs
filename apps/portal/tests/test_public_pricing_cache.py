import unittest
from unittest.mock import AsyncMock, patch

from app.public_pricing_cache import clear_public_pricing_cache, get_cached_public_pricing
from app.schemas import NormalizedPricing


def _sample_pricing(fetched_at: str = "2026-04-04T00:00:00Z") -> NormalizedPricing:
    return NormalizedPricing(
        server_id="server-1",
        server_name="Server 1",
        models=[],
        groups=[],
        fetched_at=fetched_at,
    )


def _sample_server(updated_at: str = "2026-04-04 00:00:00") -> dict:
    return {
        "id": "server-1",
        "type": "newapi",
        "updated_at": updated_at,
        "pricing_fetched_at": "2026-04-04 00:00:00",
        "groups_fetched_at": "2026-04-04 00:00:00",
        "quota_multiple": 1.0,
        "manual_groups": "",
        "hidden_groups": "",
        "excluded_models": "",
    }


class PublicPricingCacheTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        clear_public_pricing_cache()

    async def test_reuses_cached_public_pricing_when_key_is_unchanged(self) -> None:
        pricing = _sample_pricing()
        server = _sample_server()
        built = pricing.model_copy(update={"server_name": "Cached"})

        with patch(
            "app.public_pricing_cache.build_public_pricing",
            AsyncMock(return_value=built),
        ) as build_mock:
            first = await get_cached_public_pricing(pricing, server)
            second = await get_cached_public_pricing(pricing, server)

        self.assertIs(first, built)
        self.assertIs(second, built)
        build_mock.assert_awaited_once_with(pricing, server)

    async def test_rebuilds_when_pricing_snapshot_changes(self) -> None:
        server = _sample_server()
        first_pricing = _sample_pricing("2026-04-04T00:00:00Z")
        second_pricing = _sample_pricing("2026-04-04T00:01:00Z")
        first_built = first_pricing.model_copy(update={"server_name": "First"})
        second_built = second_pricing.model_copy(update={"server_name": "Second"})

        with patch(
            "app.public_pricing_cache.build_public_pricing",
            AsyncMock(side_effect=[first_built, second_built]),
        ) as build_mock:
            first = await get_cached_public_pricing(first_pricing, server)
            second = await get_cached_public_pricing(second_pricing, server)

        self.assertIs(first, first_built)
        self.assertIs(second, second_built)
        self.assertEqual(build_mock.await_count, 2)
