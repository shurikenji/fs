"""Short-lived cache for sanitized public pricing payloads."""
from __future__ import annotations

import time

from app.schemas import NormalizedPricing
from app.translation_service import build_public_pricing

_CACHE_TTL_SECONDS = 60
_cache: dict[str, tuple[float, str, NormalizedPricing]] = {}


def _public_pricing_cache_key(pricing: NormalizedPricing, server: dict) -> str:
    return "|".join(
        [
            str(pricing.server_id or ""),
            str(pricing.fetched_at or ""),
            str(server.get("pricing_fetched_at") or ""),
            str(server.get("groups_fetched_at") or ""),
            str(server.get("updated_at") or ""),
            str(server.get("quota_multiple") or ""),
            str(server.get("manual_groups") or ""),
            str(server.get("hidden_groups") or ""),
            str(server.get("excluded_models") or ""),
            str(server.get("type") or ""),
            str(server.get("parser_override") or ""),
            str(server.get("display_profile") or ""),
            str(server.get("endpoint_aliases_json") or ""),
            str(server.get("variant_pricing_mode") or ""),
        ]
    )


async def get_cached_public_pricing(
    pricing: NormalizedPricing,
    server: dict,
) -> NormalizedPricing:
    """Return public pricing from cache when the snapshot/config key is unchanged."""
    server_id = str(server.get("id") or pricing.server_id or "").strip()
    if not server_id:
        return await build_public_pricing(pricing, server)

    now = time.time()
    cache_key = _public_pricing_cache_key(pricing, server)
    cached = _cache.get(server_id)
    if cached and cached[1] == cache_key and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[2]

    public_pricing = await build_public_pricing(pricing, server)
    _cache[server_id] = (now, cache_key, public_pricing)
    return public_pricing


def clear_public_pricing_cache(server_id: str | None = None) -> None:
    if server_id is None:
        _cache.clear()
        return
    _cache.pop(str(server_id), None)
