"""Auth helpers for admin and internal APIs."""
from __future__ import annotations

from fastapi import Header, HTTPException

from app.config import get_settings


def require_control_plane_token(
    x_control_plane_token: str | None = Header(default=None),
) -> None:
    expected = get_settings().control_plane_token.strip()
    if not expected or x_control_plane_token != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")
