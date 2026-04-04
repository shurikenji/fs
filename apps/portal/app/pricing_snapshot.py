"""Canonical pricing snapshot fetch and persistence."""
from __future__ import annotations

import logging
import time

from app.adapters import get_adapter
from app.schemas import NormalizedPricing
from db.queries.servers import create_sync_log, update_server_cache

logger = logging.getLogger(__name__)


async def fetch_and_store_pricing(
    server_id: str,
    server: dict,
    *,
    trigger: str = "manual",
) -> NormalizedPricing:
    """Fetch canonical pricing from the adapter and persist the snapshot/logs."""
    adapter = get_adapter(server)
    started_at = time.perf_counter()

    try:
        pricing = await adapter.fetch_pricing(server)
        await update_server_cache(
            server_id,
            pricing_cache=pricing.model_dump_json(),
        )
        await create_sync_log(
            server_id,
            trigger=trigger,
            status="success",
            model_count=len(pricing.models),
            group_count=len(pricing.groups),
            duration_ms=int((time.perf_counter() - started_at) * 1000),
        )
        return pricing
    except Exception as exc:
        logger.error("Failed to fetch pricing for %s: %s", server_id, exc)
        await create_sync_log(
            server_id,
            trigger=trigger,
            status="failed",
            duration_ms=int((time.perf_counter() - started_at) * 1000),
            error_message=str(exc)[:500],
        )
        raise
