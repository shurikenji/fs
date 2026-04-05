"""Client for proxy-operator runtime apply jobs."""
from __future__ import annotations

from typing import Any

import httpx

from app.config import get_settings


def _response_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict):
        detail = payload.get("error") or payload.get("detail") or payload.get("message")
        if detail:
            return str(detail)

    body = (response.text or "").strip()
    if body:
        return body
    return f"{response.status_code} {response.reason_phrase}"


async def apply_proxy_state(proxies: list[dict[str, Any]]) -> dict[str, Any]:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{settings.proxy_operator_url.rstrip('/')}/api/runtime/apply",
            json={"proxies": proxies},
            headers={"X-Operator-Token": settings.proxy_operator_token},
        )
        if response.is_error:
            raise RuntimeError(_response_error_message(response))
        return response.json()


async def get_operator_status() -> dict[str, Any]:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            f"{settings.proxy_operator_url.rstrip('/')}/health",
            headers={"X-Operator-Token": settings.proxy_operator_token},
        )
        response.raise_for_status()
        return response.json()


async def ensure_wildcard_certificate() -> dict[str, Any]:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=180.0) as client:
        response = await client.post(
            f"{settings.proxy_operator_url.rstrip('/')}/api/runtime/wildcard/ensure",
            headers={"X-Operator-Token": settings.proxy_operator_token},
        )
        if response.is_error:
            raise RuntimeError(_response_error_message(response))
        return response.json()
