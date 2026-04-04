"""
Signed launch-token bridge from platform-control into the isolated Shopbot admin runtime.
"""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from admin.deps import get_templates
from bot.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth-launch"])


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.admin_launch_secret, salt="shopbot-admin-launch")


def _render_login(request: Request, error: str) -> HTMLResponse:
    templates = get_templates()
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": error, "post_url": settings.admin_login_path},
        status_code=401,
    )


@router.post("/sso/consume", response_class=HTMLResponse)
async def consume_launch_token(request: Request, token: str = Form(...)):
    if not settings.admin_launch_secret.strip():
        logger.error("Shopbot admin launch attempted without ADMIN_LAUNCH_SECRET configured")
        return _render_login(request, "Admin launch bridge chua duoc cau hinh.")

    try:
        payload = _serializer().loads(token, max_age=max(settings.admin_launch_ttl_seconds, 30))
    except SignatureExpired:
        logger.warning("Expired shopbot admin launch token")
        return _render_login(request, "Lien ket admin da het han. Vui long mo lai tu admin.shupremium.com.")
    except BadSignature:
        logger.warning("Invalid shopbot admin launch token")
        return _render_login(request, "Lien ket admin khong hop le.")

    now = int(time.time())
    issuer = str(payload.get("issuer") or "").rstrip("/")
    expected_issuer = settings.platform_admin_url.rstrip("/")
    nonce = str(payload.get("nonce") or "").strip()
    subject = str(payload.get("sub") or "").strip()
    expires_at = int(payload.get("expires_at") or 0)

    if not nonce or not subject or not issuer or issuer != expected_issuer or (expires_at and expires_at < now):
        logger.warning("Rejected shopbot admin launch token: issuer=%s subject=%s nonce=%s", issuer, subject, nonce)
        return _render_login(request, "Lien ket admin khong hop le hoac da het han.")

    request.session["admin"] = {
        "source": "platform-control",
        "subject": subject,
        "issuer": issuer,
        "nonce": nonce,
        "launched_at": now,
    }
    return RedirectResponse("/", status_code=303)
