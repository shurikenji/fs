"""Pricing-aware enrichment helpers for usage logs."""
from __future__ import annotations

from typing import Any, Callable

from app.sanitizer import sanitize_group_name
from app.schemas import NormalizedModel, NormalizedPricing, PricingMode


def enrich_logs_payload(payload: Any, pricing: NormalizedPricing | None, server: dict | None = None) -> dict | list:
    """Attach estimated cost and pricing metadata to upstream log payloads."""
    group_display_map = _build_group_display_map(pricing)
    if isinstance(payload, list):
        return [_enrich_log_item(item, pricing, server, group_display_map) for item in payload]

    if not isinstance(payload, dict):
        return {"items": [], "available_groups": []}

    items, replace_items = _extract_log_items(payload)
    if items is not None and replace_items is not None:
        replace_items([_enrich_log_item(item, pricing, server, group_display_map) for item in items])

    payload["available_groups"] = _build_available_groups(pricing)
    return payload


def _extract_log_items(
    payload: dict,
) -> tuple[list[dict] | None, Callable[[list[dict]], None] | None]:
    for key in ("data", "items", "rows", "records", "list", "logs"):
        value = payload.get(key)
        if isinstance(value, list):
            return value, lambda items, _key=key: payload.__setitem__(_key, items)
        if isinstance(value, dict):
            for subkey in ("logs", "items", "rows", "records", "list", "data"):
                subvalue = value.get(subkey)
                if isinstance(subvalue, list):
                    return subvalue, lambda items, _value=value, _subkey=subkey: _value.__setitem__(_subkey, items)
    return None, None


def _build_available_groups(pricing: NormalizedPricing | None) -> list[dict[str, Any]]:
    if not pricing:
        return []

    return [
        {
            "name": group.name,
            "display_name": sanitize_group_name(group.name, group.display_name),
            "ratio": group.ratio,
            "category": group.category,
        }
        for group in pricing.groups
    ]


def _build_group_display_map(pricing: NormalizedPricing | None) -> dict[str, str]:
    if not pricing:
        return {}

    return {
        group.name: sanitize_group_name(group.name, group.display_name)
        for group in pricing.groups
        if group.name
    }


def _resolve_group_display_name(group_name: str, group_display_map: dict[str, str]) -> str:
    if not group_name:
        return ""
    return group_display_map.get(group_name) or sanitize_group_name(group_name)


def _enrich_log_item(
    item: Any,
    pricing: NormalizedPricing | None,
    server: dict | None = None,
    group_display_map: dict[str, str] | None = None,
) -> Any:
    if not isinstance(item, dict):
        return item

    enriched = dict(item)
    model_name = str(item.get("model_name") or item.get("model") or "").strip()
    group_name = str(item.get("group") or "").strip()
    resolved_group_display_name = _resolve_group_display_name(group_name, group_display_map or {})
    if resolved_group_display_name:
        enriched["group_display_name"] = resolved_group_display_name
    matched_model = _find_model(pricing, model_name)

    if matched_model:
        group_price = matched_model.group_prices.get(group_name) if group_name else None
        estimated_cost_usd = _estimate_from_pricing(enriched, matched_model, group_price)
        if estimated_cost_usd is not None:
            enriched["estimated_cost_usd"] = estimated_cost_usd
            enriched["estimated_cost_display"] = f"${estimated_cost_usd:.6f}"

        pricing_mode = group_price.pricing_mode if group_price else matched_model.pricing_mode
        enriched["pricing_mode"] = pricing_mode.value
        if group_name:
            if group_price:
                enriched["matched_group_display_name"] = sanitize_group_name(
                    group_name,
                    group_price.group_display_name,
                )
            else:
                enriched["matched_group_display_name"] = resolved_group_display_name
            enriched["group_display_name"] = enriched["matched_group_display_name"]

        if group_price:
            enriched["input_price_per_1m"] = group_price.input_price_per_1m
            enriched["output_price_per_1m"] = group_price.output_price_per_1m
            enriched["request_price"] = group_price.request_price
            enriched["group_ratio"] = group_price.group_ratio
        else:
            enriched["input_price_per_1m"] = matched_model.input_price_per_1m
            enriched["output_price_per_1m"] = matched_model.output_price_per_1m
            enriched["request_price"] = matched_model.request_price
        return enriched

    fallback_cost = _estimate_from_raw_log(enriched, server)
    if fallback_cost is not None:
        enriched["estimated_cost_usd"] = fallback_cost
        enriched["estimated_cost_display"] = f"${fallback_cost:.6f}"
    return enriched


def _find_model(pricing: NormalizedPricing | None, model_name: str) -> NormalizedModel | None:
    if not pricing or not model_name:
        return None

    model_name_lower = model_name.lower()
    for model in pricing.models:
        if model.model_name == model_name:
            return model
    for model in pricing.models:
        if model.model_name.lower() == model_name_lower:
            return model
    return None


def _estimate_from_pricing(item: dict, model: NormalizedModel, group_price: Any) -> float | None:
    prompt_tokens = _to_float(item.get("prompt_tokens"))
    completion_tokens = _to_float(item.get("completion_tokens"))

    pricing_mode = group_price.pricing_mode if group_price else model.pricing_mode
    if pricing_mode == PricingMode.fixed:
        request_price = group_price.request_price if group_price else model.request_price
        return round(_to_float(request_price), 6) if request_price is not None else None

    if pricing_mode == PricingMode.token:
        input_price = group_price.input_price_per_1m if group_price else model.input_price_per_1m
        output_price = group_price.output_price_per_1m if group_price else model.output_price_per_1m
        if input_price is None and output_price is None:
            return None
        estimated = ((prompt_tokens / 1_000_000) * _to_float(input_price)) + (
            (completion_tokens / 1_000_000) * _to_float(output_price)
        )
        return round(estimated, 6)

    if pricing_mode == PricingMode.request_scaled:
        request_price = group_price.request_price if group_price else model.request_price
        if request_price is not None:
            return round(_to_float(request_price), 6)

    return None


def _estimate_from_raw_log(item: dict, server: dict | None = None) -> float | None:
    model_ratio = _to_float(item.get("model_ratio"))
    completion_ratio = _to_float(item.get("completion_ratio"), default=1.0)
    group_ratio = _to_float(item.get("group_ratio"), default=1.0)
    prompt_tokens = _to_float(item.get("prompt_tokens"))
    completion_tokens = _to_float(item.get("completion_tokens"))
    model_price = _to_float(item.get("model_price"))
    quota = _to_float(item.get("quota"))
    multiple = _server_multiple(server)

    if model_price > 0 and model_ratio == 0:
        return round((group_ratio * model_price) / multiple, 6)
    if model_ratio > 0:
        return round(group_ratio * model_ratio * (prompt_tokens + completion_tokens * completion_ratio) / (500000 * multiple), 6)
    if quota > 0:
        return round(quota / (500000 * multiple), 6)
    return None


def _server_multiple(server: dict | None) -> float:
    try:
        value = float((server or {}).get("quota_multiple") or 1.0)
    except (TypeError, ValueError):
        value = 1.0
    return value if value > 0 else 1.0


def _to_float(value: Any, *, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default
