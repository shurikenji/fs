import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.routers.internal_admin_pricing import latest_sync_runs, sync_runs


class InternalAdminPricingSyncRunsTests(unittest.IsolatedAsyncioTestCase):
    async def test_sync_runs_serializes_runtime_rows(self) -> None:
        with patch(
            "app.routers.internal_admin_pricing.get_sync_runs",
            AsyncMock(
                return_value=[
                    {
                        "id": 7,
                        "server_id": "gpt1",
                        "status": "success",
                        "trigger": "auto",
                        "model_count": 317,
                        "group_count": 28,
                        "duration_ms": 698,
                        "error_message": "",
                        "created_at": "2026-04-14 06:58:44",
                    }
                ]
            ),
        ):
            payload = await sync_runs(
                x_pricing_admin_token="change-me",
                source_id="gpt1",
                status="success",
                trigger="auto",
                limit=50,
            )

        self.assertTrue(payload["success"])
        self.assertEqual(len(payload["runs"]), 1)
        self.assertEqual(
            payload["runs"][0],
            {
                "id": 7,
                "source_id": "gpt1",
                "status": "success",
                "trigger": "auto",
                "model_count": 317,
                "group_count": 28,
                "translated_count": None,
                "duration_ms": 698,
                "error_message": "",
                "created_at": "2026-04-14 06:58:44",
                "origin": "runtime",
            },
        )

    async def test_latest_sync_runs_serializes_map(self) -> None:
        with patch(
            "app.routers.internal_admin_pricing.get_latest_sync_map",
            AsyncMock(
                return_value={
                    "gpt1": {
                        "id": 9,
                        "server_id": "gpt1",
                        "status": "success",
                        "trigger": "auto",
                        "model_count": 317,
                        "group_count": 28,
                        "duration_ms": 700,
                        "error_message": "",
                        "created_at": "2026-04-14 06:58:44",
                    }
                }
            ),
        ):
            payload = await latest_sync_runs(x_pricing_admin_token="change-me")

        self.assertTrue(payload["success"])
        self.assertEqual(payload["latest"]["gpt1"]["origin"], "runtime")
        self.assertIsNone(payload["latest"]["gpt1"]["translated_count"])

    async def test_sync_runs_requires_admin_token(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await sync_runs(x_pricing_admin_token="wrong")
        self.assertEqual(ctx.exception.status_code, 401)
