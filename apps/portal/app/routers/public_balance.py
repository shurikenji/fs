"""Public balance checker integrated into the portal."""
from __future__ import annotations

import asyncio
import re

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.deps import get_templates
from app.public_registry import load_balance_runtime_sources, load_public_balance_sources
from app.rate_limit import enforce_rate_limit

router = APIRouter(tags=["public"])

_API_KEY_PATTERN = re.compile(r"^sk-[A-Za-z0-9]{20,}$")


class BalanceCheckRequest(BaseModel):
    api_key: str
    server: str


def _normalize_error_message(raw: str) -> str:
    if "æ— æ•ˆçš„ä»¤ç‰Œ" in raw:
        return "Invalid API key"
    if "é¢åº¦å·²ç”¨å°½" in raw:
        return "Quota exhausted"
    return "Failed to check balance"


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
