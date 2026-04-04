"""Verification for unified admin entity states and inline toggles."""
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
from db.queries.account_stocks import add_account
from db.queries.categories import create_category, get_category_by_id, update_category
from db.queries.products import create_product, get_product_by_id, update_product
from db.queries.servers import create_server, get_server_by_id, update_server


async def _seed_entities() -> dict[str, int]:
    category_active_id = await create_category(
        name="Danh mục bật",
        icon="📦",
        description="Danh mục đang bật",
        cat_type="general",
        sort_order=1,
    )
    category_inactive_id = await create_category(
        name="Danh mục tắt",
        icon="🧰",
        description="Danh mục đang tắt",
        cat_type="general",
        sort_order=2,
    )
    await update_category(category_inactive_id, is_active=0)

    server_active_id = await create_server(
        name="Server bật",
        base_url="https://active.example.com",
        user_id_header="new-api-user",
        access_token="secret",
        price_per_unit=1000,
        quota_per_unit=1000,
    )
    server_inactive_id = await create_server(
        name="Server tắt",
        base_url="https://inactive.example.com",
        user_id_header="new-api-user",
        access_token="secret",
        price_per_unit=1000,
        quota_per_unit=1000,
    )
    await update_server(server_inactive_id, is_active=0)

    product_unlimited_id = await create_product(
        category_id=category_active_id,
        name="Gói không giới hạn",
        price_vnd=1000,
        product_type="service_upgrade",
        description="Dịch vụ không giới hạn",
        stock=-1,
    )
    product_limited_id = await create_product(
        category_id=category_active_id,
        name="Gói giới hạn",
        price_vnd=2000,
        product_type="service_upgrade",
        description="Dịch vụ giới hạn",
        stock=7,
    )
    await update_product(product_limited_id, is_active=0)

    product_stocked_id = await create_product(
        category_id=category_active_id,
        name="Tài khoản có sẵn",
        price_vnd=3000,
        product_type="account_stocked",
        description="Tài khoản trong kho",
        stock=-1,
    )
    await add_account(product_stocked_id, "user1|pass1")
    await add_account(product_stocked_id, "user2|pass2")

    return {
        "category_active": category_active_id,
        "category_inactive": category_inactive_id,
        "server_active": server_active_id,
        "server_inactive": server_inactive_id,
        "product_unlimited": product_unlimited_id,
        "product_limited": product_limited_id,
        "product_stocked": product_stocked_id,
    }


async def main() -> None:
    original_db_path = settings.db_path

    with TemporaryDirectory() as temp_dir:
        temp_db = Path(temp_dir) / "admin-entity-states.db"
        await close_db()
        object.__setattr__(settings, "db_path", str(temp_db))

        try:
            await init_db()
            ids = await _seed_entities()

            from admin.app import create_admin_app
            from admin.deps import require_admin

            app = create_admin_app()
            app.dependency_overrides[require_admin] = lambda: {"admin": True}

            with TestClient(app) as client:
                servers_page = client.get("/servers")
                assert servers_page.status_code == 200
                servers_text = servers_page.text
                assert "Đang bật" in servers_text
                assert "Tạm tắt" in servers_text
                assert f'/servers/{ids["server_active"]}/toggle-active' in servers_text
                print("[OK] servers list uses unified state wording and inline toggle")

                categories_page = client.get("/categories")
                assert categories_page.status_code == 200
                categories_text = categories_page.text
                assert "Đang bật" in categories_text
                assert "Tạm tắt" in categories_text
                assert f'/categories/{ids["category_active"]}/toggle-active' in categories_text
                print("[OK] categories list uses unified state wording and inline toggle")

                products_page = client.get("/products")
                assert products_page.status_code == 200
                products_text = products_page.text
                assert "Máy chủ đang bật" in products_text
                assert "Không giới hạn" in products_text
                assert "Tài khoản khả dụng" in products_text
                assert "Sẵn sàng bán" in products_text
                assert f'/products/{ids["product_unlimited"]}/toggle-active' in products_text
                print("[OK] products list separates status from stock and uses inline toggle")

                servers_edit_page = client.get(f'/servers/{ids["server_active"]}/edit')
                assert servers_edit_page.status_code == 200
                assert "Trạng thái: Đang bật" in servers_edit_page.text

                categories_edit_page = client.get(f'/categories/{ids["category_inactive"]}/edit')
                assert categories_edit_page.status_code == 200
                assert "Trạng thái: Tạm tắt" in categories_edit_page.text

                products_edit_page = client.get(f'/products/{ids["product_limited"]}/edit')
                assert products_edit_page.status_code == 200
                assert "Trạng thái: Tạm tắt" in products_edit_page.text
                print("[OK] edit forms use unified state checkbox copy")

                server_toggle = client.post(
                    f'/servers/{ids["server_active"]}/toggle-active',
                    data={"next": "/servers?view=compact"},
                    follow_redirects=False,
                )
                assert server_toggle.status_code == 303
                assert server_toggle.headers["location"] == "/servers?view=compact"
                server_after_toggle = await get_server_by_id(ids["server_active"])
                assert server_after_toggle is not None and server_after_toggle["is_active"] == 0

                category_toggle = client.post(
                    f'/categories/{ids["category_inactive"]}/toggle-active',
                    data={"next": "/categories?page=1"},
                    follow_redirects=False,
                )
                assert category_toggle.status_code == 303
                assert category_toggle.headers["location"] == "/categories?page=1"
                category_after_toggle = await get_category_by_id(ids["category_inactive"])
                assert category_after_toggle is not None and category_after_toggle["is_active"] == 1

                product_toggle = client.post(
                    f'/products/{ids["product_unlimited"]}/toggle-active',
                    data={"next": "/products"},
                    follow_redirects=False,
                )
                assert product_toggle.status_code == 303
                assert product_toggle.headers["location"] == "/products"
                product_after_toggle = await get_product_by_id(ids["product_unlimited"])
                assert product_after_toggle is not None and product_after_toggle["is_active"] == 0
                print("[OK] toggle routes flip is_active and preserve redirect target")

            print("\n=== ADMIN ENTITY STATE VERIFICATION PASSED ===")
        finally:
            await close_db()
            object.__setattr__(settings, "db_path", original_db_path)


if __name__ == "__main__":
    asyncio.run(main())
