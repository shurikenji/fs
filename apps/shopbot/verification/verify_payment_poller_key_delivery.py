"""Verification for key delivery extraction, key-by-id lookup, and masked fallback handling."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from bot.services import payment_poller


class _NestedKeyClient:
    async def create_token(self, **kwargs):
        _ = kwargs
        return {"success": True, "data": {"token": {"key": "abc123456789"}}}

    def extract_created_token_id(self, payload):
        _ = payload
        return None

    def supports_key_lookup_by_id(self, server: dict) -> bool:
        _ = server
        return False

    async def resolve_token_key_by_id(self, server: dict, token_id: int):
        _ = server, token_id
        raise AssertionError("resolve_token_key_by_id should not run when create_token already returns full key")

    async def search_token_by_name(self, server: dict, name: str):
        _ = server, name
        raise AssertionError("search_token_by_name should not be used when create_token returns a full key")


class _IdLookupClient:
    async def create_token(self, **kwargs):
        _ = kwargs
        return {"success": True, "data": {"id": 202, "name": "created-token"}}

    def extract_created_token_id(self, payload):
        return payload["data"]["id"]

    def supports_key_lookup_by_id(self, server: dict) -> bool:
        return bool(server.get("supports_key_lookup_by_id"))

    async def resolve_token_key_by_id(self, server: dict, token_id: int):
        assert server["supports_key_lookup_by_id"] == 1
        assert token_id == 202
        return "sk-id-lookup-key-202"

    async def search_token_by_name(self, server: dict, name: str):
        _ = server, name
        raise AssertionError("legacy search fallback should not run when key lookup by id is enabled")


class _MaskedFallbackClient:
    async def create_token(self, **kwargs):
        _ = kwargs
        return {"success": True, "data": {"id": 101, "name": "created-token"}}

    def extract_created_token_id(self, payload):
        return payload["data"]["id"]

    def supports_key_lookup_by_id(self, server: dict) -> bool:
        return bool(server.get("supports_key_lookup_by_id"))

    async def resolve_token_key_by_id(self, server: dict, token_id: int):
        _ = server, token_id
        return None

    async def search_token_by_name(self, server: dict, name: str):
        _ = server, name
        return {
            "success": True,
            "data": {
                "items": [
                    {
                        "id": 101,
                        "key": "DkB3**********aUiQ",
                        "name": "created-token",
                    }
                ]
            },
        }


class _SearchIdLookupClient:
    async def create_token(self, **kwargs):
        _ = kwargs
        return {"success": True, "data": {"name": "created-token"}}

    def extract_created_token_id(self, payload):
        if isinstance(payload, dict):
            if isinstance(payload.get("id"), int):
                return payload["id"]
            data = payload.get("data")
            if isinstance(data, dict) and isinstance(data.get("id"), int):
                return data["id"]
        return None

    def supports_key_lookup_by_id(self, server: dict) -> bool:
        return bool(server.get("supports_key_lookup_by_id"))

    async def resolve_token_key_by_id(self, server: dict, token_id: int):
        assert server["supports_key_lookup_by_id"] == 1
        assert token_id == 303
        return "sk-id-from-search-303"

    async def search_token_by_name(self, server: dict, name: str):
        _ = server, name
        return {
            "id": 303,
            "key": "masked**********303",
            "name": "created-token",
        }


async def main() -> None:
    nested_key, nested_token_id = await payment_poller._create_key_with_retry(
        _NestedKeyClient(),
        server={"name": "Verify Server"},
        quota=1,
        group_name="default",
        base_token_name="verify",
        sequence=1,
    )
    assert nested_key == "sk-abc123456789"
    assert nested_token_id is None
    print("[OK] _create_key_with_retry returns full keys from nested create responses")

    looked_up_key, looked_up_token_id = await payment_poller._create_key_with_retry(
        _IdLookupClient(),
        server={"name": "Verify Server", "supports_key_lookup_by_id": 1},
        quota=1,
        group_name="default",
        base_token_name="verify",
        sequence=2,
    )
    assert looked_up_key == "sk-id-lookup-key-202"
    assert looked_up_token_id == 202
    print("[OK] _create_key_with_retry prefers token-id lookup for upgraded NewAPI servers")

    searched_id_key, searched_id_token_id = await payment_poller._create_key_with_retry(
        _SearchIdLookupClient(),
        server={"name": "Verify Server", "supports_key_lookup_by_id": 1},
        quota=1,
        group_name="default",
        base_token_name="verify",
        sequence=4,
    )
    assert searched_id_key == "sk-id-from-search-303"
    assert searched_id_token_id == 303
    print("[OK] _create_key_with_retry resolves full key by token id recovered from search results")

    extracted = payment_poller._extract_created_key(
        {
            "success": True,
            "data": {
                "records": [
                    {"api_key": "sk-record-key-1234567890"},
                ]
            },
        }
    )
    assert extracted == "sk-record-key-1234567890"
    assert (
        payment_poller._extract_created_key(
            {
                "success": True,
                "data": {
                    "items": [
                        {"key": "DkB3**********aUiQ"},
                    ]
                },
            }
        )
        == ""
    )
    print("[OK] _extract_created_key walks nested payloads and rejects masked values")

    try:
        await payment_poller._create_key_with_retry(
            _MaskedFallbackClient(),
            server={"name": "Verify Server", "supports_key_lookup_by_id": 0},
            quota=1,
            group_name="default",
            base_token_name="verify",
            sequence=3,
        )
    except payment_poller._MaskedDeliveryDataError:
        print("[OK] _create_key_with_retry refuses masked fallback key data after a successful create")
        return

    raise AssertionError("Expected _MaskedDeliveryDataError when only masked fallback data is available")


asyncio.run(main())
