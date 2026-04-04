"""FastAPI application factory."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings

_BASE_DIR = Path(__file__).resolve().parent.parent
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    from app.auto_sync import AutoSyncPoller
    from app.control_plane import import_control_plane_sources
    from db.database import close_db, init_db

    await init_db()
    try:
        await import_control_plane_sources()
    except Exception as exc:
        logger.warning("Control-plane import skipped: %s", exc)
    poller = AutoSyncPoller()
    await poller.start()
    app.state.auto_sync_poller = poller
    try:
        yield
    finally:
        await poller.stop()
        await close_db()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_title,
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.admin_secret,
    )

    # Static files
    static_dir = _BASE_DIR / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # --- Public routers ---
    from app.routers.public_landing import router as landing_router
    from app.routers.public_balance import router as balance_router
    from app.routers.public_pricing import router as pricing_router
    from app.routers.public_status import router as status_router
    from app.routers.public_logs import router as logs_router
    from app.routers.public_keys import router as keys_router
    from app.routers.internal_admin_pricing import router as internal_admin_pricing_router

    app.include_router(landing_router)
    app.include_router(balance_router)
    app.include_router(pricing_router)
    app.include_router(status_router)
    app.include_router(logs_router)
    app.include_router(keys_router)
    app.include_router(internal_admin_pricing_router)

    # --- API routers ---
    from app.routers.api_pricing import router as api_pricing_router
    from app.routers.api_logs import router as api_logs_router
    from app.routers.api_keys import router as api_keys_router

    app.include_router(api_pricing_router)
    app.include_router(api_logs_router)
    app.include_router(api_keys_router)

    # Health check
    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app
