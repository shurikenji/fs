"""
bot/services/api_clients/rixapi.py — RixAPI client implementation.
RixAPI servers use Rix-Api-User header and /api/token/group endpoint.
Supports multi-group natively.
"""
from __future__ import annotations

from typing import Any

from .base import BaseAPIClient


class RixAPIClient(BaseAPIClient):
    """Client for RixAPI servers."""
    
    @property
    def api_type(self) -> str:
        return "rixapi"

    @property
    def supports_multi_group(self) -> bool:
        """RixAPI natively supports multi-group."""
        return True

    def get_headers(self, server: dict) -> dict[str, str]:
        """RixAPI uses rix-api-user and access_token (legacy)."""
        user_id = server.get("auth_user_value") or server.get("user_id_header", "")
        token = server.get("auth_token") or server.get("access_token", "")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if user_id:
            headers["Rix-Api-User"] = str(user_id)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if server.get("auth_cookie"):
            headers["Cookie"] = str(server["auth_cookie"])
        return headers

    def get_groups_endpoint(self, server: dict) -> str:
        """RixAPI uses /api/token/group"""
        custom = server.get("groups_endpoint")
        if custom:
            return custom.rstrip("/")
        
        base = server.get("base_url", "").rstrip("/")
        return f"{base}/api/token/group"

    def parse_groups(self, data: dict) -> list[dict]:
        """
        Parse RixAPI groups response.
        
        RixAPI format can be:
        - [{"group": "Azure", "ratio": 0.3, "desc": "..."}, ...]
        - [{"key": "Azure - high concurrency", "value": "Azure"}, ...]
        """
        groups = []
        
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    name = (
                        item.get("value")
                        or item.get("group")
                        or item.get("name")
                        or item.get("key")
                        or "unknown"
                    )
                    raw_label = item.get("key") or item.get("label") or ""
                    groups.append({
                        "name": name,
                        "name_en": item.get("name_en"),
                        "ratio": item.get("ratio") or item.get("multiplier") or self.extract_ratio_hint(raw_label, name),
                        "desc": item.get("desc") or item.get("description") or raw_label,
                        "translation_source": raw_label or name,
                    })
        elif isinstance(data, dict):
            # Sometimes RixAPI returns object with group names as keys
            for name, info in data.items():
                if isinstance(info, dict):
                    groups.append({
                        "name": name,
                        "name_en": info.get("name_en"),
                        "ratio": info.get("ratio") or self.extract_ratio_hint(info.get("desc"), name),
                        "desc": info.get("desc", ""),
                        "translation_source": info.get("desc") or name,
                    })
                else:
                    groups.append({
                        "name": name,
                        "name_en": None,
                        "ratio": 1.0,
                        "desc": "",
                        "translation_source": name,
                    })
        
        return groups

    def build_create_payload(
        self, quota: int, group: str, name: str, **kwargs
    ) -> dict[str, Any]:
        """
        Build RixAPI create payload.
        
        RixAPI supports TokenGroup for multi-group.
        """
        groups = [g.strip() for g in group.split(",") if g.strip()]
        normalized_group = ",".join(groups) if groups else group
        default_cn = "\u9ed8\u8ba4"

        payload = {
            "name": name,
            "remain_quota": quota,
            "remain_count": 0,
            "expired_time": kwargs.get("expired_time", -1),
            "unlimited_quota": False,
            "unlimited_count": True,
            "model_limits_enabled": False,
            "model_limits": "",
            "rate_limits_enabled": False,
            "rate_limits_time": 10,
            "rate_limits_count": 900,
            "rate_limits_content": "",
            "allow_ips": kwargs.get("allow_ips", ""),
            "exclude_ips": kwargs.get("exclude_ips", ""),
            "mj_mode": kwargs.get("mj_mode", default_cn),
            "mj_cdn": kwargs.get("mj_cdn", default_cn),
            "mj_cdn_addr": kwargs.get("mj_cdn_addr", ""),
            "group": normalized_group,
        }
        if normalized_group:
            payload["TokenGroup"] = normalized_group
        return payload

    def build_update_payload(
        self, current_data: dict, new_quota: int, **kwargs
    ) -> dict[str, Any]:
        """
        Build RixAPI update payload.
        
        CRITICAL: Preserve ALL fields, only change remain_quota.
        """
        payload = {
            "id": current_data.get("id"),
            "remain_quota": new_quota,
        }
        
        # Preserve all known fields
        for key in [
            "name", "group", "TokenGroup", "expired_time",
            "key", "user_id", "created_time", "updated_time",
            "status", "is_active", "mj_mode", "mj_cdn", "mj_cdn_addr",
            "remain_count", "unlimited_count", "model_limits_enabled",
            "model_limits", "allow_ips", "exclude_ips",
            "rate_limits_enabled", "rate_limits_time", "rate_limits_count",
            "rate_limits_content",
        ]:
            if key in current_data:
                payload[key] = current_data[key]
        
        # Ensure expired_time
        if "expired_time" not in payload:
            payload["expired_time"] = -1
        
        return payload
