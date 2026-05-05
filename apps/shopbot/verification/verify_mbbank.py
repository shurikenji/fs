"""Verification for the MBBank transaction client v3 contract."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from bot.config import settings
from db.database import close_db
from db.models import init_db
from db.queries.settings import set_setting


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self):
        return self.payload


class _FakeSession:
    def __init__(self, payload, calls: list[dict]):
        self.payload = payload
        self.calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def get(self, url, *, headers=None, timeout=None):
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "timeout_type": type(timeout).__name__ if timeout is not None else None,
            }
        )
        return _FakeResponse(self.payload)


async def main() -> None:
    original_db_path = settings.db_path

    with TemporaryDirectory() as temp_dir:
        temp_db = Path(temp_dir) / "mbbank.db"
        await close_db()
        object.__setattr__(settings, "db_path", str(temp_db))

        try:
            await init_db()

            from bot.services import mbbank

            await set_setting("mb_api_url", "https://api.apicanhan.com/transactions/MB/")
            await set_setting("mb_api_key", "demo-key")

            calls: list[dict] = []
            payload = {
                "status": "success",
                "message": "Thanh cong",
                "transactions": [
                    {
                        "transactionID": "FT26124726969839",
                        "amount": "31,000",
                        "transactionDate": "04/05/2026 15:58:47",
                        "type": "IN",
                        "description": "NGUYEN DUY TRONG ORDOHSWXRS4 FT26124167710760",
                    },
                    {
                        "transactionID": "FT26124726969840",
                        "amount": "99,000",
                        "transactionDate": "04/05/2026 16:00:00",
                        "type": "OUT",
                        "description": "Ignored outgoing transfer",
                    },
                ],
            }

            original_client_session = mbbank.aiohttp.ClientSession
            try:
                mbbank.aiohttp.ClientSession = lambda: _FakeSession(payload, calls)
                transactions = await mbbank.fetch_transactions()
            finally:
                mbbank.aiohttp.ClientSession = original_client_session

            assert calls and calls[0]["url"] == "https://api.apicanhan.com/transactions/MB/demo-key/?version=3"
            assert calls[0]["headers"] == {"Accept": "application/json"}
            assert calls[0]["timeout_type"] == "ClientTimeout"
            assert transactions == [
                {
                    "transactionID": "FT26124726969839",
                    "amount": 31000,
                    "description": "NGUYEN DUY TRONG ORDOHSWXRS4 FT26124167710760",
                    "transactionDate": "04/05/2026 15:58:47",
                }
            ]
            print("[OK] fetch_transactions builds the v3 URL and normalizes IN transactions")

            calls.clear()
            original_client_session = mbbank.aiohttp.ClientSession
            try:
                mbbank.aiohttp.ClientSession = lambda: _FakeSession({"status": "success", "transactions": {}}, calls)
                malformed = await mbbank.fetch_transactions()
            finally:
                mbbank.aiohttp.ClientSession = original_client_session

            assert malformed == []
            print("[OK] fetch_transactions returns [] when transactions payload is malformed")

            await set_setting("mb_api_key", "")
            missing_config = await mbbank.fetch_transactions()
            assert missing_config == []
            print("[OK] fetch_transactions returns [] when scanner config is incomplete")

            print("\n=== MBBANK VERIFICATION PASSED ===")
        finally:
            await close_db()
            object.__setattr__(settings, "db_path", original_db_path)


asyncio.run(main())
