"""In-memory pricing cache with TTL and sync logging."""
from __future__ import annotations

import time

from app.adapters.base import compute_token_prices
from app.pricing_snapshot import fetch_and_store_pricing
from app.schemas import NormalizedPricing
from db.queries.servers import (
    get_enabled_servers,
    get_server,
)

_cache: dict[str, tuple[float, NormalizedPricing]] = {}
_DEFAULT_TTL = 300  # 5 minutes


def get_cached_pricing(server_id: str) -> NormalizedPricing | None:
    entry = _cache.get(server_id)
    if entry is None:
        return None
    ts, data = entry
    if time.time() - ts > _DEFAULT_TTL:
        del _cache[server_id]
        return None
    return data


def set_cached_pricing(server_id: str, data: NormalizedPricing) -> None:
    _cache[server_id] = (time.time(), data)


def _load_pricing_snapshot(server_id: str, server: dict) -> NormalizedPricing | None:
    raw = server.get("pricing_cache")
    if raw:
        try:
            pricing = NormalizedPricing.model_validate_json(raw)
            set_cached_pricing(server_id, pricing)
            return pricing
        except Exception:
            pass
    return None


def _server_multiple(server: dict) -> float:
    try:
        value = float(server.get("quota_multiple") or 1.0)
    except (TypeError, ValueError):
        value = 1.0
    return value if value > 0 else 1.0


def _scale_price(value: float | None, multiple: float) -> float | None:
    if value is None:
        return None
    return round(float(value) / multiple, 6)


def _apply_server_multiple(pricing: NormalizedPricing, server: dict) -> NormalizedPricing:
    multiple = _server_multiple(server)
    if abs(multiple - 1.0) < 1e-9:
        return pricing

    scaled_groups = [
        group.model_copy(update={"ratio": round(float(group.ratio or 0.0) / multiple, 6)})
        for group in pricing.groups
    ]
    raw_group_ratio_map = {group.name: float(group.ratio or 0.0) for group in pricing.groups}

    scaled_models = []
    for model in pricing.models:
        updates: dict[str, object] = {
            "input_price_per_1m": _scale_price(model.input_price_per_1m, multiple),
            "output_price_per_1m": _scale_price(model.output_price_per_1m, multiple),
            "cached_input_price_per_1m": _scale_price(model.cached_input_price_per_1m, multiple),
            "request_price": _scale_price(model.request_price, multiple),
        }

        scaled_group_prices = {}
        for group_name, snapshot in model.group_prices.items():
            raw_ratio = raw_group_ratio_map.get(group_name, float(snapshot.group_ratio or 1.0))
            effective_ratio = round(raw_ratio / multiple, 6)
            scaled_group_prices[group_name] = snapshot.model_copy(
                update={
                    "group_ratio": effective_ratio,
                    "input_price_per_1m": _scale_price(snapshot.input_price_per_1m, multiple),
                    "output_price_per_1m": _scale_price(snapshot.output_price_per_1m, multiple),
                    "cached_input_price_per_1m": _scale_price(snapshot.cached_input_price_per_1m, multiple),
                    "request_price": _scale_price(snapshot.request_price, multiple),
                }
            )
        updates["group_prices"] = scaled_group_prices

        scaled_variants = []
        for variant in model.pricing_variants:
            scaled_variant_group_prices = {}
            for group_name, snapshot in variant.group_prices.items():
                raw_ratio = raw_group_ratio_map.get(group_name, float(snapshot.group_ratio or 1.0))
                effective_ratio = round(raw_ratio / multiple, 6)
                scaled_variant_group_prices[group_name] = snapshot.model_copy(
                    update={
                        "group_ratio": effective_ratio,
                        "input_price_per_1m": _scale_price(snapshot.input_price_per_1m, multiple),
                        "output_price_per_1m": _scale_price(snapshot.output_price_per_1m, multiple),
                        "cached_input_price_per_1m": _scale_price(snapshot.cached_input_price_per_1m, multiple),
                        "request_price": _scale_price(snapshot.request_price, multiple),
                    }
                )
            scaled_variants.append(
                variant.model_copy(
                    update={
                        "input_price_per_1m": _scale_price(variant.input_price_per_1m, multiple),
                        "output_price_per_1m": _scale_price(variant.output_price_per_1m, multiple),
                        "cached_input_price_per_1m": _scale_price(variant.cached_input_price_per_1m, multiple),
                        "request_price": _scale_price(variant.request_price, multiple),
                        "group_prices": scaled_variant_group_prices,
                    }
                )
            )
        updates["pricing_variants"] = scaled_variants

        if model.pricing_mode.value == "token" and model.model_ratio > 0:
            scaled = compute_token_prices(
                model.model_ratio,
                max(float(model.completion_ratio or 0.0), 0.0),
                1.0 / multiple,
                model.cache_ratio,
            )
            updates["input_price_per_1m"] = scaled["input"]
            updates["output_price_per_1m"] = None if model.output_price_per_1m is None else scaled["output"]
            updates["cached_input_price_per_1m"] = scaled["cached"]

        scaled_models.append(model.model_copy(update=updates))

    return pricing.model_copy(update={"groups": scaled_groups, "models": scaled_models})


async def fetch_pricing(
    server_id: str,
    *,
    force: bool = False,
    trigger: str = "manual",
    allow_upstream: bool = True,
) -> NormalizedPricing | None:
    """Fetch pricing for a server, using cache if available."""
    server = await get_server(server_id)
    if not server:
        return None

    if not force:
        cached = get_cached_pricing(server_id)
        if cached:
            return _apply_server_multiple(cached, server)
        snapshot = _load_pricing_snapshot(server_id, server)
        if snapshot:
            return _apply_server_multiple(snapshot, server)
        if not allow_upstream:
            return None

    try:
        raw_pricing = await fetch_and_store_pricing(
            server_id,
            server,
            trigger=trigger,
        )
        set_cached_pricing(server_id, raw_pricing)
        return _apply_server_multiple(raw_pricing, server)
    except Exception:
        snapshot = _load_pricing_snapshot(server_id, server)
        if snapshot:
            return _apply_server_multiple(snapshot, server)
        return None


async def fetch_all_pricing() -> dict[str, NormalizedPricing]:
    """Fetch pricing for all enabled servers."""
    servers = await get_enabled_servers()
    result: dict[str, NormalizedPricing] = {}
    for server in servers:
        pricing = await fetch_pricing(server["id"])
        if pricing:
            result[server["id"]] = pricing
    return result
