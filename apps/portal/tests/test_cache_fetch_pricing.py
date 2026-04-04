import json
import unittest
from unittest.mock import AsyncMock, patch

from app.cache import fetch_pricing
from app.schemas import NormalizedPricing


def _sample_pricing(server_name: str = "Server 1") -> NormalizedPricing:
    return NormalizedPricing(
        server_id="server-1",
        server_name=server_name,
        models=[],
        groups=[],
        fetched_at="2026-04-05T00:00:00Z",
    )


class FetchPricingPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_scaled_cached_pricing_without_upstream_fetch(self) -> None:
        cached = _sample_pricing()
        server = {"id": "server-1", "quota_multiple": 1.0}

        with (
            patch("app.cache.get_server", AsyncMock(return_value=server)),
            patch("app.cache.get_cached_pricing", return_value=cached) as cached_mock,
            patch("app.cache.fetch_and_store_pricing", AsyncMock()) as store_mock,
        ):
            result = await fetch_pricing("server-1")

        self.assertEqual(result, cached)
        cached_mock.assert_called_once_with("server-1")
        store_mock.assert_not_awaited()

    async def test_returns_snapshot_when_upstream_fetch_fails(self) -> None:
        snapshot = _sample_pricing("Snapshot")
        server = {
            "id": "server-1",
            "quota_multiple": 1.0,
            "pricing_cache": snapshot.model_dump_json(),
        }

        with (
            patch("app.cache.get_server", AsyncMock(return_value=server)),
            patch("app.cache.get_cached_pricing", return_value=None),
            patch(
                "app.cache.fetch_and_store_pricing",
                AsyncMock(side_effect=RuntimeError("upstream down")),
            ) as store_mock,
        ):
            result = await fetch_pricing("server-1", force=True)

        self.assertEqual(result, snapshot)
        store_mock.assert_awaited_once()

    async def test_skips_upstream_when_not_allowed_and_no_snapshot_exists(self) -> None:
        server = {
            "id": "server-1",
            "quota_multiple": 1.0,
            "pricing_cache": json.dumps(""),
        }

        with (
            patch("app.cache.get_server", AsyncMock(return_value=server)),
            patch("app.cache.get_cached_pricing", return_value=None),
            patch("app.cache.fetch_and_store_pricing", AsyncMock()) as store_mock,
        ):
            result = await fetch_pricing("server-1", allow_upstream=False)

        self.assertIsNone(result)
        store_mock.assert_not_awaited()
