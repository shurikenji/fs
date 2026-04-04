"""
bot/services/api_clients/base.py — Abstract base class for API clients.
All API clients must implement these methods.
"""
from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any, Optional

import aiohttp

logger = logging.getLogger(__name__)


def _response_dict_or_none(
    data: Any,
    *,
    server_name: str,
    action: str,
) -> dict[str, Any] | None:
    """Normalize API responses to dict and log incompatible payloads."""
    if isinstance(data, dict):
        return data

    logger.error(
        "%s received non-dict JSON from %s: type=%s value=%r",
        action,
        server_name,
        type(data).__name__,
        data if isinstance(data, (str, int, float, bool)) else type(data).__name__,
    )
    return None


def _extract_token_items(payload: Any) -> list[dict[str, Any]]:
    """Normalize token search payloads from list or paginated dict shapes."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("items", "list", "rows", "records"):
            items = payload.get(key)
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
    return []


def _build_search_token_param_candidates(api_key: str) -> list[dict[str, str]]:
    """Build a small set of token-search parameter candidates for mixed upstream APIs."""
    stripped = api_key[3:] if api_key.startswith("sk-") else api_key
    keyword_hint = stripped[-8:] if len(stripped) > 8 else stripped

    candidates = [
        {"keyword": "", "token": api_key},
    ]
    if stripped != api_key:
        candidates.append({"keyword": "", "token": stripped})
    if keyword_hint:
        candidates.append({"keyword": keyword_hint, "token": api_key})

    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        signature = (candidate["keyword"], candidate["token"])
        if signature in seen:
            continue
        seen.add(signature)
        deduped.append(candidate)
    return deduped


def _match_token_from_items(
    items: list[dict[str, Any]],
    *,
    requested_token: str,
) -> dict[str, Any] | None:
    """Find the best matching token item across masked and unmasked upstream payloads."""
    normalized_requested = requested_token[3:] if requested_token.startswith("sk-") else requested_token

    for item in items:
        token_key = str(item.get("key") or "")
        normalized_key = token_key[3:] if token_key.startswith("sk-") else token_key
        if token_key == requested_token or normalized_key == normalized_requested:
            return item

    if len(items) == 1:
        return items[0]
    return None


class BaseAPIClient(ABC):
    """Abstract base class for API clients."""

    @property
    def supports_multi_group(self) -> bool:
        """Whether this client natively supports selecting multiple groups."""
        return False

    @property
    @abstractmethod
    def api_type(self) -> str:
        """Return API type: newapi, rixapi, or other."""
        pass

    def get_supports_multi_group(self, server: dict) -> bool:
        """Check if server supports multi-group."""
        return self.supports_multi_group or bool(server.get("supports_multi_group"))

    def extract_ratio_hint(self, *texts: object, default: float = 1.0) -> float:
        """Extract ratio-like numeric hints from descriptive group labels."""
        patterns = (
            r"(\d+(?:\.\d+)?)\s*元\s*/\s*[刀次]",
            r"(\d+(?:\.\d+)?)\s*倍率",
            r"\((\d+(?:\.\d+)?)[^)]*\)",
        )
        for text in texts:
            if not text:
                continue
            value = str(text)
            for pattern in patterns:
                match = re.search(pattern, value, flags=re.IGNORECASE)
                if match:
                    try:
                        return float(match.group(1))
                    except (TypeError, ValueError):
                        continue
        return default

    def get_groups_endpoint(self, server: dict) -> str:
        """Get groups endpoint from server config or use default."""
        custom = server.get("groups_endpoint")
        if custom:
            return custom.rstrip("/")
        # Default endpoint
        base = server.get("base_url", "").rstrip("/")
        return f"{base}/api/user/self/groups"

    def get_headers(self, server: dict) -> dict[str, str]:
        """
        Build request headers.
        Override in subclasses for custom auth.
        """
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        
        # Use flexible auth fields
        auth_type = server.get("auth_type", "header")
        
        if auth_type == "header":
            user_header = server.get("auth_user_header") or server.get("user_id_header") or "new-api-user"
            user_value = server.get("auth_user_value") or server.get("user_id_header")
            token = server.get("auth_token") or server.get("access_token")
            
            if user_header and user_value:
                headers[user_header] = str(user_value)
            if token:
                headers["Authorization"] = f"Bearer {token}"
                
        elif auth_type == "bearer_only":
            token = server.get("auth_token") or server.get("access_token")
            if token:
                headers["Authorization"] = f"Bearer {token}"
                
        elif auth_type == "cookie":
            cookie = server.get("auth_cookie")
            if cookie:
                headers["Cookie"] = cookie
        
        # Add custom headers
        custom = server.get("custom_headers")
        if custom:
            try:
                custom_list = json.loads(custom) if isinstance(custom, str) else custom
                for h in custom_list:
                    if isinstance(h, dict) and h.get("key"):
                        headers[h["key"]] = h.get("value", "")
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning(f"Failed to parse custom_headers: {e}")
        
        return headers

    @abstractmethod
    def parse_groups(self, data: dict) -> list[dict]:
        """
        Parse groups response into normalized format.
        
        Expected output format:
        [
            {"name": "Azure", "ratio": 0.3, "desc": "..."},
            {"name": "Claude", "ratio": 3.0, "desc": "..."},
        ]
        """
        pass

    @abstractmethod
    def build_create_payload(
        self, quota: int, group: str, name: str, **kwargs
    ) -> dict[str, Any]:
        """
        Build payload for creating token.
        
        Args:
            quota: Amount of quota
            group: Group name (can be comma-separated for multi-group)
            name: Token name
            **kwargs: Additional parameters
            
        Returns:
            JSON-serializable dict for request body
        """
        pass

    @abstractmethod
    def build_update_payload(
        self, current_data: dict, new_quota: int, **kwargs
    ) -> dict[str, Any]:
        """
        Build payload for updating token.
        
        CRITICAL: Must preserve ALL existing fields, only change quota.
        
        Args:
            current_data: Full token data from server
            new_quota: New quota value
            **kwargs: Additional parameters
            
        Returns:
            JSON-serializable dict for request body
        """
        pass

    async def get_groups(self, server: dict) -> list[dict]:
        """Fetch groups from server."""
        url = self.get_groups_endpoint(server)
        headers = self.get_headers(server)
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    data = _response_dict_or_none(
                        await resp.json(),
                        server_name=server["name"],
                        action="get_groups",
                    )
                    if data is None:
                        return []
                    if data.get("success"):
                        raw_groups = data.get("data", {})
                        return self.parse_groups(raw_groups)
                    logger.error("get_groups failed: %s", data.get("message"))
                    return []
        except Exception as e:
            logger.error("get_groups exception: %s", e)
            return []

    async def create_token(
        self,
        server: dict,
        quota: int,
        group: str,
        name: str,
        **kwargs,
    ) -> Optional[dict]:
        """Create new token on server."""
        url = f"{server['base_url'].rstrip('/')}/api/token/"
        body = self.build_create_payload(quota, group, name, **kwargs)
        headers = self.get_headers(server)
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=body, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    data = _response_dict_or_none(
                        await resp.json(),
                        server_name=server["name"],
                        action="create_token",
                    )
                    if data is None:
                        return None
                    if data.get("success"):
                        logger.info(
                            "Token created on %s: name=%s, quota=%d, group=%s",
                            server["name"], name, quota, group
                        )
                        return data
                    logger.error(
                        "create_token failed on %s: %s",
                        server["name"], data.get("message")
                    )
                    return None
        except Exception as e:
            logger.error("create_token exception on %s: %s", server["name"], e)
            return None

    async def search_token(
        self,
        server: dict,
        api_key: str,
    ) -> Optional[dict]:
        """Search token by API key."""
        url = f"{server['base_url'].rstrip('/')}/api/token/search"
        headers = self.get_headers(server)
        
        try:
            async with aiohttp.ClientSession() as session:
                last_message: str | None = None
                for params in _build_search_token_param_candidates(api_key):
                    async with session.get(
                        url, params=params, headers=headers,
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as resp:
                        data = _response_dict_or_none(
                            await resp.json(),
                            server_name=server["name"],
                            action="search_token",
                        )
                        if data is None:
                            continue
                        if not data.get("success"):
                            last_message = str(data.get("message") or "")
                            continue

                        tokens = _extract_token_items(data.get("data", []))
                        matched = _match_token_from_items(tokens, requested_token=params["token"])
                        if matched is not None:
                            return matched
                if last_message:
                    logger.error(
                        "search_token failed on %s: %s",
                        server["name"], last_message,
                    )
                return None
        except Exception as e:
            logger.error("search_token exception on %s: %s", server["name"], e)
            return None

    async def search_token_by_name(
        self,
        server: dict,
        name: str,
    ) -> Optional[dict]:
        """Search token by name."""
        url = f"{server['base_url'].rstrip('/')}/api/token/search"
        params = {"keyword": name}
        headers = self.get_headers(server)
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, params=params, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    data = _response_dict_or_none(
                        await resp.json(),
                        server_name=server["name"],
                        action="search_token_by_name",
                    )
                    if data is None:
                        return None
                    if data.get("success"):
                        tokens = _extract_token_items(data.get("data", []))
                        if tokens:
                            for t in tokens:
                                if t.get("name") == name:
                                    return t
                            return tokens[0]
                        return None
                    logger.error(
                        "search_token_by_name failed on %s: %s",
                        server["name"], data.get("message")
                    )
                    return None
        except Exception as e:
            logger.error(
                "search_token_by_name exception on %s: %s", server["name"], e
            )
            return None

    async def update_token(
        self,
        server: dict,
        token_id: int,
        new_quota: int,
        current_data: Optional[dict] = None,
        **kwargs,
    ) -> Optional[dict]:
        """
        Update token quota.
        
        If current_data is provided, uses build_update_payload to preserve all fields.
        Otherwise, creates minimal update payload.
        """
        url = f"{server['base_url'].rstrip('/')}/api/token/"
        
        if current_data:
            body = self.build_update_payload(current_data, new_quota, **kwargs)
        else:
            # Minimal payload if no current data
            body = {
                "id": token_id,
                "remain_quota": new_quota,
            }
        
        headers = self.get_headers(server)
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.put(
                    url, json=body, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    data = _response_dict_or_none(
                        await resp.json(),
                        server_name=server["name"],
                        action="update_token",
                    )
                    if data is None:
                        return None
                    if data.get("success"):
                        logger.info(
                            "Token %d updated on %s: new_quota=%d",
                            token_id, server["name"], new_quota
                        )
                        return data.get("data")
                    logger.error(
                        "update_token failed on %s: %s",
                        server["name"], data.get("message")
                    )
                    return None
        except Exception as e:
            logger.error("update_token exception on %s: %s", server["name"], e)
            return None
