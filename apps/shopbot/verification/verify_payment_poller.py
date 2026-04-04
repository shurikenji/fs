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
from db.queries.orders import create_order, get_order_by_id
from db.queries.transactions import get_processed_transactions
from db.queries.users import create_user
from db.queries.wallets import add_balance


class _DummyBot:
    pass


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

                print("\n=== PAYMENT POLLER VERIFICATION PASSED ===")
            finally:
                payment_poller.notify_user = original_notify_user
                payment_poller.notify_admin_order_completed = original_notify_admin_order_completed
                payment_poller.notify_admin_service_paid = original_notify_admin_service_paid
                payment_poller.fetch_transactions = original_fetch_transactions
                payment_poller._process_order = original_process_order
        finally:
            await close_db()
            object.__setattr__(settings, "db_path", original_db_path)


asyncio.run(main())
