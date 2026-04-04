"""Verification for admin order detail, complete, and refund flows."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from bot.config import settings
from db.database import close_db
from db.models import init_db
from db.queries.categories import create_category
from db.queries.orders import create_order, get_order_by_id, update_order_status
from db.queries.products import create_product
from db.queries.servers import create_server
from db.queries.users import create_user
from db.queries.wallets import add_balance, charge_pending_order_from_wallet


async def _seed_completed_service_upgrade_order(user_id: int) -> int:
    order_id = await create_order(
        order_code="ADMINCOMPLETE001",
        user_id=user_id,
        product_name="Service Upgrade",
        product_type="service_upgrade",
        amount=25_000,
        payment_method="qr",
    )
    await update_order_status(order_id, "processing")
    return order_id


async def _seed_refundable_order(user_id: int, product_id: int, server_id: int) -> int:
    order_id = await create_order(
        order_code="ADMINREFUND001",
        user_id=user_id,
        product_id=product_id,
        product_name="Refundable Key",
        product_type="key_new",
        amount=50_000,
        payment_method="wallet",
        server_id=server_id,
        group_name="default",
    )
    await add_balance(user_id, 150_000, "seed", description="Seed balance for admin refund verify")
    charged = await charge_pending_order_from_wallet(order_id)
    assert charged is not None and charged["status"] == "paid"
    return order_id


async def main() -> None:
    original_db_path = settings.db_path

    with TemporaryDirectory() as temp_dir:
        temp_db = Path(temp_dir) / "admin-orders.db"
        await close_db()
        object.__setattr__(settings, "db_path", str(temp_db))

        try:
            await init_db()

            user = await create_user(
                telegram_id=20001,
                username="admin-orders",
                full_name="Admin Orders Verify",
            )
            category_id = await create_category("Admin Keys", cat_type="key_api")
            server_id = await create_server(
                name="Admin Order Server",
                base_url="https://example.com",
                user_id_header="new-api-user",
                access_token="secret",
                price_per_unit=1000,
                quota_per_unit=1000,
            )
            product_id = await create_product(
                category_id=category_id,
                server_id=server_id,
                name="Refundable Key",
                price_vnd=50_000,
                product_type="key_new",
                quota_amount=100_000,
                group_name="default",
            )

            complete_order_id = await _seed_completed_service_upgrade_order(user["id"])
            refund_order_id = await _seed_refundable_order(user["id"], product_id, server_id)

            from admin.app import create_admin_app
            from admin.deps import require_admin
            import admin.routers.orders as orders_router

            notifications: list[tuple[int, str]] = []
            admin_events: list[tuple[str, str]] = []

            async def _fake_notify_user(user_id: int, text: str) -> None:
                notifications.append((user_id, text))

            async def _fake_notify_admin_service_completed(order: dict, *, bot=None) -> tuple[int, int, int]:
                _ = bot
                admin_events.append(("service_completed", order["order_code"]))
                return (1, 0, 0)

            async def _fake_notify_admin_order_refunded(
                order: dict,
                *,
                bot=None,
                reason: str | None = None,
            ) -> tuple[int, int, int]:
                _ = bot
                admin_events.append(("order_refunded", f"{order['order_code']}|{reason or ''}"))
                return (1, 0, 0)

            app = create_admin_app()
            app.dependency_overrides[require_admin] = lambda: {"admin": True}

            original_notify_user = orders_router.notify_user
            original_notify_admin_service_completed = orders_router.notify_admin_service_completed
            original_notify_admin_order_refunded = orders_router.notify_admin_order_refunded
            orders_router.notify_user = _fake_notify_user
            orders_router.notify_admin_service_completed = _fake_notify_admin_service_completed
            orders_router.notify_admin_order_refunded = _fake_notify_admin_order_refunded
            try:
                with TestClient(app) as client:
                    detail_response = client.get(f"/orders/{refund_order_id}")
                    assert detail_response.status_code == 200
                    assert "ADMINREFUND001" in detail_response.text
                    assert "Admin Order Server" in detail_response.text
                    print("[OK] order_detail renders the selected order in admin UI")

                    complete_response = client.post(
                        f"/orders/{complete_order_id}/complete",
                        follow_redirects=False,
                    )
                    assert complete_response.status_code == 303
                    assert complete_response.headers["location"] == f"/orders/{complete_order_id}"
                    completed_order = await get_order_by_id(complete_order_id)
                    assert completed_order is not None
                    assert completed_order["status"] == "completed"
                    assert any("ADMINCOMPLETE001" in text for _, text in notifications)
                    assert ("service_completed", "ADMINCOMPLETE001") in admin_events
                    print("[OK] order_complete marks service upgrades completed and notifies the user")

                    refund_response = client.get(
                        f"/orders/{refund_order_id}/refund",
                        follow_redirects=False,
                    )
                    assert refund_response.status_code == 303
                    assert refund_response.headers["location"] == f"/orders/{refund_order_id}"
                    refunded_order = await get_order_by_id(refund_order_id)
                    assert refunded_order is not None
                    assert refunded_order["status"] == "refunded"
                    assert refunded_order["is_refunded"] == 1
                    assert any("ADMINREFUND001" in text for _, text in notifications)
                    assert ("order_refunded", "ADMINREFUND001|Admin hoàn tiền") in admin_events
                    print("[OK] order_refund credits the wallet and redirects back to order detail")

                print("\n=== ADMIN ORDER ACTION VERIFICATION PASSED ===")
            finally:
                orders_router.notify_user = original_notify_user
                orders_router.notify_admin_service_completed = original_notify_admin_service_completed
                orders_router.notify_admin_order_refunded = original_notify_admin_order_refunded
        finally:
            await close_db()
            object.__setattr__(settings, "db_path", original_db_path)


asyncio.run(main())
