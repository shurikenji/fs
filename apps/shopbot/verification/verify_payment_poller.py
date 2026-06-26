"""Verification for payment poller transaction, expiry, and wallet paths."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from bot.config import settings
from db.database import close_db, get_db
from db.models import init_db
from db.queries.api_key_alerts import get_api_key_alert_state, upsert_api_key_alert_state
from db.queries.categories import create_category
from db.queries.orders import create_order, get_order_by_id
from db.queries.products import create_product
from db.queries.servers import create_server
from db.queries.transactions import get_processed_transactions
from db.queries.user_keys import get_user_keys
from db.queries.users import create_user
from db.queries.wallets import add_balance


class _DummyBot:
    pass


class _FakeKeyTopupClient:
    def __init__(self, *, current_quota: int, token_id: int = 7701) -> None:
        self.current_quota = current_quota
        self.token_id = token_id
        self.updated_to: int | None = None

    async def search_token(self, server: dict, api_key: str) -> dict:
        _ = server, api_key
        return {"id": self.token_id, "remain_quota": self.current_quota}

    async def update_token(
        self,
        *,
        server: dict,
        token_id: int,
        new_quota: int,
        current_data: dict,
    ) -> bool:
        _ = server, token_id, current_data
        self.updated_to = new_quota
        return True


async def _set_order_created_at(order_id: int, created_at: str) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE orders SET created_at = ?, updated_at = ? WHERE id = ?",
        (created_at, created_at, order_id),
    )
    await db.commit()


async def main() -> None:
    original_db_path = settings.db_path

    with TemporaryDirectory() as temp_dir:
        temp_db = Path(temp_dir) / "payment-poller.db"
        await close_db()
        object.__setattr__(settings, "db_path", str(temp_db))

        try:
            await init_db()

            from bot.services import payment_poller

            user = await create_user(
                telegram_id=30001,
                username="poller-phase",
                full_name="Poller Phase Verify",
            )

            notifications: list[tuple[str, int | None, str]] = []
            processed_orders: list[str] = []

            async def _fake_notify_user(user_id: int, text: str, bot=None) -> None:
                _ = bot
                notifications.append(("user", user_id, text))

            async def _fake_notify_admin_order_completed(order: dict, *, bot=None) -> tuple[int, int, int]:
                _ = bot
                notifications.append(("admin_completed", None, order["order_code"]))
                return (1, 0, 0)

            async def _fake_notify_admin_service_paid(order: dict, *, bot=None) -> tuple[int, int, int]:
                _ = bot
                notifications.append(("admin_service_paid", None, order["order_code"]))
                return (1, 0, 0)

            async def _fake_process_order(bot, order: dict) -> None:
                _ = bot
                processed_orders.append(order["order_code"])
                await payment_poller.update_order_status(order["id"], "processing")

            original_notify_user = payment_poller.notify_user
            original_notify_admin_order_completed = payment_poller.notify_admin_order_completed
            original_notify_admin_service_paid = payment_poller.notify_admin_service_paid
            original_fetch_transactions = payment_poller.fetch_transactions
            original_get_api_client = payment_poller.get_api_client
            original_process_order = payment_poller._process_order

            payment_poller.notify_user = _fake_notify_user
            payment_poller.notify_admin_order_completed = _fake_notify_admin_order_completed
            payment_poller.notify_admin_service_paid = _fake_notify_admin_service_paid
            payment_poller._process_order = _fake_process_order

            try:
                matched_order_id = await create_order(
                    order_code="ORDABCD0001",
                    user_id=user["id"],
                    product_type="wallet_topup",
                    amount=70_000,
                    payment_method="qr",
                    product_name="Wallet topup",
                )
                mismatch_order_id = await create_order(
                    order_code="ORDABCD0002",
                    user_id=user["id"],
                    product_type="wallet_topup",
                    amount=50_000,
                    payment_method="qr",
                    product_name="Wallet topup mismatch",
                )
                expired_order_id = await create_order(
                    order_code="ORDABCD0003",
                    user_id=user["id"],
                    product_type="wallet_topup",
                    amount=40_000,
                    payment_method="qr",
                    product_name="Wallet topup expired",
                )

                await _set_order_created_at(expired_order_id, "2000-01-01T00:00:00")

                async def _fake_fetch_transactions() -> list[dict]:
                    return [
                        {
                            "transactionID": "TXMATCH001",
                            "amount": 70_000,
                            "description": "Thanh toan ORDABCD0001",
                            "transactionDate": "2026-03-19T10:00:00",
                        },
                        {
                            "transactionID": "TXMIS001",
                            "amount": 99_999,
                            "description": "Thanh toan ORDABCD0002",
                            "transactionDate": "2026-03-19T10:01:00",
                        },
                    ]

                payment_poller.fetch_transactions = _fake_fetch_transactions

                await payment_poller._poll_cycle(_DummyBot())

                matched_order = await get_order_by_id(matched_order_id)
                mismatch_order = await get_order_by_id(mismatch_order_id)
                expired_order = await get_order_by_id(expired_order_id)
                processed_ids = {row["transaction_id"] for row in await get_processed_transactions(limit=10)}

                assert matched_order is not None and matched_order["status"] == "processing"
                assert mismatch_order is not None and mismatch_order["status"] == "pending"
                assert expired_order is not None and expired_order["status"] == "expired"
                assert "ORDABCD0001" in processed_orders
                assert "TXMATCH001" in processed_ids
                assert "TXMIS001" not in processed_ids
                assert any("ORDABCD0003" in text for kind, _, text in notifications if kind == "user")
                print("[OK] _poll_cycle matches valid QR transactions, leaves mismatches pending, and expires old orders")

                wallet_order_id = await create_order(
                    order_code="ORDABCD0004",
                    user_id=user["id"],
                    product_type="wallet_topup",
                    amount=60_000,
                    payment_method="wallet",
                    product_name="Wallet payment",
                )
                wallet_fail = await payment_poller.process_wallet_payment(_DummyBot(), wallet_order_id)
                wallet_pending = await get_order_by_id(wallet_order_id)
                assert wallet_fail is False
                assert wallet_pending is not None and wallet_pending["status"] == "pending"
                assert any("Số dư không đủ" in text for kind, _, text in notifications if kind == "user")
                print("[OK] process_wallet_payment keeps pending orders untouched and notifies on insufficient balance")

                await add_balance(user["id"], 120_000, "seed", description="Seed balance for poller verify")
                wallet_success = await payment_poller.process_wallet_payment(_DummyBot(), wallet_order_id)
                wallet_paid = await get_order_by_id(wallet_order_id)
                assert wallet_success is True
                assert wallet_paid is not None and wallet_paid["status"] == "processing"
                assert "ORDABCD0004" in processed_orders
                print("[OK] process_wallet_payment charges the wallet and routes successful orders through _process_order")

                category_id = await create_category("Keys", sort_order=1)
                server_id = await create_server(
                    name="Alert Reset Server",
                    base_url="https://example.com",
                    user_id_header="new-api-user",
                    access_token="secret",
                    price_per_unit=30_000,
                    quota_per_unit=5_000_000,
                    quota_multiple=1.0,
                )
                product_id = await create_product(
                    category_id=category_id,
                    server_id=server_id,
                    name="Topup $10",
                    price_vnd=30_000,
                    product_type="key_topup",
                    quota_amount=5_000_000,
                    dollar_amount=10.0,
                )
                topup_key = "sk-reset-alert-after-topup-1234567890"
                topup_order_id = await create_order(
                    order_code="ORDABCD0005",
                    user_id=user["id"],
                    product_type="key_topup",
                    amount=30_000,
                    payment_method="wallet",
                    product_id=product_id,
                    product_name="Topup $10",
                    server_id=server_id,
                    existing_key=topup_key,
                )
                topup_order = await get_order_by_id(topup_order_id)
                assert topup_order is not None

                import bot.services.key_alert_poller as key_alert_poller

                await upsert_api_key_alert_state(
                    user_id=user["id"],
                    server_id=server_id,
                    api_key_hash=key_alert_poller.hash_api_key(topup_key),
                    masked_key="sk-reset********7890",
                    last_seen_remain_quota=450_000,
                    last_seen_balance_dollar=0.9,
                    last_alert_threshold=1.0,
                    last_alert_sent_at="2026-01-01 00:00:00",
                )

                topup_client = _FakeKeyTopupClient(current_quota=500_000)
                payment_poller.get_api_client = lambda server: topup_client
                await payment_poller._process_key_topup(_DummyBot(), topup_order)

                completed_topup = await get_order_by_id(topup_order_id)
                assert completed_topup is not None and completed_topup["status"] == "completed"
                assert topup_client.updated_to == 5_500_000

                recovered_state = await get_api_key_alert_state(
                    user_id=user["id"],
                    server_id=server_id,
                    api_key_hash=key_alert_poller.hash_api_key(topup_key),
                )
                assert recovered_state is not None
                assert int(recovered_state["last_seen_remain_quota"]) == 5_500_000
                assert float(recovered_state["last_seen_balance_dollar"]) == 11.0
                assert recovered_state["last_alert_threshold"] is None

                alert_notifications: list[str] = []

                async def _fake_alert_notify_user(user_id: int, text: str, *, bot=None) -> bool:
                    _ = user_id, bot
                    alert_notifications.append(text)
                    return True

                original_key_alert_get_api_client = key_alert_poller.get_api_client
                original_key_alert_notify_user = key_alert_poller.notify_user
                key_alert_poller.get_api_client = lambda server: _FakeKeyTopupClient(current_quota=450_000)
                key_alert_poller.notify_user = _fake_alert_notify_user
                try:
                    user_key_rows = await get_user_keys(user["id"], server_id=server_id)
                    assert user_key_rows
                    await key_alert_poller._check_user_key(
                        object(),
                        user_key=user_key_rows[0],
                        server={
                            "id": server_id,
                            "name": "Alert Reset Server",
                            "base_url": "https://example.com",
                            "user_id_header": "new-api-user",
                            "access_token": "secret",
                            "quota_multiple": 1.0,
                        },
                        thresholds=(100.0, 50.0, 10.0, 1.0),
                    )
                    assert len(alert_notifications) == 1
                    assert "$0.90" in alert_notifications[0]
                    assert "$1.00" in alert_notifications[0]
                finally:
                    key_alert_poller.get_api_client = original_key_alert_get_api_client
                    key_alert_poller.notify_user = original_key_alert_notify_user
                print("[OK] key topup completion resets alert baseline so fast re-drains alert again")

                print("\n=== PAYMENT POLLER VERIFICATION PASSED ===")
            finally:
                payment_poller.notify_user = original_notify_user
                payment_poller.notify_admin_order_completed = original_notify_admin_order_completed
                payment_poller.notify_admin_service_paid = original_notify_admin_service_paid
                payment_poller.fetch_transactions = original_fetch_transactions
                payment_poller.get_api_client = original_get_api_client
                payment_poller._process_order = original_process_order
        finally:
            await close_db()
            object.__setattr__(settings, "db_path", original_db_path)


asyncio.run(main())
