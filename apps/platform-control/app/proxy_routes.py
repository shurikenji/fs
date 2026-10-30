"""Shared proxy route presets and validation for platform-control."""

from __future__ import annotations

import json
import re
from typing import Iterable


ROUTE_PRESETS: dict[str, tuple[str, ...]] = {
    "openai_compatible": ("/v1/",),
    "gemini_native": (
        "/v1beta/models",
        "/v1beta/files",
        "/upload/v1beta/files",
        "/v1beta/cachedContents",
        "/v1beta/batches",
        "/v1beta/fileSearchStores",
    ),
    "gemini_openai_compatible": ("/v1beta/openai/",),
    "newapi_billing": ("/dashboard/billing/",),
}

_RESERVED_PREFIXES = {"/", "/health", "/_internal/health"}
_INVALID_CHARS = re.compile(r"[\x00-\x20\\{};]")
_REGEX_META = set("[]()|+^$")


def json_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return json_list(parsed)


def normalize_prefix(prefix: str) -> str:
    value = str(prefix or "").strip()
    if not value.startswith("/"):
        raise ValueError(f"Route prefix must start with '/': {value!r}")
    if len(value) > 128:
        raise ValueError("Route prefix cannot exceed 128 characters")
    if "?" in value or "#" in value or ".." in value or "*" in value:
        raise ValueError(f"Route prefix contains a forbidden pattern: {value!r}")
    if _INVALID_CHARS.search(value):
        raise ValueError(f"Route prefix contains forbidden characters: {value!r}")
    if any(char in _REGEX_META for char in value):
        raise ValueError(f"Regex route expressions are not allowed: {value!r}")
    if (
        value in _RESERVED_PREFIXES
        or value.startswith("/_internal/")
        or value.startswith("/.well-known/")
        or value.startswith("/health/")
    ):
        raise ValueError(f"Reserved route prefix cannot be configured: {value!r}")
    return value


def validate_custom_prefixes(prefixes: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in prefixes:
        if not str(raw).strip():
            continue
        prefix = normalize_prefix(str(raw))
        if prefix not in seen:
            result.append(prefix)
            seen.add(prefix)
    if len(result) > 32:
        raise ValueError("A proxy cannot have more than 32 custom route prefixes")
    return result


def effective_prefixes(presets: Iterable[str], custom_prefixes: Iterable[str]) -> list[str]:
    selected = [str(item).strip() for item in presets if str(item).strip()]
    unknown = [item for item in selected if item not in ROUTE_PRESETS]
    if unknown:
        raise ValueError(f"Unknown route preset: {unknown[0]}")
    custom = validate_custom_prefixes(custom_prefixes)
    result: list[str] = []
    seen: set[str] = set()
    for prefix in [prefix for preset in selected for prefix in ROUTE_PRESETS[preset]] + custom:
        if prefix not in seen:
            result.append(prefix)
            seen.add(prefix)
    return result


def parse_custom_text(value: str) -> list[str]:
    return validate_custom_prefixes(value.replace(",", "\n").splitlines())


def has_broad_custom_prefix(prefixes: Iterable[str]) -> bool:
    return any(prefix.count("/") <= 2 for prefix in prefixes)


def route_policy(presets: object, custom_prefixes: object) -> dict[str, list[str]]:
    selected = json_list(presets)
    custom = validate_custom_prefixes(json_list(custom_prefixes))
    return {
        "presets": selected,
        "custom_prefixes": custom,
        "effective_prefixes": effective_prefixes(selected, custom),
    }


def connection_profiles(domain: str, policy: dict[str, list[str]]) -> list[dict[str, str]]:
    """Build public connection guides from the protocols enabled on one proxy."""
    base_url = f"https://{str(domain or '').strip().rstrip('/')}"
    profiles: list[dict[str, str]] = []
    presets = policy.get("presets", [])
    if "openai_compatible" in presets:
        profiles.append({"protocol": "openai", "base_url": f"{base_url}/v1"})
    if "gemini_native" in presets:
        profiles.append({"protocol": "gemini_native", "base_url": base_url})
    if "gemini_openai_compatible" in presets:
        profiles.append({"protocol": "gemini_openai", "base_url": f"{base_url}/v1beta/openai"})
    for prefix in policy.get("custom_prefixes", []):
        profiles.append({"protocol": "custom", "base_url": f"{base_url}{prefix.rstrip('/')}"})
    return profiles
