"""Public registry helpers with local snapshot fallback for portal pages."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx

from app.config import get_settings
from db.queries.servers import get_public_servers

logger = logging.getLogger(__name__)

_BASE_DIR = Path(__file__).resolve().parent.parent
_DATA_DIR = _BASE_DIR / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_CACHE_TTL_SECONDS = 60
_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _snapshot_path(name: str) -> Path:
    return _DATA_DIR / name


def _read_snapshot(name: str) -> list[dict[str, Any]]:
    path = _snapshot_path(name)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to read portal snapshot %s: %s", path, exc)
        return []
    return data if isinstance(data, list) else []


def _write_snapshot(name: str, items: list[dict[str, Any]]) -> None:
    path = _snapshot_path(name)
    path.write_text(json.dumps(items, ensure_ascii=True, indent=2), encoding="utf-8")


async def _fetch_public_list(cache_key: str, endpoint: str, response_key: str, snapshot_name: str) -> list[dict[str, Any]]:
    now = time.time()
    cached = _cache.get(cache_key)
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    settings = get_settings()
    base_url = settings.control_plane_url.rstrip("/")
    if base_url:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{base_url}{endpoint}")
                response.raise_for_status()
                payload = response.json()
            items = payload.get(response_key, [])
            if isinstance(items, list):
                normalized = [item for item in items if isinstance(item, dict)]
                _write_snapshot(snapshot_name, normalized)
                _cache[cache_key] = (now, normalized)
                return normalized
        except Exception as exc:
            logger.warning("Portal public registry fetch failed for %s: %s", endpoint, exc)

    snapshot = _read_snapshot(snapshot_name)
    if snapshot:
        _cache[cache_key] = (now, snapshot)
        return snapshot

    return []


async def load_public_balance_sources() -> list[dict[str, Any]]:
    return [
        {
            "id": item["id"],
            "name": item["name"],
        }
        for item in await load_balance_runtime_sources()
    ]


async def load_balance_runtime_sources() -> list[dict[str, Any]]:
    now = time.time()
    cached = _cache.get("balance-runtime-sources")
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    servers = await get_public_servers("balance")
    normalized: list[dict[str, Any]] = []
    for server in servers:
        base_url_value = str(server.get("base_url") or "").strip()
        if not base_url_value:
            continue
        normalized.append(
            {
                "id": str(server["id"]).strip(),
                "name": str(server.get("name") or server["id"]).strip(),
                "base_url": base_url_value.rstrip("/"),
                "rate": float(server.get("balance_rate") or 1.0) or 1.0,
            }
        )

    _cache["balance-runtime-sources"] = (now, normalized)
    return normalized


async def load_public_proxy_status() -> list[dict[str, Any]]:
    items = await _fetch_public_list(
        "proxy-status",
        "/api/public/status",
        "proxies",
        "public_proxy_status.json",
    )
    normalized: list[dict[str, Any]] = []
    for item in items:
        proxy_id = str(item.get("id") or "").strip()
        if not proxy_id:
            continue
        normalized.append(
            {
                "id": proxy_id,
                "name": str(item.get("name") or proxy_id).strip(),
                "domain": str(item.get("domain") or "").strip(),
                "status": str(item.get("status") or "unknown").strip(),
            }
        )
    return normalized
