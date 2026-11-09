"""Exercise stock reservation concurrency on an isolated database."""
import asyncio
import sqlite3
import sys
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bot.config import settings
from db import database
from db.financial_migration import migrate
from db.queries.account_stocks import reserve_accounts
from db.queries.orders import cancel_order, expire_order
from db.queries.payment_receipts import match_receipt, record_receipt


class StockReservationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.old_path = settings.db_path
        self.path = str(Path(self.temp.name) / "stock.db")
        object.__setattr__(settings, "db_path", self.path)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL DEFAULT 1, status TEXT, product_id INTEGER, product_type TEXT, quantity INTEGER,
                    expired_at TEXT, updated_at TEXT, paid_at TEXT, mb_transaction_id TEXT, payment_method TEXT DEFAULT 'qr',
                    order_code TEXT, amount INTEGER, is_refunded INTEGER DEFAULT 0, created_at TEXT DEFAULT '2000-01-01 00:00:00');
                CREATE TABLE account_stocks (id INTEGER PRIMARY KEY, product_id INTEGER, is_sold INTEGER DEFAULT 0, sold_order_id INTEGER);
                CREATE TABLE processed_transactions (transaction_id TEXT UNIQUE, order_code TEXT, amount INTEGER);
                CREATE TABLE wallet_transactions (id INTEGER PRIMARY KEY);
                CREATE TABLE users (id INTEGER PRIMARY KEY);
                INSERT INTO users (id) VALUES (1);
                INSERT INTO orders (id, status, product_id, product_type, quantity) VALUES
                    (1, 'pending', 1, 'account_stocked', 2), (2, 'pending', 1, 'account_stocked', 2);
                UPDATE orders SET amount = 100, order_code = 'ORD' || id;
                INSERT INTO account_stocks VALUES (1, 1, 0, NULL), (2, 1, 0, NULL), (3, 1, 0, NULL);
            """)
            migrate(db)

    async def asyncTearDown(self):
        object.__setattr__(settings, "db_path", self.old_path)
        self.temp.cleanup()

    async def test_competing_orders_do_not_reserve_partial_stock(self):
        first, second = await asyncio.gather(reserve_accounts(1, 1, 2), reserve_accounts(1, 2, 2))
        self.assertEqual(sorted([len(first), len(second)]), [0, 2])
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM account_stocks WHERE sold_order_id IS NOT NULL").fetchone()[0], 2)

    async def test_retry_returns_same_accounts(self):
        first, second = await asyncio.gather(reserve_accounts(1, 1, 2), reserve_accounts(1, 1, 2))
        self.assertEqual([row['id'] for row in first], [row['id'] for row in second])
        self.assertEqual(len(first), 2)

    async def test_wrong_order_or_short_stock_leaves_no_reservation(self):
        self.assertEqual(await reserve_accounts(1, 1, 3), [])
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE orders SET status = 'cancelled' WHERE id = 1")
            db.execute("UPDATE orders SET quantity = 4 WHERE id = 2")
            db.commit()
        self.assertEqual(await reserve_accounts(1, 1, 2), [])
        self.assertEqual(await reserve_accounts(1, 2, 4), [])
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM account_stocks WHERE sold_order_id IS NOT NULL").fetchone()[0], 0)

    async def test_connection_is_closed_when_configuration_fails(self):
        connection = SimpleNamespace(close=AsyncMock())
        with patch.object(database.aiosqlite, "connect", AsyncMock(return_value=connection)), \
             patch.object(database, "_configure_connection", AsyncMock(side_effect=sqlite3.OperationalError("locked"))):
            with self.assertRaises(sqlite3.OperationalError):
                await database._open_connection()
        connection.close.assert_awaited_once()

    async def test_payment_and_expiry_cannot_both_win(self):
        self.assertEqual(len(await reserve_accounts(1, 1, 2)), 2)
        _, receipt = await record_receipt(provider="MB", account_identity="one", transaction_id="bank-tx", amount=100,
                                          order_code="ORD1", transaction_time="01/01/2001 00:00:00")
        result, expired = await asyncio.gather(match_receipt(receipt, account_verified=True), expire_order(1))
        paid = result == "matched"
        self.assertNotEqual(paid, expired)
        with closing(sqlite3.connect(self.path)) as db:
            status = db.execute("SELECT status FROM orders WHERE id = 1").fetchone()[0]
            reserved = db.execute("SELECT COUNT(*) FROM account_stocks WHERE sold_order_id = 1").fetchone()[0]
        self.assertEqual((status, reserved), ("paid", 2) if paid else ("expired", 0))

    async def test_cancel_releases_only_pending_order(self):
        self.assertEqual(len(await reserve_accounts(1, 1, 2)), 2)
        self.assertTrue(await cancel_order(1))
        self.assertFalse(await cancel_order(1))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM account_stocks WHERE sold_order_id = 1").fetchone()[0], 0)

    async def test_bank_transaction_cannot_pay_two_orders(self):
        receipts = [
            (await record_receipt(provider="MB", account_identity=account, transaction_id="duplicate", amount=100,
                                  order_code=code, transaction_time="01/01/2001 00:00:00"))[1]
            for account, code in (("one", "ORD1"), ("two", "ORD2"))
        ]
        paid = await asyncio.gather(*(match_receipt(receipt, account_verified=True) for receipt in receipts))
        self.assertEqual(paid.count("matched"), 1)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM orders WHERE status = 'paid'").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM processed_transactions").fetchone()[0], 1)

    async def test_invalid_bank_amount_and_identity_do_not_mark_paid(self):
        with self.assertRaises(ValueError):
            await record_receipt(provider="MB", account_identity="one", transaction_id="", amount=100)
        with self.assertRaises(ValueError):
            await record_receipt(provider="MB", account_identity="one", transaction_id="bank-tx", amount=-1)
        _, receipt = await record_receipt(provider="MB", account_identity="one", transaction_id="bank-tx", amount=99, order_code="ORD1")
        self.assertEqual(await match_receipt(receipt, account_verified=True), "needs_review")
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT status FROM orders WHERE id = 1").fetchone()[0], "pending")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM processed_transactions").fetchone()[0], 0)

    async def test_reservation_failure_rolls_back_entire_batch(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("""CREATE TRIGGER fail_second BEFORE UPDATE OF sold_order_id ON account_stocks
                          WHEN NEW.id = 2 BEGIN SELECT RAISE(ABORT, 'injected failure'); END""")
            db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            await reserve_accounts(1, 1, 2)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM account_stocks WHERE sold_order_id IS NOT NULL").fetchone()[0], 0)

    async def test_release_failure_keeps_order_pending_and_stock_reserved(self):
        self.assertEqual(len(await reserve_accounts(1, 1, 2)), 2)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("""CREATE TRIGGER fail_release BEFORE UPDATE OF sold_order_id ON account_stocks
                          WHEN NEW.sold_order_id IS NULL BEGIN SELECT RAISE(ABORT, 'injected failure'); END""")
            db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            await expire_order(1)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT status FROM orders WHERE id = 1").fetchone()[0], "pending")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM account_stocks WHERE sold_order_id = 1").fetchone()[0], 2)

    async def test_receipt_write_failure_rolls_back_paid_transition(self):
        _, receipt = await record_receipt(provider="MB", account_identity="one", transaction_id="bank-tx", amount=100,
                                          order_code="ORD1", transaction_time="01/01/2001 00:00:00")
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("""CREATE TRIGGER fail_receipt BEFORE INSERT ON processed_transactions
                          BEGIN SELECT RAISE(ABORT, 'injected failure'); END""")
            db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            await match_receipt(receipt, account_verified=True)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT status FROM orders WHERE id = 1").fetchone()[0], "pending")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM processed_transactions").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
