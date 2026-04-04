"""Focused verification for pricing snapshots, spend ledger, and imported-key accrual."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from bot.config import settings
from bot.services.key_valuation import KeyValuationService, hash_api_key
from bot.services.pricing_resolver import quote_api_order, quote_non_api_product
from bot.services.spend_ledger import SpendLedgerService
from db.database import close_db
from db.models import init_db
from db.queries.categories import create_category
from db.queries.orders import create_order, get_order_by_id
from db.queries.pricing import (
    get_primary_product_promotion,
    list_server_pricing_versions,
    replace_primary_product_promotion,
    replace_server_discount_tiers,
    sync_server_pricing_version,
)
from db.queries.products import create_product
from db.queries.servers import create_server, update_server
from db.queries.spend import (
    find_api_key_registry,
    get_user_server_total_spend,
    list_key_valuation_events,
    list_spend_ledger,
)
from db.queries.user_keys import find_user_key_by_api_key
from db.queries.users import create_user, set_admin, set_discount_disabled
from db.queries.wallets import refund_order_to_wallet


async def main() -> None:
    original_db_path = settings.db_path

    with TemporaryDirectory() as temp_dir:
        temp_db = Path(temp_dir) / "discount_ledger.db"
        await close_db()
        object.__setattr__(settings, "db_path", str(temp_db))

        try:
            await init_db()

            user = await create_user(telegram_id=21001, username="tiered", full_name="Tiered User")
            other_user = await create_user(telegram_id=21002, username="other", full_name="Other User")
            admin_user = await create_user(telegram_id=21003, username="admin", full_name="Admin User")
            blocked_user = await create_user(telegram_id=21004, username="blocked", full_name="Blocked User")
            category_id = await create_category("API Keys", cat_type="key_api")
            general_category_id = await create_category("Services", cat_type="general")
            server_id = await create_server(
                name="Discount Server",
                base_url="https://example.com",
                user_id_header="new-api-user",
                access_token="secret",
                price_per_unit=10000,
                quota_per_unit=1000000,
                dollar_per_unit=10.0,
                quota_multiple=1.0,
                import_spend_accrual_enabled=1,
                discount_stack_mode="exclusive",
            )
            await sync_server_pricing_version(server_id)
            await replace_server_discount_tiers(
                server_id,
                [
                    {
                        "name": "Silver",
                        "min_spend_vnd": 15000,
                        "benefits": [{"type": "percent_off", "value": 10}],
                    }
                ],
            )

            key_product_id = await create_product(
                category_id=category_id,
                server_id=server_id,
                name="Key $20",
                price_vnd=20000,
                product_type="key_new",
                quota_amount=2000000,
                dollar_amount=20,
            )
            general_product_id = await create_product(
                category_id=general_category_id,
                name="Managed Service",
                price_vnd=100000,
                product_type="service_upgrade",
            )
            await replace_primary_product_promotion(
                general_product_id,
                {
                    "name": "Launch promo",
                    "promotion_type": "percent_off",
                    "value_amount": 10,
                    "priority": 10,
                    "is_active": True,
                },
            )

            server = {
                "id": server_id,
                "price_per_unit": 10000,
                "quota_per_unit": 1000000,
                "dollar_per_unit": 10.0,
                "quota_multiple": 1.0,
                "discount_stack_mode": "exclusive",
                "discount_allowed_stack_types": "cashback",
            }
            product = {"id": key_product_id, "price_vnd": 20000, "quota_amount": 2000000, "dollar_amount": 20}

            initial_quote = await quote_api_order(user_id=user["id"], server=server, product=product)
            assert initial_quote.payable_amount == 20000
            assert initial_quote.discount_amount == 0
            print("[OK] Initial API quote uses base price before tier thresholds are met")

            order_id = await create_order(
                order_code="ORDLEDGER001",
                user_id=user["id"],
                product_id=key_product_id,
                product_name="Key $20",
                product_type="key_new",
                amount=initial_quote.payable_amount,
                payment_method="wallet",
                server_id=server_id,
                base_amount=initial_quote.base_amount,
                discount_amount=initial_quote.discount_amount,
                cashback_amount=initial_quote.cashback_amount,
                spend_credit_amount=initial_quote.spend_credit_amount,
                pricing_version_id=initial_quote.pricing_version_id,
                applied_tier_id=initial_quote.applied_tier_id,
                pricing_snapshot=json.dumps(initial_quote.pricing_snapshot, ensure_ascii=True),
            )
            order = await get_order_by_id(order_id)
            assert order is not None
            assert await SpendLedgerService.record_order_completion(order) is not None
            assert await SpendLedgerService.record_order_completion(order) is None
            assert await get_user_server_total_spend(user["id"], server_id) == 20000
            print("[OK] Completing an API order credits spend once and updates the summary")

            discounted_quote = await quote_api_order(user_id=user["id"], server=server, product=product)
            assert discounted_quote.discount_amount == 2000
            assert discounted_quote.payable_amount == 18000
            print("[OK] Tier discount activates automatically from per-server spend summary")

            await set_admin(admin_user["id"], 1)
            admin_order_id = await create_order(
                order_code="ORDLEDGERADM001",
                user_id=admin_user["id"],
                product_id=key_product_id,
                product_name="Key $20",
                product_type="key_new",
                amount=initial_quote.payable_amount,
                payment_method="wallet",
                server_id=server_id,
                base_amount=initial_quote.base_amount,
                discount_amount=0,
                cashback_amount=0,
                spend_credit_amount=initial_quote.spend_credit_amount,
                pricing_version_id=initial_quote.pricing_version_id,
                applied_tier_id=None,
                pricing_snapshot=json.dumps(initial_quote.pricing_snapshot, ensure_ascii=True),
            )
            admin_order = await get_order_by_id(admin_order_id)
            assert admin_order is not None
            await SpendLedgerService.record_order_completion(admin_order)
            admin_quote = await quote_api_order(user_id=admin_user["id"], server=server, product=product)
            assert admin_quote.discount_amount == 0
            assert admin_quote.payable_amount == 20000
            print("[OK] Admin users bypass API-key tier discounts even after accumulating spend")

            valuation = await KeyValuationService.evaluate_imported_key(
                user_id=user["id"],
                server=server,
                api_key="sk-imported-key-12345678901234567890",
                token_data={"id": 77, "remain_quota": 500000, "used_quota": 500000},
            )
            assert valuation["status"] == "credited"
            assert valuation["credited_delta_quota"] == 1000000
            assert valuation["credited_value_vnd"] == 10000
            assert await get_user_server_total_spend(user["id"], server_id) == 30000
            registry = await find_api_key_registry(server_id, hash_api_key("sk-imported-key-12345678901234567890"))
            assert registry is not None and registry["owner_user_id"] == user["id"]
            print("[OK] First imported key binds ownership and credits its full observed value")

            no_change = await KeyValuationService.evaluate_imported_key(
                user_id=user["id"],
                server=server,
                api_key="sk-imported-key-12345678901234567890",
                token_data={"id": 77, "remain_quota": 500000, "used_quota": 500000},
            )
            assert no_change["status"] == "no_change"
            assert await get_user_server_total_spend(user["id"], server_id) == 30000
            print("[OK] Re-importing the same observed quota does not double count spend")

            delta_credit = await KeyValuationService.evaluate_imported_key(
                user_id=user["id"],
                server=server,
                api_key="sk-imported-key-12345678901234567890",
                token_data={"id": 77, "remain_quota": 400000, "used_quota": 1100000},
            )
            assert delta_credit["credited_delta_quota"] == 500000
            assert delta_credit["credited_value_vnd"] == 5000
            assert await get_user_server_total_spend(user["id"], server_id) == 35000
            print("[OK] Importing a higher observed total only credits the delta quota")

            mismatch = await KeyValuationService.evaluate_imported_key(
                user_id=other_user["id"],
                server=server,
                api_key="sk-imported-key-12345678901234567890",
                token_data={"id": 77, "remain_quota": 300000, "used_quota": 1200000},
            )
            assert mismatch["status"] == "owner_mismatch"
            assert await get_user_server_total_spend(other_user["id"], server_id) == 0
            linked_key = await find_user_key_by_api_key(
                other_user["id"],
                "sk-imported-key-12345678901234567890",
            )
            assert linked_key is not None
            print("[OK] Owner-locked imported keys skip accrual for other users but still allow topup linkage")

            await KeyValuationService.record_platform_quota_offset(
                user_id=other_user["id"],
                server=server,
                api_key="sk-imported-key-12345678901234567890",
                quota_delta=250000,
                resulting_total_quota=1750000,
                source="platform_key_topup",
                source_ref="order:sim-topup-1",
            )
            imported_after_topup = await KeyValuationService.evaluate_imported_key(
                user_id=user["id"],
                server=server,
                api_key="sk-imported-key-12345678901234567890",
                token_data={"id": 77, "remain_quota": 500000, "used_quota": 1250000},
            )
            assert imported_after_topup["status"] == "no_change"
            assert imported_after_topup["credited_delta_quota"] == 0
            assert await get_user_server_total_spend(user["id"], server_id) == 35000
            print("[OK] Platform topups move the key baseline forward so imports do not recapture other users' paid quota")

            await update_server(server_id, price_per_unit=12000)
            await sync_server_pricing_version(server_id)
            versions = await list_server_pricing_versions(server_id)
            assert len(versions) == 2
            print("[OK] Updating server pricing creates a new immutable pricing version")

            service_quote = await quote_non_api_product(
                {"id": general_product_id, "price_vnd": 100000, "quota_amount": 0, "dollar_amount": 0},
                user_id=user["id"],
            )
            assert service_quote.payable_amount == 90000
            assert service_quote.discount_amount == 10000
            assert (await get_primary_product_promotion(general_product_id)) is not None
            print("[OK] Non-API products use the promotion engine independently from server tiers")

            await set_discount_disabled(blocked_user["id"], 1)
            blocked_service_quote = await quote_non_api_product(
                {"id": general_product_id, "price_vnd": 100000, "quota_amount": 0, "dollar_amount": 0},
                user_id=blocked_user["id"],
            )
            assert blocked_service_quote.discount_amount == 0
            assert blocked_service_quote.payable_amount == 100000
            print("[OK] Discount-disabled users bypass non-API promotions")

            refunded_balance = await refund_order_to_wallet(
                order_id,
                reason="Verification refund",
                tx_type="refund",
                description="Verification refund",
            )
            assert refunded_balance is not None
            await SpendLedgerService.record_order_refund(order)
            assert await get_user_server_total_spend(user["id"], server_id) == 15000
            print("[OK] Refunding a completed API order appends a reversal and reduces spend summary")

            ledger_entries = await list_spend_ledger(user["id"], server_id)
            assert len(ledger_entries) == 4
            valuation_events = await list_key_valuation_events(server_id)
            assert len(valuation_events) == 6
            print("[OK] Ledger and valuation event audit trails are persisted as append-only records")

            print("\n=== DISCOUNT / LEDGER VERIFICATION PASSED ===")
        finally:
            await close_db()
            object.__setattr__(settings, "db_path", original_db_path)


asyncio.run(main())
