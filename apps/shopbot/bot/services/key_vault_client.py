"""Read sanitized key inventory from the ARM key-vault worker."""
from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any
from urllib.parse import quote

import aiohttp

from bot.config import settings

logger = logging.getLogger(__name__)


async def get_summary() -> list[dict[str, Any]] | None:
    if not settings.key_vault_url or not settings.key_vault_api_token:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{settings.key_vault_url.rstrip('/')}/internal/key-vault/summary",
                headers={"Authorization": f"Bearer {settings.key_vault_api_token}"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                response.raise_for_status()
                body = await response.json()
        sources = body.get("sources") if isinstance(body, dict) else None
        if not isinstance(sources, list) or any(not isinstance(row, dict) for row in sources):
            return None
        return sources
    except Exception as exc:
        logger.warning("Key-vault summary unavailable (%s)", type(exc).__name__)
        return None


async def get_inventory(source_id: str) -> list[dict[str, Any]] | None:
    if not settings.key_vault_url or not settings.key_vault_api_token or not source_id:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{settings.key_vault_url.rstrip('/')}/internal/key-vault/items/{quote(source_id, safe='')}",
                headers={"Authorization": f"Bearer {settings.key_vault_api_token}"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                response.raise_for_status()
                body = await response.json()
        items = body.get("items") if isinstance(body, dict) else None
        return items if isinstance(items, list) and all(isinstance(item, dict) for item in items) else None
    except Exception as exc:
        logger.warning("Key-vault inventory unavailable for source %s (%s)", source_id, type(exc).__name__)
        return None


async def get_runs(source_id: str) -> list[dict[str, Any]] | None:
    if not settings.key_vault_url or not settings.key_vault_api_token or not source_id:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{settings.key_vault_url.rstrip('/')}/internal/key-vault/runs/{quote(source_id, safe='')}",
                headers={"Authorization": f"Bearer {settings.key_vault_api_token}"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                response.raise_for_status()
                body = await response.json()
        runs = body.get("runs") if isinstance(body, dict) else None
        return runs if isinstance(runs, list) and all(isinstance(item, dict) for item in runs) else None
    except Exception as exc:
        logger.warning("Key-vault run history unavailable for source %s (%s)", source_id, type(exc).__name__)
        return None


async def get_item_detail(source_id: str, token_ref: str) -> dict[str, Any] | None:
    if not settings.key_vault_url or not settings.key_vault_api_token or not source_id or not token_ref:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{settings.key_vault_url.rstrip('/')}/internal/key-vault/item",
                params={"source_id": source_id, "token_ref": token_ref},
                headers={"Authorization": f"Bearer {settings.key_vault_api_token}"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                response.raise_for_status()
                body = await response.json()
        return body if isinstance(body, dict) else None
    except Exception as exc:
        logger.warning("Key-vault item detail unavailable for source %s (%s)", source_id, type(exc).__name__)
        return None


def _fingerprint(api_key: str) -> str:
    normalized = api_key.strip()
    if normalized and not normalized.startswith("sk-"):
        normalized = f"sk-{normalized}"
    return hmac.new(
        settings.key_vault_lookup_secret.encode(), normalized.encode(), hashlib.sha256
    ).hexdigest()


async def lookup_item(server: dict[str, Any], api_key: str, token_id: Any, token_name: Any) -> dict[str, Any] | None:
    source_id = str(server.get("control_plane_source_id") or "").strip()
    if not (settings.key_vault_url and settings.key_vault_api_token and settings.key_vault_lookup_secret and source_id):
        return None
    payload = {
        "source_id": source_id,
        "key_fingerprint": _fingerprint(api_key),
        "token_id": str(token_id or ""),
        "token_name": str(token_name or ""),
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{settings.key_vault_url.rstrip('/')}/internal/key-vault/lookup",
                json=payload,
                headers={"Authorization": f"Bearer {settings.key_vault_api_token}"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                response.raise_for_status()
                body = await response.json()
        item = body.get("item") if isinstance(body, dict) else None
        return item if isinstance(item, dict) else None
    except Exception as exc:
        logger.warning("Key-vault lookup degraded for source %s: %s", source_id, exc)
        return None
