import unittest
from unittest.mock import AsyncMock, patch

from app.pricing_admin import (
    _load_runtime_sync_state,
    _normalize_control_run,
    _normalize_runtime_run,
    _sort_sync_runs,
)


class PricingSyncHistoryHelpersTests(unittest.TestCase):
    def test_normalize_runtime_run_sets_origin_and_empty_translated_count(self) -> None:
        row = _normalize_runtime_run(
            {
                "id": 11,
                "source_id": "gpt1",
                "status": "success",
                "trigger": "auto",
                "model_count": 317,
                "group_count": 28,
                "duration_ms": 698,
                "error_message": "",
                "created_at": "2026-04-14 06:58:44",
            },
            {"gpt1": "GPT1"},
        )
        self.assertEqual(row["origin"], "runtime")
        self.assertEqual(row["source_name"], "GPT1")
        self.assertIsNone(row["translated_count"])

    def test_sort_sync_runs_prefers_latest_created_at(self) -> None:
        rows = _sort_sync_runs(
            [
                {"id": 1, "source_id": "gpt1", "created_at": "2026-04-14 06:13:20"},
                {"id": 2, "source_id": "gpt1", "created_at": "2026-04-14 06:58:44"},
                {"id": 3, "source_id": "gpt2", "created_at": "2026-04-14 06:43:36"},
            ]
        )
        self.assertEqual(rows[0]["id"], 2)
        self.assertEqual(rows[1]["id"], 3)
        self.assertEqual(rows[2]["id"], 1)

    def test_normalize_control_run_keeps_translated_count(self) -> None:
        row = _normalize_control_run(
            {
                "id": 3,
                "source_id": "gpt1",
                "status": "success",
                "trigger": "manual",
                "model_count": 317,
                "group_count": 28,
                "translated_count": 14,
                "duration_ms": 820,
                "error_message": "",
                "created_at": "2026-04-14 07:00:00",
            },
            {"gpt1": "GPT1"},
        )
        self.assertEqual(row["origin"], "control-plane")
        self.assertEqual(row["translated_count"], 14)


class RuntimeSyncStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_load_runtime_sync_state_returns_warning_on_client_error(self) -> None:
        with patch(
            "app.pricing_admin.pricing_get_sync_runs",
            AsyncMock(side_effect=RuntimeError("portal unavailable")),
        ):
            runs, latest, warning = await _load_runtime_sync_state()

        self.assertEqual(runs, [])
        self.assertEqual(latest, {})
        self.assertIn("portal unavailable", warning)

    async def test_load_runtime_sync_state_returns_payloads(self) -> None:
        with (
            patch(
                "app.pricing_admin.pricing_get_sync_runs",
                AsyncMock(return_value={"runs": [{"source_id": "gpt1", "status": "success"}]}),
            ),
            patch(
                "app.pricing_admin.pricing_get_latest_sync_runs",
                AsyncMock(return_value={"latest": {"gpt1": {"source_id": "gpt1", "status": "success"}}}),
            ),
        ):
            runs, latest, warning = await _load_runtime_sync_state(source_id="gpt1", trigger="auto")

        self.assertEqual(len(runs), 1)
        self.assertIn("gpt1", latest)
        self.assertEqual(warning, "")
