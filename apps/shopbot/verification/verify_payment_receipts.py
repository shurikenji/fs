"""Verify deduplication and conflict detection for bank receipts."""
import asyncio
import sqlite3
import sys
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bot.config import settings
from bot.services.bank_receipt_ingest import ingest_transactions, reconcile_unmatched_receipts
from db.database import close_db
from db.financial_migration import migrate
from db.queries.payment_receipts import match_receipt, record_receipt


class ReceiptTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.original = settings.db_path
        self.path = str(Path(self.temp.name) / "receipts.sqlite")
        object.__setattr__(settings, "db_path", self.path)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE users (id INTEGER PRIMARY KEY);
                CREATE TABLE orders (id INTEGER PRIMARY KEY, order_code TEXT UNIQUE, status TEXT,
                    payment_method TEXT, amount INTEGER, is_refunded INTEGER DEFAULT 0,
                    paid_at TEXT, mb_transaction_id TEXT, updated_at TEXT,
                    created_at TEXT DEFAULT '2000-01-01 00:00:00', expired_at TEXT, user_id INTEGER);
                CREATE TABLE processed_transactions (transaction_id TEXT UNIQUE, order_code TEXT, amount INTEGER);
                CREATE TABLE wallet_transactions (id INTEGER PRIMARY KEY);
                INSERT INTO orders (id, order_code, status, payment_method, amount) VALUES
                    (1, 'ORD1', 'pending', 'qr', 100), (2, 'ORD2', 'expired', 'qr', 100);
            """)
            migrate(db)

    async def asyncTearDown(self):
        await close_db()
        object.__setattr__(settings, "db_path", self.original)
        self.temp.cleanup()

    async def test_concurrent_duplicates_record_only_once(self):
        args = dict(provider="MB", account_identity="account", transaction_id="tx1", amount=100)
        results = await asyncio.gather(*(record_receipt(**args) for _ in range(5)))
        self.assertEqual(sorted(result[0] for result in results), ["duplicate"] * 4 + ["inserted"])
        self.assertEqual(len({result[1] for result in results}), 1)

    async def test_conflicting_duplicate_is_held_for_review(self):
        args = dict(provider="MB", account_identity="account", transaction_id="tx1", amount=100, order_code="ORD1")
        await record_receipt(**args)
        args["amount"] = 200
        status, receipt_id = await record_receipt(**args)
        self.assertEqual(status, "conflict")
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT amount, status FROM payment_receipts WHERE id = ?", (receipt_id,)).fetchone(), (100, "needs_review"))

    async def test_invalid_receipts_are_not_saved(self):
        args = dict(provider="MB", account_identity="account", transaction_id="tx1", amount=0)
        with self.assertRaises(ValueError):
            await record_receipt(**args)
        args.update(amount=100, transaction_id="   ")
        with self.assertRaises(ValueError):
            await record_receipt(**args)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM payment_receipts").fetchone()[0], 0)

    async def test_match_is_atomic_and_idempotent(self):
        _, receipt_id = await record_receipt(provider="MB", account_identity="account", transaction_id="tx1", amount=100, order_code="ORD1", transaction_time="01/01/2001 12:00:00")
        statuses = await asyncio.gather(match_receipt(receipt_id, account_verified=True), match_receipt(receipt_id, account_verified=True))
        self.assertEqual(statuses, ["matched", "matched"])
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT status FROM orders WHERE id = 1").fetchone()[0], "paid")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM processed_transactions").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM fulfillment_jobs WHERE order_id = 1").fetchone()[0], 1)

    async def test_late_and_wrong_amount_are_kept_for_review(self):
        _, late_id = await record_receipt(provider="MB", account_identity="account", transaction_id="late", amount=100, order_code="ORD2")
        _, wrong_id = await record_receipt(provider="MB", account_identity="account", transaction_id="wrong", amount=99, order_code="ORD1")
        self.assertEqual(await match_receipt(late_id, account_verified=True), "late")
        self.assertEqual(await match_receipt(wrong_id, account_verified=True), "needs_review")
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT status FROM orders WHERE id = 1").fetchone()[0], "pending")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM fulfillment_jobs").fetchone()[0], 0)

    async def test_job_failure_rolls_back_receipt_match(self):
        _, receipt_id = await record_receipt(provider="MB", account_identity="account", transaction_id="tx1", amount=100, order_code="ORD1", transaction_time="01/01/2001 12:00:00")
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("""CREATE TRIGGER fail_job BEFORE INSERT ON fulfillment_jobs
                          BEGIN SELECT RAISE(ABORT, 'injected failure'); END""")
            db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            await match_receipt(receipt_id, account_verified=True)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT status FROM orders WHERE id = 1").fetchone()[0], "pending")
            self.assertEqual(db.execute("SELECT status FROM payment_receipts WHERE id = ?", (receipt_id,)).fetchone()[0], "unmatched")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM processed_transactions").fetchone()[0], 0)

    async def test_conflict_stops_pending_fulfillment(self):
        args = dict(provider="MB", account_identity="account", transaction_id="tx1", amount=100, order_code="ORD1", transaction_time="01/01/2001 12:00:00")
        _, receipt_id = await record_receipt(**args)
        self.assertEqual(await match_receipt(receipt_id, account_verified=True), "matched")
        args["amount"] = 200
        self.assertEqual((await record_receipt(**args))[0], "conflict")
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT status FROM fulfillment_jobs").fetchone()[0], "needs_review")

    async def test_duplicate_can_fill_missing_order_code(self):
        args = dict(provider="MB", account_identity="account", transaction_id="tx1", amount=100, transaction_time="01/01/2001 12:00:00")
        _, receipt_id = await record_receipt(**args)
        self.assertEqual(await match_receipt(receipt_id, account_verified=True), "unmatched")
        args["order_code"] = "ORD1"
        self.assertEqual((await record_receipt(**args))[0], "duplicate")
        self.assertEqual(await match_receipt(receipt_id, account_verified=True), "matched")

    async def test_feed_saves_unmatched_and_invalid_entries(self):
        result = await ingest_transactions([
            {"transactionID": "unmatched", "amount": 500, "description": "transfer", "transactionDate": "today"},
            {"transactionID": "no-description", "amount": 100, "description": None, "transactionDate": None},
            {"transactionID": "bad", "amount": 0, "description": "transfer"},
        ], account_identity="account")
        self.assertEqual(result, {"identity_unverified": 2, "invalid": 1})
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM payment_receipts WHERE status = 'unmatched'").fetchone()[0], 2)

    async def test_feed_matches_valid_order_and_enqueues_once(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE orders SET order_code = 'ORDABCD0001' WHERE id = 1")
            db.commit()
        feed = [{"transactionID": "tx1", "amount": 100,
                 "description": "payment ORDABCD0001", "transactionDate": "01/01/2001 12:00:00"}]
        self.assertEqual(await ingest_transactions(feed, account_identity="account", account_verified=True), {"matched": 1})
        self.assertEqual(await ingest_transactions(feed, account_identity="account", account_verified=True), {"matched": 1})
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM fulfillment_jobs").fetchone()[0], 1)

    async def test_unverified_account_never_marks_order_paid(self):
        _, receipt_id = await record_receipt(provider="MB", account_identity="account", transaction_id="tx1", amount=100, order_code="ORD1")
        self.assertEqual(await match_receipt(receipt_id), "identity_unverified")
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT status FROM orders WHERE id = 1").fetchone()[0], "pending")
            self.assertEqual(db.execute("SELECT status FROM payment_receipts WHERE id = ?", (receipt_id,)).fetchone()[0], "unmatched")

    async def test_unknown_and_out_of_window_times_require_review(self):
        for txid, timestamp, expected in [
            ("missing", None, "needs_review"),
            ("old", "01/01/1999 12:00:00", "needs_review"),
        ]:
            _, receipt_id = await record_receipt(provider="MB", account_identity="account", transaction_id=txid,
                                                  amount=100, order_code="ORD1", transaction_time=timestamp)
            self.assertEqual(await match_receipt(receipt_id, account_verified=True), expected)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE orders SET expired_at = '2000-02-01 00:00:00' WHERE id = 1")
            db.commit()
        _, receipt_id = await record_receipt(provider="MB", account_identity="account", transaction_id="after",
                                              amount=100, order_code="ORD1", transaction_time="01/01/2001 12:00:00")
        self.assertEqual(await match_receipt(receipt_id, account_verified=True), "late")

    async def test_multiple_order_codes_cannot_be_automatically_matched(self):
        feed = [{"transactionID": "tx1", "amount": 100,
                 "description": "ORDABCD0001 ORDABCD0002", "transactionDate": "01/01/2001 12:00:00"}]
        self.assertEqual(await ingest_transactions(feed, account_identity="account", account_verified=True), {"unmatched": 1})
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT order_code FROM payment_receipts").fetchone()[0], None)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM fulfillment_jobs").fetchone()[0], 0)

    async def test_unverified_receipt_can_be_reconciled_after_verification(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE orders SET order_code = 'ORDABCD0001' WHERE id = 1")
            db.commit()
        feed = [{"transactionID": "tx1", "amount": 100, "description": "ORDABCD0001",
                 "transactionDate": "01/01/2001 12:00:00"}]
        self.assertEqual(await ingest_transactions(feed, account_identity="account"), {"identity_unverified": 1})
        self.assertEqual(await reconcile_unmatched_receipts(account_identity="account"), 1)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT status FROM payment_receipts").fetchone()[0], "matched")


if __name__ == "__main__":
    unittest.main()
