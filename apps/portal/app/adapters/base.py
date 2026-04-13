"""Base adapter — shared helpers for all upstream server types."""
from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from typing import Any

import aiohttp

from app.schemas import (
    NormalizedGroup,
    NormalizedModel,
    NormalizedPricing,
    PricingMode,
    GroupPriceSnapshot,
)

logger = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=20)


# ── Shared helpers ───────────────────────────────────────────────────────────


def join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{path if path.startswith('/') else '/' + path}"


def build_headers(
    server: dict,
    *,
    override_user: str = "",
    override_token: str = "",
    include_server_user: bool = False,
) -> dict[str, str]:
    headers: dict[str, str] = {"Accept": "application/json"}
    mode = server.get("auth_mode") or "header"
    token = override_token or server.get("auth_token") or ""
    user_header = str(server.get("auth_user_header") or "").strip()
    user_value = str(override_user or "").strip()
    if not user_value and include_server_user:
        user_value = str(server.get("auth_user_value") or "").strip()

    if mode == "header":
        # Do not auto-attach legacy user headers such as New-Api-User for
        # generic pricing/search requests. Only send a custom user header when
        # the caller explicitly provides an override, or this endpoint opts in.
        if user_header and user_value:
            headers[user_header] = user_value
        if token:
            headers["Authorization"] = f"Bearer {token}"
    elif mode == "bearer":
        if token:
            headers["Authorization"] = f"Bearer {token}"
    elif mode == "cookie":
        cookie = server.get("auth_cookie") or ""
        if cookie:
            headers["Cookie"] = cookie
    return headers


def infer_pricing_mode(
    quota_type: int | None,
    model_price: float = 0.0,
    model_ratio: float = 0.0,
    completion_ratio: float = 0.0,
) -> PricingMode:
    if model_price and model_price > 0 and (not model_ratio or model_ratio == 0):
        return PricingMode.fixed
    if quota_type == 0 and model_price and model_price > 0:
        return PricingMode.fixed
    if model_ratio and model_ratio > 0:
        return PricingMode.token
    return PricingMode.unknown


def compute_token_prices(
    model_ratio: float,
    completion_ratio: float,
    group_ratio: float = 1.0,
    cache_ratio: float | None = None,
) -> dict[str, float | None]:
    inp = round(2.0 * group_ratio * model_ratio, 6)
    out = round(2.0 * group_ratio * model_ratio * completion_ratio, 6)
    cached = round(2.0 * group_ratio * model_ratio * cache_ratio, 6) if cache_ratio is not None else None
    return {"input": inp, "output": out, "cached": cached}


_RATIO_PATTERNS = (
    re.compile(r"(\d+(?:\.\d+)?)\s*元\s*/\s*[刀次]"),
    re.compile(r"(\d+(?:\.\d+)?)\s*倍率"),
    re.compile(r"\((\d+(?:\.\d+)?)[^)]*\)"),
)


_GROUP_RATIO_PATTERNS = (
    re.compile(r"(\d+(?:\.\d+)?)\s*(?:cny|usd|rmb|yuan)\s*/\s*(?:token|request|quota|1m|次|刀次)", re.IGNORECASE),
    re.compile(r"(?:倍率|ratio|multiplier)\s*[:=]?\s*(\d+(?:\.\d+)?)", re.IGNORECASE),
    re.compile(r"(?:^|[^\w])x\s*(\d+(?:\.\d+)?)(?:$|[^\w])", re.IGNORECASE),
    re.compile(r"(?:^|[^\w])(\d+(?:\.\d+)?)\s*x(?:$|[^\w])", re.IGNORECASE),
    re.compile(r"\((\d+(?:\.\d+)?)[^)]*(?:cny|usd|rmb|yuan|token|request|quota|1m|x|倍)", re.IGNORECASE),
)


def extract_ratio_hint(*texts: object, default: float = 1.0) -> float:
    for text in texts:
        if not text:
            continue
        value = str(text)
        for pattern in _GROUP_RATIO_PATTERNS:
            m = pattern.search(value)
            if m:
                try:
                    return float(m.group(1))
                except (TypeError, ValueError):
                    continue
    return default


def build_token_search_candidates(api_key: str) -> list[dict[str, str]]:
    stripped = api_key[3:] if api_key.startswith("sk-") else api_key
    hint = stripped[-8:] if len(stripped) > 8 else stripped
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, str]] = []
    for c in [
        {"keyword": "", "token": api_key},
        {"keyword": "", "token": stripped},
        {"keyword": hint, "token": api_key},
    ]:
        key = (c["keyword"], c["token"])
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def match_token_from_items(
    items: list[dict], requested: str
) -> dict | None:
    norm = requested[3:] if requested.startswith("sk-") else requested
    for item in items:
        raw = str(item.get("key") or "")
        raw_norm = raw[3:] if raw.startswith("sk-") else raw
        if raw == requested or raw_norm == norm:
            return item
    if len(items) == 1:
        return items[0]
    return None


def extract_token_items(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [i for i in payload if isinstance(i, dict)]
    if isinstance(payload, dict):
        for key in ("items", "list", "rows", "records", "data"):
            v = payload.get(key)
            if isinstance(v, list):
                return [i for i in v if isinstance(i, dict)]
    return []


# ── Tag inference ────────────────────────────────────────────────────────────

_TAG_MAP = {
    "推理": "thinking", "reasoning": "thinking",
    "工具": "tools", "函数调用": "tools", "function_calling": "tools",
    "文件": "file", "file": "file",
    "多模态": "vision", "图片输入": "vision", "vision": "vision",
    "音频": "audio", "audio": "audio",
    "开源权重": "open-weight",
    "结构化输出": "structured-output",
    "文本输入": "chat", "文本输出": "chat",
}


def normalize_tags(raw_tags: str | list | None) -> list[str]:
    extra_map = {
        "对话": "chat",
        "chat格式": "chat",
        "dialogue": "chat",
        "思考": "thinking",
        "绘画": "image",
        "drawing": "image",
        "image generation": "image",
        "识图": "vision",
        "图像分析": "vision",
        "视图": "vision",
        "异步": "async",
        "异步任务": "async",
        "视频生成": "video",
        "视频": "video",
        "联网": "web",
        "文本转语音": "tts",
        "text to speech": "tts",
        "语音转文本": "transcription",
        "speech to text": "transcription",
        "实时语音": "realtime-audio",
        "向量": "embedding",
        "文本嵌入": "embedding",
        "重排序": "rerank",
        "re-ranking": "rerank",
        "音乐": "music",
        "文件分析": "file",
        "高清": "hd",
        "编辑": "edit",
        "弃用": "deprecated",
    }
    if not raw_tags:
        return []
    if isinstance(raw_tags, list):
        items = raw_tags
    else:
        items = [t.strip() for t in str(raw_tags).split(",") if t.strip()]
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        lowered = item.lower()
        mapped = extra_map.get(lowered) or extra_map.get(item) or _TAG_MAP.get(lowered, _TAG_MAP.get(item))
        tag = mapped or item
        if tag not in seen:
            seen.add(tag)
            out.append(tag)
    return out


# ── Endpoint inference ───────────────────────────────────────────────────────


def infer_endpoints(
    supported_types: Any,
    endpoints_map: Any,
    model_name: str = "",
    tags: list[str] | None = None,
) -> list[str]:
    supported_type_endpoints = {
        "v1": ["/v1/chat/completions"],
        "openai": ["/v1/chat/completions"],
        "openai-chat": ["/v1/chat/completions"],
        "openai-compatible": ["/v1/chat/completions"],
        "openai_response": ["/v1/responses"],
        "openai-response": ["/v1/responses"],
        "responses": ["/v1/responses"],
        "anthropic": ["/v1/messages"],
        "image-generation": ["/v1/images/generations"],
        "images": ["/v1/images/generations"],
        "embedding": ["/v1/embeddings"],
        "embeddings": ["/v1/embeddings"],
        "rerank": ["/v1/rerank"],
        "audio-speech": ["/v1/audio/speech"],
        "audio-transcription": ["/v1/audio/transcriptions"],
    }

    def append_unique(items: list[str], *values: str) -> None:
        for value in values:
            if value and value not in items:
                items.append(value)

    eps: list[str] = []
    if isinstance(endpoints_map, dict):
        for key, spec in endpoints_map.items():
            if isinstance(spec, dict) and spec.get("path"):
                append_unique(eps, str(spec["path"]))
            elif isinstance(spec, str) and spec.strip().startswith("/"):
                append_unique(eps, spec.strip())
            elif isinstance(key, str) and key.strip().startswith("/"):
                append_unique(eps, key.strip())
    elif isinstance(endpoints_map, list):
        for spec in endpoints_map:
            if isinstance(spec, dict) and spec.get("path"):
                append_unique(eps, str(spec["path"]))
            elif isinstance(spec, str) and spec.strip().startswith("/"):
                append_unique(eps, spec.strip())
    elif isinstance(endpoints_map, str) and endpoints_map.strip().startswith("/"):
        append_unique(eps, endpoints_map.strip())

    normalized_types: list[str] = []
    if isinstance(supported_types, str):
        normalized_types = [supported_types]
    elif isinstance(supported_types, list):
        normalized_types = [str(item) for item in supported_types if str(item).strip()]
    for raw_type in normalized_types:
        for endpoint in supported_type_endpoints.get(str(raw_type).strip().lower(), []):
            append_unique(eps, endpoint)

    if not eps:
        name_lower = model_name.lower()
        tag_set = set(tags or [])
        if "embedding" in name_lower or "embedding" in tag_set:
            append_unique(eps, "/v1/embeddings")
        elif "rerank" in name_lower or "rerank" in tag_set:
            append_unique(eps, "/v1/rerank")
        elif "tts" in name_lower or "tts" in tag_set:
            append_unique(eps, "/v1/audio/speech")
        elif "transcription" in name_lower or "whisper" in name_lower or "transcription" in tag_set:
            append_unique(eps, "/v1/audio/transcriptions")
        elif "dall-e" in name_lower or "image" in name_lower or "image" in tag_set:
            append_unique(eps, "/v1/images/generations")
        elif "claude" in name_lower:
            append_unique(eps, "/v1/chat/completions", "/v1/messages")
        elif "chat" in tag_set or "tools" in tag_set or "vision" in tag_set or "thinking" in tag_set:
            append_unique(eps, "/v1/chat/completions")
    return eps


# ── Abstract adapter ─────────────────────────────────────────────────────────


class BaseAdapter(ABC):
    """Each server type implements fetch_pricing, fetch_logs, search_token."""

    @abstractmethod
    async def fetch_pricing(self, server: dict) -> NormalizedPricing:
        ...

    def extract_ratio_hint(self, *texts: object, default: float = 1.0) -> float:
        return extract_ratio_hint(*texts, default=default)

    def get_groups_path(self, server: dict) -> str:
        return str(server.get("groups_path") or "/api/user/self/groups").strip()

    def parse_groups(self, data: Any) -> list[dict]:
        return []

    async def fetch_groups(self, server: dict) -> list[dict]:
        """Fetch canonical groups using the same flow as shopbot API clients."""
        path = self.get_groups_path(server)
        if not path:
            return []

        url = join_url(server["base_url"], path)
        headers = build_headers(server, include_server_user=True)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=_TIMEOUT) as resp:
                    data = await resp.json()
        except Exception as exc:
            logger.warning("fetch_groups failed for %s: %s", server.get("name"), exc)
            return []

        if not isinstance(data, dict):
            return []
        if data.get("success") is False:
            logger.warning(
                "fetch_groups upstream rejected %s: %s",
                server.get("name"),
                data.get("message") or "unknown error",
            )
            return []

        payload = data.get("data", data)
        return self.parse_groups(payload)

    async def fetch_logs(
        self, server: dict, params: dict
    ) -> dict:
        """Fetch usage logs. params includes userId, accessToken, page, etc."""
        url = join_url(
            server["base_url"],
            server.get("log_path") or "/api/log/self",
        )
        headers = build_headers(
            server,
            override_user=params.get("userId", ""),
            override_token=params.get("accessToken", ""),
        )
        query: dict[str, str] = {
            "p": str(params.get("page", 1)),
            "page_size": str(params.get("pageSize", 50)),
            "type": "0",
        }
        for key in ("token_name", "model_name", "start_timestamp", "end_timestamp", "group"):
            val = params.get(key)
            if val:
                query[key] = str(val)

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=query, timeout=_TIMEOUT) as resp:
                data = await resp.json()
                return data if isinstance(data, dict) else {"data": data}

    async def search_token(self, server: dict, api_key: str) -> dict | None:
        """Search for a token by API key."""
        url = join_url(
            server["base_url"],
            server.get("token_search_path") or "/api/token/search",
        )
        headers = build_headers(server, include_server_user=True)
        async with aiohttp.ClientSession() as session:
            for candidate in build_token_search_candidates(api_key):
                try:
                    async with session.get(
                        url, params=candidate, headers=headers, timeout=_TIMEOUT
                    ) as resp:
                        data = await resp.json()
                        if not isinstance(data, dict) or not data.get("success"):
                            continue
                        items = extract_token_items(data.get("data", []))
                        matched = match_token_from_items(items, candidate["token"])
                        if matched:
                            return matched
                except Exception as exc:
                    logger.warning("search_token attempt failed: %s", exc)
        return None

    async def update_token(self, server: dict, payload: dict) -> dict:
        """Update token metadata using the upstream token update endpoint."""
        url = join_url(
            server["base_url"],
            server.get("token_update_path") or "/api/token/",
        )
        headers = {
            "Content-Type": "application/json",
            **build_headers(server, include_server_user=True),
        }
        async with aiohttp.ClientSession() as session:
            async with session.put(url, json=payload, headers=headers, timeout=_TIMEOUT) as resp:
                data = await resp.json()
                if isinstance(data, dict):
                    return data
                return {"success": False, "message": f"Unexpected response with status {resp.status}"}
