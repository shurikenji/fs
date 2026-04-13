"""
bot/services/api_clients/other.py — Other/Custom API client implementation.
For servers that don't fit newapi or rixapi patterns.
Uses flexible authentication (header, bearer, cookie) and custom endpoints.
"""
from __future__ import annotations

from typing import Any

from .base import BaseAPIClient
from bot.utils.group_name_policy import extract_ratio_hint_from_texts, strip_group_price_notes


class OtherAPIClient(BaseAPIClient):
    """Client for custom/other servers."""
    
    @property
    def api_type(self) -> str:
        return "other"

    def get_headers(self, server: dict) -> dict[str, str]:
        """
        Build headers based on auth_type setting.
        
        Auth types:
        - header: User ID header + Bearer token (default)
        - bearer_only: Bearer token only
        - cookie: Cookie-based auth
        - none: No auth
        """
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        
        auth_type = server.get("auth_type", "header")
        
        if auth_type == "header":
            # Header + Bearer
            user_header = server.get("auth_user_header") or server.get("user_id_header") or "new-api-user"
            user_value = server.get("auth_user_value") or server.get("user_id_header") or ""
            token = server.get("auth_token") or server.get("access_token") or ""
            
            if user_header and user_value:
                headers[user_header] = str(user_value)
            if token:
                headers["Authorization"] = f"Bearer {token}"
                
        elif auth_type == "bearer_only":
            # Bearer Only
            token = server.get("auth_token") or server.get("access_token") or ""
            if token:
                headers["Authorization"] = f"Bearer {token}"
                
        elif auth_type == "cookie":
            # Cookie Auth
            cookie = server.get("auth_cookie") or ""
            if cookie:
                headers["Cookie"] = cookie
        
        # Add custom headers (JSON array)
        custom_headers = server.get("custom_headers")
        if custom_headers:
            import json
            try:
                custom_list = json.loads(custom_headers) if isinstance(custom_headers, str) else custom_headers
                for h in custom_list:
                    if isinstance(h, dict) and h.get("key"):
                        headers[h["key"]] = h.get("value", "")
            except (json.JSONDecodeError, TypeError):
                pass
        
        return headers

    def get_groups_endpoint(self, server: dict) -> str:
        """Get custom groups endpoint or default to newapi format."""
        custom = server.get("groups_endpoint")
        if custom:
            return custom.rstrip("/")
        
        base = server.get("base_url", "").rstrip("/")
        
        # Try newapi format as default
        return f"{base}/api/user/self/groups"

    def parse_groups(self, data: dict) -> list[dict]:
        """
        Parse groups - tries multiple formats.
        
        Supports:
        - NewAPI: {"Azure": {"desc": "...", "ratio": 0.3}, ...}
        - RixAPI: [{"group": "Azure", "ratio": 0.3}, ...]
        - Array: [{"name": "Azure", "ratio": 0.3}, ...]
        """
        groups = []
        
        # Try NewAPI format (dict)
        if isinstance(data, dict):
            for name, info in data.items():
                if isinstance(info, dict):
                    raw_desc = str(info.get("desc") or "")
                    groups.append({
                        "name": name,
                        "ratio": info.get("ratio", 1.0),
                        "desc": raw_desc,
                        "translation_source": strip_group_price_notes(raw_desc or name),
                        "ratio_source": raw_desc or name,
                    })
                else:
                    groups.append({
                        "name": name,
                        "ratio": 1.0,
                        "desc": "",
                        "translation_source": name,
                        "ratio_source": name,
                    })
        
        # Try RixAPI/Array format
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    raw_label = item.get("key") or item.get("label") or item.get("description") or ""
                    raw_desc = item.get("desc") or item.get("description") or raw_label
                    name = item.get("value") or item.get("group") or item.get("name") or item.get("key") or "unknown"
                    explicit_ratio = item.get("ratio")
                    if explicit_ratio in (None, ""):
                        explicit_ratio = item.get("multiplier")
                    groups.append({
                        "name": name,
                        "name_en": item.get("name_en"),
                        "ratio": explicit_ratio if explicit_ratio not in (None, "") else extract_ratio_hint_from_texts(raw_label, raw_desc, name),
                        "desc": raw_desc,
                        "translation_source": strip_group_price_notes(raw_label or raw_desc or name),
                        "ratio_source": str(raw_label or raw_desc or name),
                    })
        
        return groups

    def build_create_payload(
        self, quota: int, group: str, name: str, **kwargs
    ) -> dict[str, Any]:
        """
        Build create payload.
        
        Tries to match server format if known, otherwise uses generic.
        """
        # Default to newapi-like format
        return {
            "remain_quota": quota,
            "expired_time": kwargs.get("expired_time", -1),
            "unlimited_quota": False,
            "model_limits_enabled": False,
            "name": name,
            "group": group,  # Comma-separated for multi-group
            "allow_ips": kwargs.get("allow_ips", ""),
        }

    def build_update_payload(
        self, current_data: dict, new_quota: int, **kwargs
    ) -> dict[str, Any]:
        """
        Build update payload.
        
        CRITICAL: Preserve ALL fields from current_data.
        """
        payload = {
            "id": current_data.get("id"),
            "remain_quota": new_quota,
        }
        
        # Copy all existing fields
        for key, value in current_data.items():
            if key not in payload:
                payload[key] = value
        
        # Ensure required fields
        if "expired_time" not in payload:
            payload["expired_time"] = -1
        
        return payload
