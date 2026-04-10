"""Quick verification script for active admin app wiring."""
import asyncio
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from db.database import close_db
from db.models import init_db


async def main() -> None:
    await init_db()

    from admin.app import create_admin_app

    app = create_admin_app()
    routes = [route.path for route in app.routes]
    print(f"[OK] admin app - {len(routes)} routes registered")

    from admin.routers.account_stock import router as account_stock_router
    from admin.routers.analytics import router as analytics_router
    from admin.routers.auth import router as auth_router
    from admin.routers.broadcast import router as broadcast_router
    from admin.routers.categories import router as categories_router
    from admin.routers.dashboard import router as dashboard_router
    from admin.routers.logs import router as logs_router
    from admin.routers.orders import router as orders_router
    from admin.routers.products import router as products_router
    from admin.routers.servers import router as servers_router
    from admin.routers.settings import router as settings_router
    from admin.routers.users import router as users_router

    _ = (
        auth_router,
        dashboard_router,
        analytics_router,
        servers_router,
        categories_router,
        products_router,
        settings_router,
        orders_router,
        users_router,
        account_stock_router,
        logs_router,
        broadcast_router,
    )
    print("[OK] admin routers import cleanly")

    from admin.deps import get_templates, require_admin

    _ = require_admin
    templates = get_templates()
    print(f"[OK] templates instance created: {type(templates).__name__}")

    root_dir = str(ROOT_DIR)
    template_dir = os.path.join(root_dir, "admin", "templates")
    template_files = os.listdir(template_dir)
    print(f"[OK] {len(template_files)} template files found")

    css_path = os.path.join(root_dir, "admin", "static", "css", "style.css")
    js_path = os.path.join(root_dir, "admin", "static", "js", "app.js")
    assert os.path.exists(css_path), "CSS missing"
    assert os.path.exists(js_path), "JS missing"
    print("[OK] static files: CSS + JS")

    await close_db()
    print("\n=== ALL PHASE 4 TESTS PASSED ===")


asyncio.run(main())
