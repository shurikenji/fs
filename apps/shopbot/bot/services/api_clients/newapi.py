"""
bot/services/api_clients/newapi.py — NewAPI client implementation.
Standard NewAPI servers use New-Api-User header and /api/user/self/groups endpoint.
"""
from __future__ import annotations

from typing import Any

from .base import BaseAPIClient


class NewAPIClient(BaseAPIClient):
    """Client for standard NewAPI servers."""
    
    @property
    def api_type(self) -> str:
        return "newapi"

    def get_headers(self, server: dict) -> dict[str, str]:
        """NewAPI uses user_id_header and access_token (legacy)."""
        user_id = server.get("auth_user_value") or server.get("user_id_header", "")
        token = server.get("auth_token") or server.get("access_token", "")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if user_id:
            headers["New-Api-User"] = str(user_id)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def get_groups_endpoint(self, server: dict) -> str:
        """NewAPI uses /api/user/self/groups"""
        custom = server.get("groups_endpoint")
        if custom:
            return custom.rstrip("/")
        
        base = server.get("base_url", "").rstrip("/")
        return f"{base}/api/user/self/groups"

    def parse_groups(self, data: dict) -> list[dict]:
        """
        Parse NewAPI groups response.
        
        NewAPI format: {"Azure": {"desc": "...", "ratio": 0.3}, ...}
        """
        groups = []

        if (
            isinstance(data, dict)
            and isinstance(data.get("data"), dict)
            and isinstance(data.get("ratios"), dict)
        ):
            descriptions = data.get("data", {})
            ratios = data.get("ratios", {})
            for name, desc in descriptions.items():
                groups.append({
                    "name": name,
                    "ratio": ratios.get(name, 1.0),
                    "desc": desc if isinstance(desc, str) else "",
                })
            return groups
        
        if isinstance(data, dict):
            for name, info in data.items():
                if isinstance(info, dict):
                    groups.append({
                        "name": name,
                        "ratio": info.get("ratio", 1.0),
                        "desc": info.get("desc", ""),
                    })
                else:
                    groups.append({
                        "name": name,
                        "ratio": 1.0,
                        "desc": "",
                    })
        elif isinstance(data, list):
            # Some servers return array format
            for item in data:
                if isinstance(item, dict):
                    groups.append({
                        "name": item.get("name") or item.get("group") or "unknown",
                        "ratio": item.get("ratio") or item.get("multiplier") or 1.0,
                        "desc": item.get("desc") or item.get("description") or "",
                    })
        
        return groups

    def build_create_payload(
        self, quota: int, group: str, name: str, **kwargs
    ) -> dict[str, Any]:
        """Build NewAPI create payload."""
        groups = [g.strip() for g in group.split(",") if g.strip()]
        payload = {
            "remain_quota": quota,
            "expired_time": kwargs.get("expired_time", -1),
            "unlimited_quota": False,
            "model_limits_enabled": False,
            "model_limits": "",
            "name": name,
            "group": group,  # Can be comma-separated for multi-group
            "allow_ips": kwargs.get("allow_ips", ""),
        }
        if len(groups) > 1:
            payload["selected_groups"] = groups
        return payload

    def build_update_payload(
        self, current_data: dict, new_quota: int, **kwargs
    ) -> dict[str, Any]:
        """
        Build NewAPI update payload.
        
        CRITICAL: Preserve ALL fields, only change remain_quota.
        """
        # Copy all existing fields
        payload = {
            "id": current_data.get("id"),
            "remain_quota": new_quota,
        }
        
        # Preserve all known fields from current data
        for key in [
            "name", "group", "expired_time", "unlimited_quota",
            "model_limits_enabled", "allow_ips", "key", "user_id",
            "created_time", "updated_time", "status", "is_active",
        ]:
            if key in current_data:
                payload[key] = current_data[key]
        
        # Ensure expired_time is set
        if "expired_time" not in payload:
            payload["expired_time"] = -1
        
        return payload
