"""Verification for analytics ranges and NewAPI server config fields."""
from __future__ import annotations

import asyncio
import sys
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from bot.config import settings
from bot.utils.time_utils import get_now_vn, to_db_time_string
from db.database import close_db, get_db
from db.models import init_db
from db.queries.analytics import get_analytics_summary, get_dashboard_overview
from db.queries.orders import create_order, update_order_status
from db.queries.servers import create_server, get_server_by_id, update_server
from db.queries.users import create_user


async def _seed_orders(user_id: int, server_id: int) -> None:
    now = get_now_vn()
    yesterday = now.replace(hour=9, minute=0, second=0, microsecond=0) - timedelta(days=1)
    today = now.replace(hour=10, minute=0, second=0, microsecond=0)
    last_month = (now.replace(day=1, hour=11, minute=0, second=0, microsecond=0) - timedelta(days=2)).replace(day=5)

    order_yesterday = await create_order(
        order_code="ORD-AN-001",
        user_id=user_id,
        product_type="key_new",
        amount=10000,
        payment_method="wallet",
        server_id=server_id,
    )
    await update_order_status(order_yesterday, "completed")

    order_today = await create_order(
        order_code="ORD-AN-002",
        user_id=user_id,
        product_type="key_new",
        amount=20000,
        payment_method="wallet",
        server_id=server_id,
    )
    await update_order_status(order_today, "completed")

    order_last_month = await create_order(
        order_code="ORD-AN-003",
        user_id=user_id,
        product_type="key_new",
        amount=30000,
        payment_method="wallet",
        server_id=server_id,
    )
    await update_order_status(order_last_month, "completed")

    refund_order = await create_order(
        order_code="ORD-AN-004",
        user_id=user_id,
        product_type="key_new",
        amount=5000,
        payment_method="wallet",
        server_id=server_id,
    )

    db = await get_db()
    await db.execute(
        """UPDATE orders
           SET created_at = ?, completed_at = ?, paid_at = ?, status = 'completed'
           WHERE id = ?""",
        (to_db_time_string(yesterday), to_db_time_string(today), to_db_time_string(yesterday), order_yesterday),
    )
    await db.execute(
        """UPDATE orders
           SET created_at = ?, completed_at = ?, paid_at = ?, status = 'completed'
           WHERE id = ?""",
        (to_db_time_string(today), to_db_time_string(today), to_db_time_string(today), order_today),
    )
    await db.execute(
        """UPDATE orders
           SET created_at = ?, completed_at = ?, paid_at = ?, status = 'completed'
           WHERE id = ?""",
        (to_db_time_string(last_month), to_db_time_string(last_month), to_db_time_string(last_month), order_last_month),
    )
    await db.execute(
        """UPDATE orders
           SET created_at = ?,
               status = 'refunded',
               is_refunded = 1,
               refunded_at = ?,
               completed_at = ?,
               paid_at = ?
           WHERE id = ?""",
        (
            to_db_time_string(today),
            to_db_time_string(today),
            to_db_time_string(today),
            to_db_time_string(today),
            refund_order,
        ),
    )
    await db.commit()


async def main() -> None:
    original_db_path = settings.db_path

    with TemporaryDirectory() as temp_dir:
        temp_db = Path(temp_dir) / "analytics-server-config.db"
        await close_db()
        object.__setattr__(settings, "db_path", str(temp_db))

        try:
            await init_db()
            db = await get_db()

            cursor = await db.execute("PRAGMA table_info(api_servers)")
            server_columns = {row[1] for row in await cursor.fetchall()}
            assert "supports_key_lookup_by_id" in server_columns
            assert "token_key_endpoint_template" in server_columns

            cursor = await db.execute("PRAGMA table_info(orders)")
            order_columns = {row[1] for row in await cursor.fetchall()}
            assert "completed_at" in order_columns
            print("[OK] migrations add server key-lookup config and orders.completed_at")

            user = await create_user(telegram_id=900001, username="analytics-user", full_name="Analytics User")
            server_id = await create_server(
                name="NewAPI Verify",
                base_url="https://verify.example.com",
                user_id_header="new-api-user",
                access_token="secret",
                price_per_unit=1000,
                quota_per_unit=1000,
                api_type="newapi",
                supports_key_lookup_by_id=1,
                token_key_endpoint_template="/api/token/{id}/key",
            )
            await update_server(server_id, token_key_endpoint_template="/api/token/{id}/key")
            server = await get_server_by_id(server_id)
            assert server is not None
            assert server["supports_key_lookup_by_id"] == 1
            assert server["token_key_endpoint_template"] == "/api/token/{id}/key"
            print("[OK] server config persists key-by-id capability")

            await _seed_orders(user["id"], server_id)

            overview = await get_dashboard_overview()
            assert overview["today_revenue"] == 30000
            assert overview["month_revenue"] == 30000
            assert overview["today_orders"] >= 2
            assert overview["month_orders"] >= 3
            print("[OK] dashboard overview uses completed_at for revenue and created_at for order counts")

            today_summary = await get_analytics_summary("today")
            assert today_summary["gross_revenue"] == 30000
            assert today_summary["refunded_amount"] == 5000

            this_month_summary = await get_analytics_summary("this_month")
            assert this_month_summary["gross_revenue"] == 30000

            last_month_summary = await get_analytics_summary("last_month")
            assert last_month_summary["gross_revenue"] == 30000
            print("[OK] analytics separates today / this month / last month correctly")

            from admin.app import create_admin_app
            from admin.deps import require_admin

            app = create_admin_app()
            app.dependency_overrides[require_admin] = lambda: {"admin": True}
            with TestClient(app) as client:
                analytics_page = client.get("/analytics?range_key=today")
                assert analytics_page.status_code == 200
                assert "Analytics" in analytics_page.text
                dashboard_page = client.get("/")
                assert dashboard_page.status_code == 200
                assert "Doanh thu hom nay" in dashboard_page.text
            print("[OK] admin dashboard and analytics page render with the new overview")

            print("\n=== ANALYTICS AND SERVER CONFIG VERIFICATION PASSED ===")
        finally:
            await close_db()
            object.__setattr__(settings, "db_path", original_db_path)


if __name__ == "__main__":
    asyncio.run(main())
