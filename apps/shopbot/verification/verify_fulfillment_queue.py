"""Verify durable queue claims, fencing, and conservative crash recovery."""
import asyncio
import sqlite3
import sys
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bot.config import settings
from bot.services.fulfillment_worker import run_one
from db.database import open_write_transaction
from db.financial_migration import migrate
from db.queries.fulfillment import begin_operation, claim_next, complete_key_order, complete_manual_service, complete_stock_order, confirm_operation, enqueue_paid_order, finish_claim, prepare_service_order
from db.queries.wallets import complete_wallet_topup_order
from db.queries.notification_outbox import claim_notification, finish_notification


class QueueTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.original = settings.db_path
        self.path = str(Path(self.temp.name) / "queue.sqlite")
        object.__setattr__(settings, "db_path", self.path)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE users (id INTEGER PRIMARY KEY);
                INSERT INTO users VALUES (4);
                CREATE TABLE orders (id INTEGER PRIMARY KEY, status TEXT, is_refunded INTEGER, updated_at TEXT,
                    product_type TEXT, quantity INTEGER DEFAULT 1, completed_at TEXT, api_key TEXT, api_token_id INTEGER,
                    api_token_name TEXT, quota_after INTEGER, delivery_info TEXT, delivery_token_names TEXT,
                    user_id INTEGER, server_id INTEGER, product_id INTEGER, amount INTEGER, order_code TEXT);
                CREATE TABLE wallets (user_id INTEGER PRIMARY KEY, balance INTEGER, updated_at TEXT);
                CREATE TABLE wallet_transactions (id INTEGER PRIMARY KEY, user_id INTEGER, amount INTEGER,
                    balance_after INTEGER, type TEXT, reference_id TEXT, description TEXT);
                CREATE TABLE account_stocks (id INTEGER PRIMARY KEY, product_id INTEGER, account_data TEXT, is_sold INTEGER,
                    sold_order_id INTEGER, sold_to_user INTEGER, sold_at TEXT);
                INSERT INTO orders (id,status,is_refunded,product_type,quantity) VALUES (1, 'paid', 0, 'key_new', 1);
            """)
            migrate(db)

    async def asyncTearDown(self):
        object.__setattr__(settings, "db_path", self.original)
        self.temp.cleanup()

    async def enqueue(self):
        db = await open_write_transaction()
        try:
            await enqueue_paid_order(db, 1)
            await enqueue_paid_order(db, 1)
            await db.commit()
        finally:
            await db.close()

    async def test_enqueue_rolls_back_with_payment(self):
        db = await open_write_transaction()
        try:
            await enqueue_paid_order(db, 1)
            await db.rollback()
        finally:
            await db.close()
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM fulfillment_jobs").fetchone()[0], 0)

    async def test_competing_workers_claim_once(self):
        await self.enqueue()
        claims = await asyncio.gather(claim_next("one"), claim_next("two"))
        self.assertEqual(sum(item is not None for item in claims), 1)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT status FROM orders WHERE id = 1").fetchone()[0], "processing")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM fulfillment_jobs").fetchone()[0], 1)

    async def test_expired_claim_is_review_not_replayed(self):
        await self.enqueue()
        claim = await claim_next("old")
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE fulfillment_jobs SET lease_until = datetime('now', '-1 second')")
            db.commit()
        self.assertFalse(await finish_claim(claim["id"], claim["lease_token"], succeeded=True))
        self.assertIsNone(await claim_next("new"))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT status FROM fulfillment_jobs").fetchone()[0], "needs_review")

    async def test_completion_requires_current_token_and_completed_order(self):
        await self.enqueue()
        claim = await claim_next("worker")
        self.assertFalse(await finish_claim(claim["id"], "wrong", succeeded=True))
        self.assertTrue(await finish_claim(claim["id"], claim["lease_token"], succeeded=True))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT status FROM fulfillment_jobs").fetchone()[0], "needs_review")

    async def test_completed_order_finishes_with_current_token(self):
        await self.enqueue()
        claim = await claim_next("worker")
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE orders SET status = 'completed', product_type = 'service_upgrade' WHERE id = 1")
            db.commit()
        self.assertTrue(await finish_claim(claim["id"], claim["lease_token"], succeeded=True))
        self.assertFalse(await finish_claim(claim["id"], claim["lease_token"], succeeded=True))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT status FROM fulfillment_jobs").fetchone()[0], "completed")

    async def test_key_order_without_operation_needs_review(self):
        await self.enqueue()
        claim = await claim_next("worker")
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE orders SET status = 'completed' WHERE id = 1")
            db.commit()
        self.assertTrue(await finish_claim(claim["id"], claim["lease_token"], succeeded=True))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT status FROM fulfillment_jobs").fetchone()[0], "needs_review")

    async def test_operation_send_boundary_cannot_be_replayed(self):
        await self.enqueue()
        claim = await claim_next("worker")
        self.assertIsNone(await begin_operation(claim["id"], "wrong", 0))
        with self.assertRaises(ValueError):
            await begin_operation(claim["id"], claim["lease_token"], 1)
        attempts = await asyncio.gather(*(
            begin_operation(claim["id"], claim["lease_token"], 0) for _ in range(2)
        ))
        self.assertEqual(sum(item is not None for item in attempts), 1)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT operation_key, status FROM fulfillment_operations").fetchone(),
                             ("order:1:item:0", "sending"))

    async def test_unconfirmed_operation_prevents_success(self):
        await self.enqueue()
        claim = await claim_next("worker")
        operation = await begin_operation(claim["id"], claim["lease_token"], 0)
        self.assertFalse(await confirm_operation(claim["id"], "wrong", operation, "remote-1"))
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE orders SET status = 'completed' WHERE id = 1")
            db.commit()
        self.assertTrue(await finish_claim(claim["id"], claim["lease_token"], succeeded=True))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT status FROM fulfillment_jobs").fetchone()[0], "needs_review")

    async def test_confirmed_operation_allows_completion(self):
        await self.enqueue()
        claim = await claim_next("worker")
        operation = await begin_operation(claim["id"], claim["lease_token"], 0)
        self.assertTrue(await confirm_operation(claim["id"], claim["lease_token"], operation, "remote-1"))
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE orders SET status = 'completed' WHERE id = 1")
            db.commit()
        self.assertTrue(await finish_claim(claim["id"], claim["lease_token"], succeeded=True))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT status FROM fulfillment_jobs").fetchone()[0], "completed")

    async def test_key_delivery_requires_confirmed_operation_and_valid_lease(self):
        await self.enqueue()
        claim = await claim_next("worker")
        delivery = {"api_key": "test-key", "api_token_name": "test-name"}
        self.assertFalse(await complete_key_order(claim["id"], claim["lease_token"], delivery))
        operation = await begin_operation(claim["id"], claim["lease_token"], 0, delivery=delivery)
        self.assertFalse(await complete_key_order(claim["id"], claim["lease_token"], delivery))
        self.assertTrue(await confirm_operation(claim["id"], claim["lease_token"], operation, "remote-1"))
        self.assertFalse(await complete_key_order(claim["id"], "wrong", delivery))
        self.assertFalse(await complete_key_order(claim["id"], claim["lease_token"], delivery))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT status, api_key FROM orders").fetchone(), ("processing", "test-key"))

    async def test_worker_failure_leaves_review_without_replay(self):
        await self.enqueue()
        calls = []

        async def fail(claim):
            calls.append(claim["id"])
            raise RuntimeError("untrusted external error")

        self.assertTrue(await run_one(fail, owner="worker"))
        self.assertFalse(await run_one(fail, owner="worker"))
        self.assertEqual(len(calls), 1)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT status FROM fulfillment_jobs").fetchone()[0], "needs_review")

    async def test_worker_cancellation_is_reconciled_after_lease(self):
        await self.enqueue()

        async def interrupted(claim):
            raise asyncio.CancelledError()

        with self.assertRaises(asyncio.CancelledError):
            await run_one(interrupted, owner="old")
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE fulfillment_jobs SET lease_until = datetime('now', '-1 second')")
            db.commit()
        self.assertIsNone(await claim_next("new"))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT status FROM fulfillment_jobs").fetchone()[0], "needs_review")

    async def test_stock_delivery_is_atomic_and_fenced(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE orders SET product_type='account_stocked', product_id=1, user_id=4, quantity=2")
            db.executemany("INSERT INTO account_stocks VALUES (?, 1, ?, 0, 1, NULL, NULL)", [(1, "one"), (2, "two")])
            db.commit()
        await self.enqueue()
        claim = await claim_next("worker")
        self.assertIsNone(await complete_stock_order(claim["id"], "wrong"))
        result = await complete_stock_order(claim["id"], claim["lease_token"])
        self.assertEqual(len(result), 2)
        self.assertIsNone(await complete_stock_order(claim["id"], claim["lease_token"]))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT status FROM orders WHERE id=1").fetchone()[0], "completed")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM account_stocks WHERE is_sold=1 AND sold_to_user=4").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM notification_outbox").fetchone()[0], 2)

    async def test_stock_delivery_rolls_back_when_order_write_fails(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE orders SET product_type='account_stocked', product_id=1, user_id=4")
            db.execute("INSERT INTO account_stocks VALUES (1, 1, 'one', 0, 1, NULL, NULL)")
            db.execute("""CREATE TRIGGER fail_completion BEFORE UPDATE OF status ON orders
                          WHEN NEW.status='completed' BEGIN SELECT RAISE(ABORT, 'injected'); END""")
            db.commit()
        await self.enqueue()
        claim = await claim_next("worker")
        with self.assertRaises(sqlite3.IntegrityError):
            await complete_stock_order(claim["id"], claim["lease_token"])
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT is_sold FROM account_stocks").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT status FROM orders").fetchone()[0], "processing")

    async def test_wallet_topup_requires_current_claim_and_credits_once(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE orders SET product_type='wallet_topup', user_id=4, amount=100, order_code='ORD1'")
            db.commit()
        await self.enqueue()
        claim = await claim_next("worker")
        self.assertIsNone(await complete_wallet_topup_order(1, claim={"id": claim["id"], "lease_token": "wrong"}))
        self.assertEqual(await complete_wallet_topup_order(1, claim=claim), 100)
        self.assertIsNone(await complete_wallet_topup_order(1, claim=claim))
        self.assertTrue(await finish_claim(claim["id"], claim["lease_token"], succeeded=True))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT balance FROM wallets WHERE user_id=4").fetchone()[0], 100)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM wallet_transactions").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM notification_outbox").fetchone()[0], 2)

    async def test_notification_retry_is_fenced_and_bounded(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("INSERT INTO notification_outbox(event_key,event_type,status) VALUES ('event','user_order_completed','pending')")
            db.commit()
        claims = await asyncio.gather(claim_notification(), claim_notification())
        self.assertEqual(sum(claim is not None for claim in claims), 1)
        claim = next(claim for claim in claims if claim)
        self.assertFalse(await finish_notification(claim["id"], "wrong", succeeded=True))
        self.assertTrue(await finish_notification(claim["id"], claim["lease_token"], succeeded=False))
        for _ in range(2):
            with closing(sqlite3.connect(self.path)) as db:
                db.execute("UPDATE notification_outbox SET next_attempt_at = NULL")
                db.commit()
            claim = await claim_notification()
            self.assertTrue(await finish_notification(claim["id"], claim["lease_token"], succeeded=False))
        self.assertIsNone(await claim_notification())
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT status, attempts FROM notification_outbox").fetchone(), ("failed", 3))

    async def test_wallet_credit_rolls_back_if_outbox_fails(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE orders SET product_type='wallet_topup', user_id=4, amount=100, order_code='ORD1'")
            db.execute("""CREATE TRIGGER fail_notification BEFORE INSERT ON notification_outbox
                          BEGIN SELECT RAISE(ABORT, 'injected'); END""")
            db.commit()
        await self.enqueue()
        claim = await claim_next("worker")
        with self.assertRaises(sqlite3.IntegrityError):
            await complete_wallet_topup_order(1, claim=claim)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM wallets").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM wallet_transactions").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT status FROM orders").fetchone()[0], "processing")

    async def test_service_order_notifies_but_remains_manual(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE orders SET product_type='service_upgrade', user_id=4")
            db.commit()
        await self.enqueue()
        claim = await claim_next("worker")
        self.assertFalse(await prepare_service_order(claim["id"], "wrong"))
        self.assertTrue(await prepare_service_order(claim["id"], claim["lease_token"]))
        self.assertFalse(await complete_manual_service(1))
        self.assertTrue(await finish_claim(claim["id"], claim["lease_token"], succeeded=True))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT status FROM fulfillment_jobs").fetchone()[0], "needs_review")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM notification_outbox").fetchone()[0], 2)
        self.assertTrue(await complete_manual_service(1))
        self.assertFalse(await complete_manual_service(1))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT status FROM fulfillment_jobs").fetchone()[0], "completed")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM notification_outbox").fetchone()[0], 4)


if __name__ == "__main__":
    unittest.main()
