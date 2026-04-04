"""Static registry data for server profile resolution."""
from __future__ import annotations

from typing import Any


_DEFAULT_ENDPOINT_ALIAS_MAP: dict[str, dict[str, str]] = {
    "1": {"label": "OpenAI Compatible", "public_path": "/v1/chat/completions", "method": "POST"},
    "openai": {"label": "OpenAI Compatible", "public_path": "/v1/chat/completions", "method": "POST"},
    "anthropic": {"label": "Anthropic Messages", "public_path": "/v1/messages", "method": "POST"},
    "openai-response": {"label": "OpenAI Responses", "public_path": "/v1/responses", "method": "POST"},
    "aigc-image": {"label": "AIGC Image", "method": "POST"},
    "aigc-video": {"label": "AIGC Video", "method": "POST"},
}

_SERVER_ID_PROFILES: dict[str, dict[str, Any]] = {
    "gpt2": {
        "parser_id": "rixapi_inline",
        "display_profile": "flat",
        "variant_pricing_mode": "",
    },
}


def get_default_endpoint_alias_map() -> dict[str, dict[str, str]]:
    return {
        key: {
            "label": str(value.get("label") or "").strip(),
            "public_path": str(value.get("public_path") or "").strip(),
            "method": str(value.get("method") or "").strip().upper(),
        }
        for key, value in _DEFAULT_ENDPOINT_ALIAS_MAP.items()
    }


def get_known_server_profile(server_id: str) -> dict[str, Any]:
    profile = _SERVER_ID_PROFILES.get(str(server_id or "").strip(), {})
    return {
        "parser_id": str(profile.get("parser_id") or "").strip(),
        "display_profile": str(profile.get("display_profile") or "").strip(),
        "variant_pricing_mode": str(profile.get("variant_pricing_mode") or "").strip(),
    }
