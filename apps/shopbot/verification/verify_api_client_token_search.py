"""Verification for token-search response normalization."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import bot.services.api_clients.base as base_module
from bot.services.api_clients.newapi import NewAPIClient


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def get(self, url, *, params=None, headers=None, timeout=None):
        _ = headers, timeout
        self.calls.append({"url": url, "params": params})
        payload = self._responses.pop(0)
        return _FakeResponse(payload)


async def main() -> None:
    server = {
        "name": "Verify Search Server",
        "base_url": "https://api.kksj.org",
        "auth_type": "header",
        "user_id_header": "new-api-user",
        "access_token": "secret",
    }
    client = NewAPIClient()

    fake_session = _FakeSession(
        [
            "keyword required",
            {
                "data": {
                    "page": 1,
                    "page_size": 10,
                    "total": 1,
                    "items": [
                        {
                            "id": 12164,
                            "key": "DkB3**********aUiQ",
                            "name": "key_arju7c5b",
                            "remain_quota": 4500000,
                            "used_quota": 0,
                        }
                    ],
                },
                "message": "",
                "success": True,
            },
        ]
    )

    original_client_session = base_module.aiohttp.ClientSession
    base_module.aiohttp.ClientSession = lambda: fake_session
    try:
        token = await client.search_token(
            server,
            "sk-DkB3wUqxxMwcJgrMmNqlp3OcZchvNq6dAt30I4gxfUcpaUiQ",
        )
        assert token is not None
        assert token["id"] == 12164
        assert token["remain_quota"] == 4500000
        assert len(fake_session.calls) == 2
        assert fake_session.calls[0]["params"]["token"].startswith("sk-")
        assert fake_session.calls[1]["params"]["token"] == "DkB3wUqxxMwcJgrMmNqlp3OcZchvNq6dAt30I4gxfUcpaUiQ"
        print("[OK] search_token handles non-dict fallback responses and paginated item payloads")
    finally:
        base_module.aiohttp.ClientSession = original_client_session


asyncio.run(main())
