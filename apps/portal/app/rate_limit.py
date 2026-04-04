"""Simple in-memory rate limiting for public tool endpoints."""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

_LOCK = asyncio.Lock()
_WINDOWS: dict[tuple[str, str], deque[float]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


async def enforce_rate_limit(
    request: Request,
    *,
    bucket: str,
    limit: int,
    window_seconds: int,
    detail: str | None = None,
) -> None:
    now = time.monotonic()
    key = (bucket, _client_ip(request))
    async with _LOCK:
        hits = _WINDOWS[key]
        cutoff = now - window_seconds
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= limit:
            raise HTTPException(
                status_code=429,
                detail=detail or "Too many requests. Please wait and try again.",
            )
        hits.append(now)
