"""Verification for token-search response normalization."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

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
                            "key": "DkB3wUqxxMwcJgrMmNqlp3OcZchvNq6dAt30I4gxfUcpaUiQ",
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

        for raw in ("other-key", "DkB3**********aUiQ", "DkB3...aUiQ", "", None):
            assert base_module._match_token_from_items([{"key": raw}], requested_token="sk-DkB3fullaUiQ") is None
        assert base_module._match_token_from_items([{}], requested_token="") is None
        assert base_module._match_token_from_items([{"key": "sk-key…masked"}], requested_token="sk-key…masked") is None
        fake_session._responses = [{"success": True, "data": [{"id": 1, "key": "DkB3***aUiQ"}]}] * 3
        assert await client.search_token(server, "sk-DkB3fullaUiQ") is None
        server["supports_key_lookup_by_id"] = 1
        client.resolve_token_key_by_id = AsyncMock(return_value="sk-DkB3fullaUiQ")
        fake_session._responses = [{"success": True, "data": [{"id": 1, "key": "DkB3***aUiQ"}]}]
        assert (await client.search_token(server, "sk-DkB3fullaUiQ"))["id"] == 1
        client.resolve_token_key_by_id.assert_awaited_once_with(server, 1)
        client.resolve_token_key_by_id = AsyncMock(return_value="sk-another-key")
        fake_session._responses = [{"success": True, "data": [{"id": 1, "key": "DkB3***aUiQ"}]}] * 3
        assert await client.search_token(server, "sk-DkB3fullaUiQ") is None
        client.resolve_token_key_by_id.assert_awaited_once_with(server, 1)
        client.resolve_token_key_by_id = AsyncMock(return_value="sk-another-key")
        fake_session._responses = [{"success": True, "data": [{"id": i, "key": "masked***key"} for i in range(1, 8)]}] * 3
        assert await client.search_token(server, "sk-DkB3fullaUiQ") is None
        assert client.resolve_token_key_by_id.await_count == 3
        print("[OK] token matching rejects wrong, masked, missing and empty keys")
        print("[OK] masked results require full-key verification on compatible servers")
    finally:
        base_module.aiohttp.ClientSession = original_client_session


asyncio.run(main())
