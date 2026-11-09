"""Exercise receipt-to-delivery on a real isolated SQLite schema, with fake remote calls."""
import sqlite3
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bot.config import settings
from bot.services import notification_worker, payment_poller
from bot.services.bank_receipt_ingest import ingest_transactions
from bot.services.fulfillment_worker import process_shopbot_claim, run_one
from bot.utils.time_utils import get_now_vn
from db.bootstrap import init_db
from db.database import close_db, get_db
from db.financial_migration import migrate
from db.queries.categories import create_category
from db.queries.orders import create_order, get_order_by_id
from db.queries.fulfillment import require_financial_schema
from db.queries.products import create_product
from db.queries.servers import create_server
from db.queries.settings import set_setting
from db.queries.users import create_user
from db.queries.wallets import add_balance, get_balance


class FulfillmentEndToEndTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.original = settings.db_path
        self.original_verified_account = settings.mb_verified_account_no
        self.original_verified_timezone = settings.mb_verified_feed_timezone
        await close_db()
        object.__setattr__(settings, "db_path", str(Path(self.temp.name) / "test.sqlite"))
        await init_db()
        await close_db()
        db = sqlite3.connect(settings.db_path)
        try:
            migrate(db)
        finally:
            db.close()
        user = await create_user(telegram_id=90003, username="test", full_name="Test")
        self.user_id = user["id"]
        category_id = await create_category("Keys", cat_type="key_api")
        server_id = await create_server(name="Test", base_url="https://example.test", user_id_header="42",
                                        access_token="test", price_per_unit=1000, quota_per_unit=500000)
        product_id = await create_product(category_id=category_id, server_id=server_id, name="Test key",
                                          price_vnd=1000, product_type="key_new", quota_amount=500000)
        self.server_id = server_id
        self.product_id = product_id
        self.order_id = await create_order(order_code="ORDABCD0001", user_id=self.user_id, product_type="key_new",
                                           amount=1000, payment_method="qr", product_id=product_id,
                                           server_id=server_id, expired_at=(get_now_vn() + timedelta(hours=1)).isoformat())

    async def asyncTearDown(self):
        await close_db()
        object.__setattr__(settings, "db_path", self.original)
        object.__setattr__(settings, "mb_verified_account_no", self.original_verified_account)
        object.__setattr__(settings, "mb_verified_feed_timezone", self.original_verified_timezone)
        self.temp.cleanup()

    async def test_paid_receipt_creates_and_notifies_once(self):
        feed = [{"transactionID": "tx1", "amount": 1000, "description": "ORDABCD0001",
                 "transactionDate": get_now_vn().strftime("%d/%m/%Y %H:%M:%S")}]
        self.assertEqual(await ingest_transactions(feed, account_identity="test-account", account_verified=True), {"matched": 1})
        with patch.object(payment_poller, "get_api_client"), \
             patch.object(payment_poller, "_create_key_with_retry", AsyncMock(return_value=("sk-test-full-key", 12))) as create:
            self.assertTrue(await run_one(lambda claim: process_shopbot_claim(None, claim), owner="worker"))
        create.assert_awaited_once()
        order = await get_order_by_id(self.order_id)
        self.assertEqual((order["status"], order["api_key"]), ("completed", "sk-test-full-key"))
        db = await get_db()
        cursor = await db.execute("SELECT status FROM fulfillment_jobs WHERE order_id = ?", (self.order_id,))
        self.assertEqual((await cursor.fetchone())[0], "completed")
        cursor = await db.execute("SELECT COUNT(*) FROM spend_ledger WHERE source_type = 'order_completion'")
        self.assertEqual((await cursor.fetchone())[0], 1)
        with patch.object(notification_worker, "notify_user", AsyncMock(return_value=True)) as user_send, \
             patch.object(notification_worker, "notify_admin_order_completed", AsyncMock(return_value=(1, 0, 0))) as admin_send:
            self.assertTrue(await notification_worker.run_one_notification(None))
            self.assertTrue(await notification_worker.run_one_notification(None))
            self.assertFalse(await notification_worker.run_one_notification(None))
        user_send.assert_awaited_once()
        admin_send.assert_awaited_once()
        cursor = await db.execute("SELECT COUNT(*) FROM notification_outbox WHERE status = 'sent'")
        self.assertEqual((await cursor.fetchone())[0], 2)

    async def test_multiple_key_tokens_with_missing_first_identity(self):
        db = await get_db()
        await db.execute("UPDATE orders SET quantity = 2 WHERE id = ?", (self.order_id,))
        await db.commit()
        feed = [{"transactionID": "tx-multi", "amount": 1000, "description": "ORDABCD0001",
                 "transactionDate": get_now_vn().strftime("%d/%m/%Y %H:%M:%S")}]
        self.assertEqual(await ingest_transactions(feed, account_identity="test-account", account_verified=True), {"matched": 1})
        with patch.object(payment_poller, "get_api_client"), \
             patch.object(payment_poller, "_create_key_with_retry", AsyncMock(side_effect=[("sk-first", None), ("sk-second", 12)])):
            self.assertTrue(await run_one(lambda claim: process_shopbot_claim(None, claim), owner="worker"))
        order = await get_order_by_id(self.order_id)
        self.assertEqual((order["status"], order["api_key"], order["api_token_id"], order["delivery_info"]),
                         ("completed", "sk-first", None, "sk-first\nsk-second"))

    async def test_failure_after_remote_create_requires_review(self):
        feed = [{"transactionID": "tx1", "amount": 1000, "description": "ORDABCD0001",
                 "transactionDate": get_now_vn().strftime("%d/%m/%Y %H:%M:%S")}]
        self.assertEqual(await ingest_transactions(feed, account_identity="test-account", account_verified=True), {"matched": 1})
        db = await get_db()
        await db.execute("""CREATE TRIGGER fail_key_baseline BEFORE INSERT ON api_key_valuation_events
                            BEGIN SELECT RAISE(ABORT, 'injected failure'); END""")
        await db.commit()
        with patch.object(payment_poller, "get_api_client"), \
             patch.object(payment_poller, "_create_key_with_retry", AsyncMock(return_value=("sk-test-full-key", 12))) as create:
            self.assertTrue(await run_one(lambda claim: process_shopbot_claim(None, claim), owner="worker"))
            self.assertFalse(await run_one(lambda claim: process_shopbot_claim(None, claim), owner="worker"))
        create.assert_awaited_once()
        order = await get_order_by_id(self.order_id)
        self.assertEqual(order["status"], "processing")
        cursor = await db.execute("SELECT status FROM fulfillment_jobs WHERE order_id = ?", (self.order_id,))
        self.assertEqual((await cursor.fetchone())[0], "needs_review")
        cursor = await db.execute("SELECT status FROM fulfillment_operations")
        self.assertEqual((await cursor.fetchone())[0], "sending")
        for table in ("user_keys", "api_key_registry", "api_key_valuation_events"):
            cursor = await db.execute(f"SELECT COUNT(*) FROM {table}")
            self.assertEqual((await cursor.fetchone())[0], 0)
        cursor = await db.execute("SELECT COUNT(*) FROM wallet_transactions WHERE type = 'refund'")
        self.assertEqual((await cursor.fetchone())[0], 0)

    async def test_wallet_payment_queues_and_worker_delivers(self):
        await add_balance(self.user_id, 2000, "seed")
        order_id = await create_order(order_code="ORDABCD0002", user_id=self.user_id, product_type="key_new",
                                      amount=1000, payment_method="wallet", product_id=self.product_id,
                                      server_id=self.server_id)
        self.assertTrue(await payment_poller.process_wallet_payment(None, order_id))
        self.assertEqual(await get_balance(self.user_id), 1000)
        with patch.object(payment_poller, "get_api_client"), \
             patch.object(payment_poller, "_create_key_with_retry", AsyncMock(return_value=("sk-test-full-key", 12))) as create:
            self.assertTrue(await run_one(lambda claim: process_shopbot_claim(None, claim), owner="worker"))
        create.assert_awaited_once()
        self.assertEqual((await get_order_by_id(order_id))["status"], "completed")

    async def test_wallet_debit_rolls_back_if_job_insert_fails(self):
        await add_balance(self.user_id, 2000, "seed")
        order_id = await create_order(order_code="ORDABCD0002", user_id=self.user_id, product_type="key_new",
                                      amount=1000, payment_method="wallet", product_id=self.product_id,
                                      server_id=self.server_id)
        db = await get_db()
        await db.execute("""CREATE TRIGGER fail_job BEFORE INSERT ON fulfillment_jobs
                            BEGIN SELECT RAISE(ABORT, 'injected'); END""")
        await db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            await payment_poller.process_wallet_payment(None, order_id)
        self.assertEqual(await get_balance(self.user_id), 2000)
        self.assertEqual((await get_order_by_id(order_id))["status"], "pending")

    async def test_incomplete_financial_schema_fails_startup_check(self):
        await require_financial_schema()
        db = await get_db()
        await db.execute("DROP TABLE worker_status")
        await db.commit()
        with self.assertRaisesRegex(RuntimeError, "schema is incomplete"):
            await require_financial_schema()

    async def test_poller_receipt_flows_through_worker(self):
        await set_setting("mb_account_no", "123456789")
        object.__setattr__(settings, "mb_verified_account_no", "123456789")
        object.__setattr__(settings, "mb_verified_feed_timezone", "Asia/Ho_Chi_Minh")
        feed = [{"transactionID": "tx1", "amount": 1000, "description": "ORDABCD0001",
                 "transactionDate": get_now_vn().strftime("%d/%m/%Y %H:%M:%S")}]
        with patch.object(payment_poller, "fetch_transactions", AsyncMock(return_value=feed)):
            self.assertTrue(await payment_poller._poll_cycle(None, from_days=7))
        self.assertEqual((await get_order_by_id(self.order_id))["status"], "paid")
        with patch.object(payment_poller, "get_api_client"), \
             patch.object(payment_poller, "_create_key_with_retry", AsyncMock(return_value=("sk-test-full-key", 12))) as create:
            self.assertTrue(await run_one(lambda claim: process_shopbot_claim(None, claim), owner="worker"))
        create.assert_awaited_once()
        self.assertEqual((await get_order_by_id(self.order_id))["status"], "completed")


if __name__ == "__main__":
    unittest.main()
