"""Focused verification for order and payment flows on a temporary database."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from bot.config import settings
from db.database import close_db
from db.models import init_db
from db.queries.account_stocks import add_account
from db.queries.categories import create_category
from db.queries.orders import (
    count_all_orders,
    count_orders_by_user,
    create_order,
    get_all_orders,
    get_order_by_code,
    get_order_by_id,
    get_orders_by_user,
    get_pending_qr_orders,
    update_order_status,
)
from db.queries.products import (
    create_product,
    get_active_products_by_category,
    get_product_by_id,
)
from db.queries.servers import create_server
from db.queries.users import create_user
from db.queries.wallets import (
    add_balance,
    charge_pending_order_from_wallet,
    complete_wallet_topup_order,
    count_wallet_transactions,
    get_balance,
    get_wallet_transactions,
    refund_order_to_wallet,
)


async def main() -> None:
    original_db_path = settings.db_path

    with TemporaryDirectory() as temp_dir:
        temp_db = Path(temp_dir) / "phase5.db"
        await close_db()
        object.__setattr__(settings, "db_path", str(temp_db))

        try:
            await init_db()

            user = await create_user(telegram_id=10001, username="phase5", full_name="Phase 5")
            category_id = await create_category("API Keys", cat_type="key_api")
            server_id = await create_server(
                name="Test Server",
                base_url="https://example.com",
                user_id_header="new-api-user",
                access_token="secret",
                price_per_unit=1000,
                quota_per_unit=1000,
            )

            key_product_id = await create_product(
                category_id=category_id,
                server_id=server_id,
                name="Starter Key",
                price_vnd=50000,
                product_type="key_new",
                quota_amount=250000,
                group_name="default",
            )
            stocked_product_id = await create_product(
                category_id=category_id,
                name="Stock Account",
                price_vnd=30000,
                product_type="account_stocked",
                stock=-1,
            )
            await add_account(stocked_product_id, "demo@example.com|password")

            stocked_product = await get_product_by_id(stocked_product_id)
            assert stocked_product is not None and stocked_product["stock"] == 1
            print("[OK] get_product_by_id hydrates real stock for account_stocked products")

            active_key_products = await get_active_products_by_category(
                category_id,
                server_id=server_id,
                product_type="key_new",
            )
            assert len(active_key_products) == 1 and active_key_products[0]["id"] == key_product_id
            print("[OK] get_active_products_by_category filters by server and product_type")

            order_id = await create_order(
                order_code="ORDPHASE5001",
                user_id=user["id"],
                product_id=key_product_id,
                product_name="Starter Key",
                product_type="key_new",
                amount=50000,
                payment_method="wallet",
                server_id=server_id,
                group_name="default",
            )
            order = await get_order_by_id(order_id)
            assert order is not None and order["status"] == "pending"
            assert (await get_order_by_code("ORDPHASE5001"))["id"] == order_id
            print("[OK] create_order + get_order_by_id/get_order_by_code work together")

            await add_balance(user["id"], 200000, "seed", description="Seed balance for verification")
            charged_order = await charge_pending_order_from_wallet(order_id)
            assert charged_order is not None and charged_order["status"] == "paid"
            assert charged_order["payment_method"] == "wallet"
            assert await get_balance(user["id"]) == 150000
            print("[OK] charge_pending_order_from_wallet marks order paid and deducts wallet balance")

            refunded_balance = await refund_order_to_wallet(
                order_id,
                reason="Verification refund",
                tx_type="refund",
                description="Verification refund",
            )
            refunded_order = await get_order_by_id(order_id)
            assert refunded_balance == 200000
            assert refunded_order is not None and refunded_order["status"] == "refunded"
            assert refunded_order["is_refunded"] == 1
            print("[OK] refund_order_to_wallet restores balance and marks the order refunded")

            qr_order_id = await create_order(
                order_code="ORDPHASE5002",
                user_id=user["id"],
                product_type="wallet_topup",
                amount=70000,
                payment_method="qr",
                product_name="Wallet topup",
            )
            pending_qr_ids = {item["id"] for item in await get_pending_qr_orders()}
            assert qr_order_id in pending_qr_ids
            assert order_id not in pending_qr_ids
            print("[OK] get_pending_qr_orders only returns pending QR orders")

            await update_order_status(qr_order_id, "paid")
            topped_up_balance = await complete_wallet_topup_order(qr_order_id)
            topped_up_order = await get_order_by_id(qr_order_id)
            assert topped_up_balance == 270000
            assert topped_up_order is not None and topped_up_order["status"] == "completed"
            print("[OK] complete_wallet_topup_order credits wallet and completes topup orders")

            all_orders = await get_all_orders(limit=10)
            searched_orders = await get_all_orders(limit=10, search="ORDPHASE5001")
            assert len(all_orders) == 2
            assert len(searched_orders) == 1 and searched_orders[0]["id"] == order_id
            assert await count_all_orders() == 2
            assert await count_all_orders(search="ORDPHASE5001") == 1
            print("[OK] get_all_orders/count_all_orders support pagination and search filters")

            user_orders = await get_orders_by_user(user["id"], limit=10)
            assert len(user_orders) == 2
            assert await count_orders_by_user(user["id"]) == 2
            print("[OK] get_orders_by_user/count_orders_by_user return user order history")

            transactions = await get_wallet_transactions(user["id"], limit=10)
            tx_types = {tx["type"] for tx in transactions}
            assert len(transactions) == 4
            assert tx_types == {"seed", "purchase", "refund", "topup"}
            assert await count_wallet_transactions(user["id"]) == 4
            print("[OK] wallet transaction history captures seed, purchase, refund, and topup")

            print("\n=== ALL PHASE 5 TESTS PASSED ===")
        finally:
            await close_db()
            object.__setattr__(settings, "db_path", original_db_path)


asyncio.run(main())
