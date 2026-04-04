"""
admin/app.py - FastAPI app setup with templates, static files, and routers.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from admin.routers import PROTECTED_ROUTERS, PUBLIC_ROUTERS
from bot.config import settings

_BASE_DIR = Path(__file__).resolve().parent


def create_admin_app() -> FastAPI:
    """Create the FastAPI application for the admin panel."""
    app = FastAPI(title="ShopBot Admin", docs_url=None, redoc_url=None)

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.admin_secret_key,
    )

    static_dir = _BASE_DIR / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    (static_dir / "css").mkdir(parents=True, exist_ok=True)
    (static_dir / "js").mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    for router in PUBLIC_ROUTERS:
        app.include_router(router)

    @app.get("/health")
    async def health_check() -> dict[str, str]:
        from bot.utils.time_utils import get_now_vn

        return {"status": "ok", "timestamp": get_now_vn().isoformat()}

    for router in PROTECTED_ROUTERS:
        app.include_router(router)

    return app
