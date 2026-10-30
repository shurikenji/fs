"""Read sanitized key inventory from the ARM key-vault worker."""
from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

import aiohttp

from bot.config import settings

logger = logging.getLogger(__name__)


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
