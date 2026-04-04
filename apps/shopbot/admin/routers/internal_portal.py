"""
Internal portal API for read-only customer data access from the future product shell.
Protected by an internal shared token so other services never touch the DB directly.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException
from itsdangerous import BadSignature, URLSafeSerializer
from pydantic import BaseModel

from bot.config import settings
from db.queries.orders import count_orders_by_user, get_orders_by_user
from db.queries.user_keys import get_user_keys
from db.queries.users import get_user_by_telegram_id
from db.queries.wallets import get_wallet

router = APIRouter(prefix="/internal/portal", tags=["internal-portal"])


def _require_internal_token(x_portal_token: Annotated[str | None, Header()] = None) -> None:
    expected = settings.portal_internal_token.strip()
    if not expected or x_portal_token != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(settings.portal_session_secret, salt="shopbot-portal-session")


class PortalSessionIssueRequest(BaseModel):
    telegram_id: int


class PortalSessionVerifyRequest(BaseModel):
    session_token: str


@router.get("/health")
async def portal_health(x_portal_token: Annotated[str | None, Header()] = None) -> dict[str, str]:
    _require_internal_token(x_portal_token)
    return {"status": "ok"}


@router.get("/users/{telegram_id}/summary")
async def portal_user_summary(telegram_id: int, x_portal_token: Annotated[str | None, Header()] = None):
    _require_internal_token(x_portal_token)
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    orders = await get_orders_by_user(int(user["id"]), limit=5)
    keys = await get_user_keys(int(user["id"]), limit=5)
    wallet = await get_wallet(int(user["id"]))

    return {
        "user": {
            "id": int(user["id"]),
            "telegram_id": int(user["telegram_id"]),
            "username": user.get("username"),
            "full_name": user.get("full_name"),
            "is_banned": bool(user.get("is_banned")),
        },
        "wallet_balance_vnd": int(wallet["balance"]) if wallet else 0,
        "order_count": await count_orders_by_user(int(user["id"])),
        "active_key_count": len([item for item in keys if int(item.get("is_active") or 0) == 1]),
        "recent_orders": orders,
        "recent_keys": keys,
    }


@router.post("/sessions/issue")
async def issue_portal_session(
    body: PortalSessionIssueRequest,
    x_portal_token: Annotated[str | None, Header()] = None,
):
    _require_internal_token(x_portal_token)
    user = await get_user_by_telegram_id(body.telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    session_token = _serializer().dumps(
        {
            "telegram_id": int(user["telegram_id"]),
            "user_id": int(user["id"]),
            "is_banned": bool(user.get("is_banned")),
        }
    )
    return {"session_token": session_token}


@router.post("/sessions/verify")
async def verify_portal_session(
    body: PortalSessionVerifyRequest,
    x_portal_token: Annotated[str | None, Header()] = None,
):
    _require_internal_token(x_portal_token)
    try:
        payload = _serializer().loads(body.session_token)
    except BadSignature as exc:
        raise HTTPException(status_code=401, detail="Invalid session token") from exc

    user = await get_user_by_telegram_id(int(payload["telegram_id"]))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "valid": True,
        "telegram_id": int(user["telegram_id"]),
        "user_id": int(user["id"]),
        "is_banned": bool(user.get("is_banned")),
    }
