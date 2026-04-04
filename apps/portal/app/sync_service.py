"""Shared server snapshot refresh orchestration."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.cache import fetch_pricing
from app.group_catalog import ensure_server_group_catalog
from app.schemas import NormalizedPricing
from app.translation_service import warm_translation_cache
from db.queries.servers import get_enabled_servers, get_server

logger = logging.getLogger(__name__)


@dataclass
class RefreshServerSnapshotResult:
    server_id: str
    pricing: NormalizedPricing | None = None
    translated_count: int = 0


async def refresh_server_snapshot(
    server_id: str,
    *,
    trigger: str = "manual",
) -> RefreshServerSnapshotResult:
    result = RefreshServerSnapshotResult(server_id=server_id)
    server = await get_server(server_id)
    if not server:
        return result

    pricing = await fetch_pricing(server_id, force=True, trigger=trigger)
    if not pricing:
        return result

    result.pricing = pricing

    try:
        await ensure_server_group_catalog(server, force=True)
    except Exception as exc:
        logger.warning("Group catalog refresh failed for %s: %s", server_id, exc)

    try:
        result.translated_count = await warm_translation_cache(
            pricing,
            str(server.get("type") or "newapi"),
        )
    except Exception as exc:
        logger.warning("Translation warm-up failed for %s: %s", server_id, exc)

    return result


async def refresh_enabled_server_snapshots(
    *,
    trigger: str = "manual",
) -> list[RefreshServerSnapshotResult]:
    results: list[RefreshServerSnapshotResult] = []
    for server in await get_enabled_servers():
        results.append(
            await refresh_server_snapshot(str(server["id"]), trigger=trigger)
        )
    return results
