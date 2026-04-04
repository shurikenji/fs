import unittest
from unittest.mock import AsyncMock, Mock, patch

from app.pricing_snapshot import fetch_and_store_pricing
from app.schemas import NormalizedPricing


def _sample_pricing() -> NormalizedPricing:
    return NormalizedPricing(
        server_id="server-1",
        server_name="Server 1",
        models=[],
        groups=[],
        fetched_at="2026-04-05T00:00:00Z",
    )


class FetchAndStorePricingTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetches_and_persists_successful_snapshot(self) -> None:
        pricing = _sample_pricing()
        adapter = Mock()
        adapter.fetch_pricing = AsyncMock(return_value=pricing)

        with (
            patch("app.pricing_snapshot.get_adapter", return_value=adapter) as get_adapter_mock,
            patch("app.pricing_snapshot.update_server_cache", AsyncMock()) as update_cache_mock,
            patch("app.pricing_snapshot.create_sync_log", AsyncMock()) as sync_log_mock,
        ):
            result = await fetch_and_store_pricing(
                "server-1",
                {"id": "server-1", "type": "newapi"},
                trigger="auto",
            )

        self.assertIs(result, pricing)
        get_adapter_mock.assert_called_once()
        adapter.fetch_pricing.assert_awaited_once()
        update_cache_mock.assert_awaited_once_with(
            "server-1",
            pricing_cache=pricing.model_dump_json(),
        )
        sync_log_mock.assert_awaited_once()
        self.assertEqual(sync_log_mock.await_args.kwargs["trigger"], "auto")
        self.assertEqual(sync_log_mock.await_args.kwargs["status"], "success")
        self.assertEqual(sync_log_mock.await_args.kwargs["model_count"], 0)
        self.assertEqual(sync_log_mock.await_args.kwargs["group_count"], 0)

    async def test_logs_failed_fetch_and_reraises(self) -> None:
        adapter = Mock()
        adapter.fetch_pricing = AsyncMock(side_effect=RuntimeError("boom"))

        with (
            patch("app.pricing_snapshot.get_adapter", return_value=adapter),
            patch("app.pricing_snapshot.update_server_cache", AsyncMock()) as update_cache_mock,
            patch("app.pricing_snapshot.create_sync_log", AsyncMock()) as sync_log_mock,
        ):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                await fetch_and_store_pricing(
                    "server-1",
                    {"id": "server-1", "type": "newapi"},
                    trigger="manual",
                )

        update_cache_mock.assert_not_awaited()
        sync_log_mock.assert_awaited_once()
        self.assertEqual(sync_log_mock.await_args.kwargs["status"], "failed")
        self.assertEqual(sync_log_mock.await_args.kwargs["trigger"], "manual")
        self.assertEqual(sync_log_mock.await_args.kwargs["error_message"], "boom")
