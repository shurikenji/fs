"""
Compatibility wrapper for legacy NewAPI helpers.

Runtime code should prefer `bot.services.api_clients`, but this module keeps the
old public functions available for older scripts and tests.
"""
from __future__ import annotations

from typing import Any, Optional

from bot.services.api_clients.newapi import NewAPIClient

_CLIENT = NewAPIClient()


async def get_groups(server: dict) -> dict[str, Any]:
    """
    Return groups in the legacy dict shape:
    {
        "Azure": {"desc": "...", "ratio": 0.3},
        ...
    }
    """
    groups = await _CLIENT.get_groups(server)
    result: dict[str, Any] = {}
    for group in groups:
        name = str(group.get("name") or "").strip()
        if not name:
            continue
        result[name] = {
            "desc": group.get("desc", ""),
            "ratio": group.get("ratio", 1.0),
        }
    return result


async def create_token(
    server: dict,
    quota: int,
    group: str,
    name: str,
    expired_time: int = -1,
) -> Optional[dict]:
    """Legacy wrapper for creating a token on a NewAPI server."""
    return await _CLIENT.create_token(
        server,
        quota,
        group,
        name,
        expired_time=expired_time,
    )


async def search_token(
    server: dict,
    api_key: str,
) -> Optional[dict]:
    """Legacy wrapper for searching a token by API key."""
    return await _CLIENT.search_token(server, api_key)


async def search_token_by_name(
    server: dict,
    name: str,
) -> Optional[dict]:
    """Legacy wrapper for searching a token by name."""
    return await _CLIENT.search_token_by_name(server, name)


async def update_token(
    server: dict,
    token_id: int,
    remain_quota: int,
    name: Optional[str] = None,
    group: Optional[str] = None,
) -> Optional[dict]:
    """Legacy wrapper for updating a token quota."""
    return await _CLIENT.update_token(
        server,
        token_id,
        remain_quota,
        name=name,
        group=group,
    )


async def get_token_quota(server: dict, api_key: str) -> Optional[int]:
    """Return the current remain_quota for a token, if found."""
    token = await search_token(server, api_key)
    if token:
        return token.get("remain_quota")
    return None


__all__ = [
    "get_groups",
    "create_token",
    "search_token",
    "search_token_by_name",
    "update_token",
    "get_token_quota",
]
