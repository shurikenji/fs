"""Public balance checker integrated into the portal."""
from __future__ import annotations

import asyncio
import logging
import re

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.deps import get_templates
from app.public_registry import load_balance_runtime_sources, load_public_balance_sources
from app.rate_limit import enforce_rate_limit

router = APIRouter(tags=["public"])
logger = logging.getLogger(__name__)

_API_KEY_PATTERN = re.compile(r"^sk-[A-Za-z0-9]{20,}$")

# Standard NewAPI internal quota units: 500000 units = $1 USD
_QUOTA_PER_USD = 500_000


class BalanceCheckRequest(BaseModel):
    api_key: str
    server: str


def _is_quota_exhausted(raw: str) -> bool:
    """Check if the error message indicates quota exhausted (negative balance)."""
    return "\u989d\u5ea6\u5df2\u7528\u5c3d" in raw


def _normalize_error_message(raw: str) -> str:
    if "\u65e0\u6548\u7684\u4ee4\u724c" in raw:
        return "Invalid API key"
    if _is_quota_exhausted(raw):
        return "Quota exhausted"
    return "Failed to check balance"


async def _fallback_balance_via_token_search(
    selected: dict,
    api_key: str,
) -> dict | None:
    """
    Fallback: when the billing API returns 'quota exhausted', use the admin
    token search API to retrieve remain_quota / used_quota and compute balance.

    Returns the response dict on success, or None if fallback is unavailable.
    """
    from app.adapters import get_adapter
    from db.queries.servers import get_server

    server_id = str(selected["id"]).strip()
    server = await get_server(server_id)
    if not server:
        return None

    # Admin auth_token is required to search tokens on the upstream server
    if not server.get("auth_token"):
        return None

    adapter = get_adapter(server)
    try:
        token_data = await adapter.search_token(server, api_key)
    except Exception as exc:
        logger.warning("Balance fallback search_token failed for server %s: %s", server_id, exc)
        return None

    if not token_data:
        return None

    remain_quota = token_data.get("remain_quota")
    used_quota = token_data.get("used_quota")
    if remain_quota is None:
        remain_quota = token_data.get("remainQuota")
    if used_quota is None:
        used_quota = token_data.get("usedQuota")

    if remain_quota is None or used_quota is None:
        return None

    try:
        remain_quota = int(remain_quota)
        used_quota = int(used_quota)
    except (TypeError, ValueError):
        return None

    rate = float(selected.get("rate") or 1.0) or 1.0
    total_quota = remain_quota + used_quota

    # Convert from internal quota units to USD, then apply balance_rate
    limit_usd = total_quota / (_QUOTA_PER_USD * rate)
    usage_usd = used_quota / (_QUOTA_PER_USD * rate)
    balance_usd = remain_quota / (_QUOTA_PER_USD * rate)

    return {
        "success": True,
        "server": selected["name"],
        "data": {
            "limit_usd": f"{limit_usd:.2f}",
            "usage_usd": f"{usage_usd:.2f}",
            "balance_usd": f"{balance_usd:.2f}",
            "has_payment_method": False,
        },
    }


@router.get("/check", response_class=HTMLResponse)
async def balance_page(request: Request):
    templates = get_templates()
    return templates.TemplateResponse(
        "balance.html",
        {
            "request": request,
            "servers": await load_public_balance_sources(),
        },
    )


@router.post("/api/check-balance")
async def check_balance(body: BalanceCheckRequest, request: Request):
    await enforce_rate_limit(
        request,
        bucket="balance-check",
        limit=12,
        window_seconds=60,
        detail="Too many balance checks. Please wait a moment and try again.",
    )
    api_key = body.api_key.strip()
    if not _API_KEY_PATTERN.match(api_key):
        raise HTTPException(status_code=400, detail="Invalid API key format. Must start with sk-.")

    servers = await load_balance_runtime_sources()
    selected = next((item for item in servers if str(item["id"]) == body.server), None)
    if not selected:
        raise HTTPException(status_code=400, detail="Invalid server")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            subscription_response, usage_response = await asyncio.gather(
                client.get(f"{selected['base_url']}/v1/dashboard/billing/subscription", headers=headers),
                client.get(f"{selected['base_url']}/v1/dashboard/billing/usage", headers=headers),
            )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Failed to reach the selected source. Please try again later.",
        ) from exc

    try:
        subscription_response.raise_for_status()
        usage_response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        message = ""
        try:
            payload = exc.response.json()
            message = str(payload.get("error", {}).get("message") or "")
        except Exception:
            message = exc.response.text

        # Fallback: if quota exhausted, try internal token search to compute balance
        if _is_quota_exhausted(message):
            fallback_result = await _fallback_balance_via_token_search(selected, api_key)
            if fallback_result is not None:
                return fallback_result

        raise HTTPException(status_code=exc.response.status_code, detail=_normalize_error_message(message)) from exc

    subscription = subscription_response.json()
    usage = usage_response.json()
    rate = float(selected.get("rate") or 1.0) or 1.0

    raw_limit = float(subscription.get("hard_limit_usd") or 0)
    raw_usage = float(usage.get("total_usage") or 0) / 100
    limit = raw_limit / rate
    usage_value = raw_usage / rate
    balance = max(0.0, limit - usage_value)

    return {
        "success": True,
        "server": selected["name"],
        "data": {
            "limit_usd": f"{limit:.2f}",
            "usage_usd": f"{usage_value:.2f}",
            "balance_usd": f"{balance:.2f}",
            "has_payment_method": bool(subscription.get("has_payment_method") or False),
        },
    }
