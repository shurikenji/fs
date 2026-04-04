import unittest
from unittest.mock import AsyncMock, patch

from app.schemas import NormalizedPricing
from app.sync_service import refresh_enabled_server_snapshots, refresh_server_snapshot


def _sample_pricing() -> NormalizedPricing:
    return NormalizedPricing(
        server_id="server-1",
        server_name="Server 1",
        models=[],
        groups=[],
        fetched_at="2026-03-28T00:00:00Z",
    )


class RefreshServerSnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_refreshes_groups_and_translation_cache(self) -> None:
        pricing = _sample_pricing()
        with (
            patch("app.sync_service.get_server", AsyncMock(return_value={"id": "server-1", "type": "newapi"})),
            patch("app.sync_service.fetch_pricing", AsyncMock(return_value=pricing)) as fetch_mock,
            patch("app.sync_service.ensure_server_group_catalog", AsyncMock()) as groups_mock,
            patch("app.sync_service.warm_translation_cache", AsyncMock(return_value=6)) as warm_mock,
        ):
            result = await refresh_server_snapshot("server-1", trigger="auto")

        fetch_mock.assert_awaited_once_with("server-1", force=True, trigger="auto")
        groups_mock.assert_awaited_once()
        warm_mock.assert_awaited_once_with(pricing, "newapi")
        self.assertEqual(result.pricing, pricing)
        self.assertEqual(result.translated_count, 6)

    async def test_returns_empty_result_when_fetch_fails(self) -> None:
        with (
            patch("app.sync_service.get_server", AsyncMock(return_value={"id": "server-1", "type": "newapi"})),
            patch("app.sync_service.fetch_pricing", AsyncMock(return_value=None)),
            patch("app.sync_service.ensure_server_group_catalog", AsyncMock()) as groups_mock,
            patch("app.sync_service.warm_translation_cache", AsyncMock()) as warm_mock,
        ):
            result = await refresh_server_snapshot("server-1", trigger="manual")

        self.assertIsNone(result.pricing)
        self.assertEqual(result.translated_count, 0)
        groups_mock.assert_not_awaited()
        warm_mock.assert_not_awaited()

    async def test_refreshes_all_enabled_servers(self) -> None:
        with (
            patch(
                "app.sync_service.get_enabled_servers",
                AsyncMock(return_value=[{"id": "a"}, {"id": "b"}]),
            ),
            patch("app.sync_service.refresh_server_snapshot", AsyncMock()) as refresh_mock,
        ):
            await refresh_enabled_server_snapshots(trigger="auto")

        self.assertEqual(refresh_mock.await_count, 2)
        refresh_mock.assert_any_await("a", trigger="auto")
        refresh_mock.assert_any_await("b", trigger="auto")
