"""Verify bank feed errors are distinguishable and do not leak credentials."""
import sys
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import AsyncMock, patch

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bot.services import mbbank
from bot.services import bank_receipt_ingest, payment_poller


class BankFeedTests(unittest.IsolatedAsyncioTestCase):
    def test_amount_rejects_ambiguous_or_non_integer_values(self):
        self.assertEqual(mbbank._parse_amount(31000), 31000)
        self.assertEqual(mbbank._parse_amount("31,000"), 31000)
        self.assertEqual(mbbank._parse_amount("31.000"), 31000)
        for value in ("31.50", "1,23", "-10", 1.5, True, 2**63):
            self.assertEqual(mbbank._parse_amount(value), 0)

    async def test_http_failure_does_not_log_secret(self):
        class FailedSession:
            async def __aenter__(self):
                raise aiohttp.ClientConnectionError("https://bank.invalid/private-api-key")

            async def __aexit__(self, *args):
                return False

        with patch.object(mbbank, "_get_mb_config", AsyncMock(return_value={"api_url": "https://bank.invalid", "api_key": "private-api-key"})), \
             patch.object(mbbank.aiohttp, "ClientSession", return_value=FailedSession()), \
             self.assertLogs(mbbank.logger, level="ERROR") as logs:
            self.assertIsNone(await mbbank.fetch_transactions())
        self.assertNotIn("private-api-key", "\n".join(logs.output))

    async def test_empty_success_is_not_an_error(self):
        class Response:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): return False
            def raise_for_status(self): return None
            async def json(self): return {"status": "success", "transactions": []}

        class Session:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): return False
            def get(self, *args, **kwargs): return Response()

        with patch.object(mbbank, "_get_mb_config", AsyncMock(return_value={"api_url": "https://bank.invalid", "api_key": "key"})), \
             patch.object(mbbank.aiohttp, "ClientSession", return_value=Session()):
            self.assertEqual(await mbbank.fetch_transactions(), [])

    async def test_poller_ingests_even_when_no_orders_are_pending(self):
        config = SimpleNamespace(mb_account_no="", mb_verified_account_no="123", mb_verified_feed_timezone="Asia/Ho_Chi_Minh")
        with patch.object(payment_poller, "env_settings", config), \
             patch.object(payment_poller, "_expire_old_orders", AsyncMock()), \
             patch.object(payment_poller, "get_setting", AsyncMock(return_value="123")), \
             patch.object(payment_poller, "_load_recent_transactions", AsyncMock(return_value=[])), \
             patch.object(payment_poller, "_load_pending_qr_orders", AsyncMock(return_value=[])), \
             patch.object(bank_receipt_ingest, "ingest_transactions", AsyncMock()) as ingest, \
             patch.object(bank_receipt_ingest, "reconcile_unmatched_receipts", AsyncMock()):
            await payment_poller._poll_cycle(None)
        ingest.assert_awaited_once_with([], account_identity="123", account_verified=True)


if __name__ == "__main__":
    unittest.main()
