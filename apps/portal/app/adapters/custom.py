"""Custom adapter for manual/demo pricing snapshots."""
from __future__ import annotations

from datetime import datetime, timezone

from app.adapters.base import BaseAdapter
from app.schemas import NormalizedPricing


class CustomAdapter(BaseAdapter):
    """Serve pricing directly from stored snapshot data."""

    async def fetch_pricing(self, server: dict) -> NormalizedPricing:
        raw = server.get("pricing_cache")
        if raw:
            pricing = NormalizedPricing.model_validate_json(raw)
            if not pricing.server_id or not pricing.server_name:
                pricing = pricing.model_copy(update={
                    "server_id": server["id"],
                    "server_name": server["name"],
                })
            return pricing

        return NormalizedPricing(
            server_id=server["id"],
            server_name=server["name"],
            models=[],
            groups=[],
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )

    async def fetch_groups(self, server: dict) -> list[dict]:
        pricing = await self.fetch_pricing(server)
        return [
            {
                "name": group.name,
                "ratio": group.ratio,
                "desc": group.description,
                "translation_source": group.description or group.display_name or group.name,
            }
            for group in pricing.groups
        ]
