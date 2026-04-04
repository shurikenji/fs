"""Server-aware parser/display profile resolution."""
from __future__ import annotations

import json
from typing import Any

from app.server_profile_registry import (
    get_default_endpoint_alias_map,
    get_known_server_profile,
)


def parse_endpoint_alias_map(raw: Any) -> dict[str, dict[str, str]]:
    if not raw:
        return {}
    payload = raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        try:
            payload = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
    if not isinstance(payload, dict):
        return {}

    aliases: dict[str, dict[str, str]] = {}
    for key, value in payload.items():
        normalized_key = str(key or "").strip()
        if not normalized_key:
            continue
        if isinstance(value, dict):
            aliases[normalized_key] = {
                "label": str(value.get("label") or "").strip(),
                "public_path": str(value.get("public_path") or value.get("path") or "").strip(),
                "method": str(value.get("method") or "").strip().upper(),
            }
            continue
        if isinstance(value, str):
            aliases[normalized_key] = {
                "label": "",
                "public_path": value.strip(),
                "method": "",
            }
    return aliases


def _merge_alias_maps(*maps: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    merged: dict[str, dict[str, str]] = {}
    for source in maps:
        for key, value in (source or {}).items():
            normalized_key = str(key or "").strip()
            if not normalized_key:
                continue
            merged[normalized_key] = {
                "label": str(value.get("label") or "").strip(),
                "public_path": str(value.get("public_path") or "").strip(),
                "method": str(value.get("method") or "").strip().upper(),
            }
    return merged


def fingerprint_parser_id(server: dict[str, Any], pricing_raw: Any | None = None) -> str:
    server_type = str(server.get("type") or "newapi").strip().lower() or "newapi"
    if server_type == "custom":
        return "custom_manual"
    if server_type == "rixapi":
        return "rixapi_inline"

    if isinstance(pricing_raw, dict):
        data = pricing_raw.get("data")
        if (
            isinstance(data, list)
            and isinstance(pricing_raw.get("group_ratio"), dict)
            and isinstance(pricing_raw.get("supported_endpoint"), dict)
            and isinstance(pricing_raw.get("vendors"), list)
        ):
            return "yunwu_pricing_new"
        raw_data = pricing_raw.get("data", pricing_raw)
        if isinstance(raw_data, dict) and isinstance(raw_data.get("group_info"), dict):
            return "rixapi_inline"

    return "newapi_standard"


def resolve_server_profile(server: dict[str, Any], pricing_raw: Any | None = None) -> dict[str, Any]:
    explicit_parser = str(server.get("parser_override") or "").strip()
    explicit_display = str(server.get("display_profile") or "").strip()
    explicit_variant_mode = str(server.get("variant_pricing_mode") or "").strip()
    explicit_aliases = parse_endpoint_alias_map(server.get("endpoint_aliases_json"))

    known = get_known_server_profile(str(server.get("id") or "").strip())
    parser_id = explicit_parser or str(known.get("parser_id") or "").strip() or fingerprint_parser_id(server, pricing_raw)
    display_profile = explicit_display or str(known.get("display_profile") or "").strip() or "flat"
    variant_pricing_mode = explicit_variant_mode or str(known.get("variant_pricing_mode") or "").strip()

    endpoint_alias_map = _merge_alias_maps(get_default_endpoint_alias_map(), explicit_aliases)
    return {
        "parser_id": parser_id,
        "display_profile": display_profile,
        "variant_pricing_mode": variant_pricing_mode,
        "endpoint_alias_map": endpoint_alias_map,
    }


def _load_cached_pricing_payload(server: dict[str, Any]) -> Any | None:
    raw = str(server.get("pricing_cache") or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def describe_server_profile(server: dict[str, Any]) -> dict[str, Any]:
    return resolve_server_profile(server, _load_cached_pricing_payload(server))
