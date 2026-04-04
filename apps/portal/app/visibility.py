"""Server-level public visibility filters for groups, models, and logs."""
from __future__ import annotations

import json
from typing import Any, Callable, Iterable

from app.schemas import NormalizedPricing


def parse_visibility_names(raw: Any) -> list[str]:
    if raw is None:
        return []

    items: Iterable[Any]
    if isinstance(raw, list):
        items = raw
    else:
        text = str(raw).strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = None
        if isinstance(parsed, list):
            items = parsed
        else:
            items = [part.strip() for part in text.split(",")]

    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = str(item or "").strip()
        if value and value not in seen:
            seen.add(value)
            cleaned.append(value)
    return cleaned


def dump_visibility_names(items: Iterable[Any]) -> str:
    return json.dumps(parse_visibility_names(list(items)), ensure_ascii=False)


def hidden_group_names(server: dict[str, Any]) -> set[str]:
    return set(parse_visibility_names(server.get("hidden_groups")))


def excluded_model_names(server: dict[str, Any]) -> set[str]:
    return set(parse_visibility_names(server.get("excluded_models")))


def filter_group_rows(
    groups: list[dict[str, Any]],
    *,
    hidden_groups: set[str],
) -> list[dict[str, Any]]:
    return [
        group
        for group in groups
        if str(group.get("name") or "").strip()
        and str(group.get("name") or "").strip() not in hidden_groups
    ]


def split_visible_and_hidden_groups(
    group_names: list[str],
    *,
    hidden_groups: set[str],
) -> tuple[list[str], list[str]]:
    visible: list[str] = []
    hidden: list[str] = []
    for group_name in group_names:
        if group_name in hidden_groups:
            hidden.append(group_name)
        else:
            visible.append(group_name)
    return visible, hidden


def visibility_warning(hidden_groups: list[str]) -> str:
    if not hidden_groups:
        return ""
    return "Some groups currently assigned to this key are hidden by server visibility settings."


def apply_visibility_to_pricing(
    pricing: NormalizedPricing,
    *,
    hidden_groups: set[str],
    excluded_models: set[str],
) -> NormalizedPricing:
    visible_groups = [
        group
        for group in pricing.groups
        if group.name not in hidden_groups
    ]
    visible_group_names = {group.name for group in visible_groups}

    visible_models = []
    for model in pricing.models:
        if model.model_name in excluded_models:
            continue

        original_group_refs = set(model.enable_groups) | set(model.group_prices)
        filtered_enable_groups = [
            group_name
            for group_name in model.enable_groups
            if group_name in visible_group_names
        ]
        filtered_group_prices = {
            group_name: snapshot
            for group_name, snapshot in model.group_prices.items()
            if group_name in visible_group_names
        }
        filtered_variants = []
        for variant in model.pricing_variants:
            variant_enable_groups = [
                group_name
                for group_name in variant.enable_groups
                if group_name in visible_group_names
            ]
            variant_group_prices = {
                group_name: snapshot
                for group_name, snapshot in variant.group_prices.items()
                if group_name in visible_group_names
            }
            if (variant.enable_groups or variant.group_prices) and not variant_enable_groups and not variant_group_prices:
                continue
            filtered_variants.append(
                variant.model_copy(
                    update={
                        "enable_groups": variant_enable_groups,
                        "group_prices": variant_group_prices,
                    }
                )
            )

        if original_group_refs and not filtered_enable_groups and not filtered_group_prices:
            continue

        visible_models.append(
            model.model_copy(
                update={
                    "enable_groups": filtered_enable_groups,
                    "group_prices": filtered_group_prices,
                    "pricing_variants": filtered_variants,
                }
            )
        )

    return pricing.model_copy(
        update={
            "groups": visible_groups,
            "models": visible_models,
        }
    )


def filter_logs_payload(
    payload: Any,
    *,
    hidden_groups: set[str],
    excluded_models: set[str],
) -> Any:
    if isinstance(payload, list):
        return [
            item for item in payload
            if _is_visible_log(item, hidden_groups=hidden_groups, excluded_models=excluded_models)
        ]

    if not isinstance(payload, dict):
        return payload

    items, replace_items = _extract_log_items(payload)
    if items is not None and replace_items is not None:
        filtered = [
            item for item in items
            if _is_visible_log(item, hidden_groups=hidden_groups, excluded_models=excluded_models)
        ]
        replace_items(filtered)
        _update_log_totals(payload, len(filtered))

    available_groups = payload.get("available_groups")
    if isinstance(available_groups, list):
        payload["available_groups"] = [
            item
            for item in available_groups
            if str(item.get("name") or "").strip() not in hidden_groups
        ]
    return payload


def _is_visible_log(
    item: Any,
    *,
    hidden_groups: set[str],
    excluded_models: set[str],
) -> bool:
    if not isinstance(item, dict):
        return False

    model_name = str(item.get("model_name") or item.get("model") or "").strip()
    if model_name and model_name in excluded_models:
        return False

    group_name = str(item.get("group") or "").strip()
    if group_name and group_name in hidden_groups:
        return False
    return True


def _extract_log_items(
    payload: dict[str, Any],
) -> tuple[list[dict[str, Any]] | None, Callable[[list[dict[str, Any]]], None] | None]:
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


def _update_log_totals(payload: dict[str, Any], total: int) -> None:
    for key in ("total", "count"):
        if isinstance(payload.get(key), (int, float)):
            payload[key] = total

    for key in ("data", "items", "rows", "records", "list", "logs"):
        value = payload.get(key)
        if not isinstance(value, dict):
            continue
        for subkey in ("total", "count"):
            if isinstance(value.get(subkey), (int, float)):
                value[subkey] = total
