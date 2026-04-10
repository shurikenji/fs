"""Verification for key delivery extraction and masked fallback handling."""
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

    async def search_token_by_name(self, server: dict, name: str):
        _ = server, name
        raise AssertionError("search_token_by_name should not be used when create_token returns a full key")


class _MaskedFallbackClient:
    async def create_token(self, **kwargs):
        _ = kwargs
        return {"success": True, "data": {"id": 101, "name": "created-token"}}

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


async def main() -> None:
    nested_key = await payment_poller._create_key_with_retry(
        _NestedKeyClient(),
        server={"name": "Verify Server"},
        quota=1,
        group_name="default",
        base_token_name="verify",
        sequence=1,
    )
    assert nested_key == "sk-abc123456789"
    print("[OK] _create_key_with_retry returns full keys from nested create responses")

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
            server={"name": "Verify Server"},
            quota=1,
            group_name="default",
            base_token_name="verify",
            sequence=2,
        )
    except payment_poller._MaskedDeliveryDataError:
        print("[OK] _create_key_with_retry refuses masked fallback key data after a successful create")
        return

    raise AssertionError("Expected _MaskedDeliveryDataError when only masked fallback data is available")


asyncio.run(main())
