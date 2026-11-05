"""Exercise wallet transactions against an isolated SQLite database."""
import asyncio
import os
import sqlite3
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.config import settings
from db.bootstrap import init_db
from db.database import close_db, get_db
from db.financial_migration import migrate
from db.queries.fulfillment import claim_next
from db.queries.account_stocks import add_account, reserve_accounts
from db.queries.categories import create_category
from db.queries.products import create_product
from db.queries.users import create_user
from db.queries.wallets import (
    add_balance,
    charge_pending_order_from_wallet,
    complete_wallet_topup_order,
    deduct_balance,
    get_balance,
    refund_order_to_wallet,
)


class WalletIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.original_path = settings.db_path
        await close_db()
        object.__setattr__(settings, "db_path", str(Path(self.temp.name) / "wallet.db"))
        await init_db()
        connection = sqlite3.connect(settings.db_path)
        try:
            migrate(connection)
        finally:
            connection.close()
        user = await create_user(telegram_id=90001, username="original", full_name="Test")
        self.user_id = user["id"]

    async def asyncTearDown(self):
        await close_db()
        object.__setattr__(settings, "db_path", self.original_path)
        self.temp.cleanup()

    async def _order(self, code, amount, status, product_type="key_api"):
        db = await get_db()
        cursor = await db.execute(
            """INSERT INTO orders (order_code, user_id, product_type, amount, payment_method, status)
               VALUES (?, ?, ?, ?, 'wallet', ?)""",
            (code, self.user_id, product_type, amount, status),
        )
        await db.commit()
        return cursor.lastrowid

    async def test_concurrent_credits_do_not_lose_updates(self):
        await add_balance(self.user_id, 100, "seed")
        await asyncio.wait_for(asyncio.gather(*(add_balance(self.user_id, 1, "credit") for _ in range(20))), 15)
        self.assertEqual(await get_balance(self.user_id), 120)
        db = await get_db()
        cursor = await db.execute("SELECT SUM(amount), COUNT(*) FROM wallet_transactions WHERE user_id = ?", (self.user_id,))
        self.assertEqual(tuple(await cursor.fetchone()), (120, 21))

    async def test_credits_across_processes_do_not_lose_updates(self):
        await add_balance(self.user_id, 100, "seed")
        script = """
import asyncio
from db.queries.wallets import add_balance
async def main():
    for _ in range(5):
        await add_balance(USER_ID, 1, 'credit')
asyncio.run(main())
""".replace("USER_ID", str(self.user_id))
        env = {**os.environ, "DB_PATH": settings.db_path}
        processes = await asyncio.gather(*(
            asyncio.create_subprocess_exec(
                sys.executable, "-c", script,
                cwd=str(Path(__file__).resolve().parents[1]), env=env,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            ) for _ in range(2)
        ))
        try:
            for process in processes:
                _, stderr = await asyncio.wait_for(process.communicate(), 20)
                self.assertEqual(process.returncode, 0, stderr.decode(errors="replace"))
        finally:
            for process in processes:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
        self.assertEqual(await get_balance(self.user_id), 110)

    async def test_simultaneous_debits_cannot_overspend(self):
        await add_balance(self.user_id, 100, "seed")
        outcomes = await asyncio.wait_for(asyncio.gather(
            deduct_balance(self.user_id, 80), deduct_balance(self.user_id, 80), return_exceptions=True
        ), 15)
        self.assertEqual(sum(isinstance(value, ValueError) for value in outcomes), 1)
        self.assertEqual(await get_balance(self.user_id), 20)
        with self.assertRaises(ValueError):
            await deduct_balance(self.user_id, -1)
        with self.assertRaises(ValueError):
            await deduct_balance(self.user_id, 0)
        with self.assertRaises(ValueError):
            await add_balance(self.user_id, 1.5, "credit")

    async def test_ledger_failure_rolls_back_balance(self):
        await add_balance(self.user_id, 100, "seed")
        db = await get_db()
        await db.execute("""CREATE TRIGGER fail_credit BEFORE INSERT ON wallet_transactions
                            WHEN NEW.type = 'credit' BEGIN SELECT RAISE(ABORT, 'test failure'); END""")
        await db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            await add_balance(self.user_id, 10, "credit")
        self.assertEqual(await get_balance(self.user_id), 100)
        cursor = await db.execute("SELECT COUNT(*) FROM wallet_transactions WHERE user_id = ?", (self.user_id,))
        self.assertEqual((await cursor.fetchone())[0], 1)

    async def test_wallet_write_does_not_commit_unrelated_transaction(self):
        await add_balance(self.user_id, 100, "seed")
        db = await get_db()
        await db.execute("BEGIN IMMEDIATE")
        await db.execute("UPDATE users SET username = 'uncommitted' WHERE id = ?", (self.user_id,))
        task = asyncio.create_task(add_balance(self.user_id, 10, "credit"))
        await asyncio.sleep(0.1)
        await db.rollback()
        await asyncio.wait_for(task, 10)
        cursor = await db.execute("SELECT username FROM users WHERE id = ?", (self.user_id,))
        self.assertEqual((await cursor.fetchone())[0], "original")
        self.assertEqual(await get_balance(self.user_id), 110)

    async def test_duplicate_order_charge_and_refund_are_single(self):
        await add_balance(self.user_id, 100, "seed")
        order_id = await self._order("test-order", 40, "pending")
        charged = await asyncio.wait_for(asyncio.gather(
            charge_pending_order_from_wallet(order_id), charge_pending_order_from_wallet(order_id)
        ), 15)
        self.assertEqual(sum(item is not None for item in charged), 1)
        self.assertEqual(await get_balance(self.user_id), 60)
        refunds = await asyncio.wait_for(asyncio.gather(
            refund_order_to_wallet(order_id, reason="test"), refund_order_to_wallet(order_id, reason="test")
        ), 15)
        self.assertEqual(sum(item is not None for item in refunds), 1)
        self.assertEqual(await get_balance(self.user_id), 100)

    async def test_duplicate_wallet_topup_is_single(self):
        order_id = await self._order("test-topup", 40, "paid", product_type="wallet_topup")
        results = await asyncio.wait_for(asyncio.gather(
            complete_wallet_topup_order(order_id), complete_wallet_topup_order(order_id)
        ), 15)
        self.assertEqual(sum(item is not None for item in results), 1)
        self.assertEqual(await get_balance(self.user_id), 40)

    async def test_refund_rejects_unpaid_processing_and_completed_orders(self):
        for status in ("pending", "processing", "completed"):
            order_id = await self._order("guard-" + status, 40, status, product_type="key_new")
            self.assertIsNone(await refund_order_to_wallet(order_id, reason="test"))

    async def test_negative_order_cannot_increase_balance(self):
        await add_balance(self.user_id, 100, "seed")
        order_id = await self._order("negative", -40, "pending", product_type="key_new")
        with self.assertRaises(ValueError):
            await charge_pending_order_from_wallet(order_id)
        self.assertEqual(await get_balance(self.user_id), 100)
        db = await get_db()
        cursor = await db.execute("SELECT COUNT(*) FROM wallet_transactions WHERE reference_id = 'negative'")
        self.assertEqual((await cursor.fetchone())[0], 0)

    async def test_refund_and_queued_worker_cannot_both_win(self):
        await add_balance(self.user_id, 100, "seed")
        order_id = await self._order("queue-race", 40, "pending", product_type="key_new")
        await charge_pending_order_from_wallet(order_id)
        claim, refund = await asyncio.gather(claim_next("worker"), refund_order_to_wallet(order_id, reason="test"))
        self.assertNotEqual(claim is not None, refund is not None)
        db = await get_db()
        cursor = await db.execute("SELECT status FROM fulfillment_jobs WHERE order_id = ?", (order_id,))
        self.assertEqual((await cursor.fetchone())[0], "processing" if claim else "cancelled")

    async def test_wallet_topup_rejects_wrong_type_and_negative_amount(self):
        await add_balance(self.user_id, 100, "seed")
        wrong_type = await self._order("wrong-type", 40, "paid", product_type="key_new")
        negative = await self._order("negative-topup", -40, "paid", product_type="wallet_topup")
        self.assertIsNone(await complete_wallet_topup_order(wrong_type))
        self.assertIsNone(await complete_wallet_topup_order(negative))
        self.assertEqual(await get_balance(self.user_id), 100)

    async def test_refund_releases_reserved_stock(self):
        category_id = await create_category("Accounts", cat_type="account_stocked")
        product_id = await create_product(category_id=category_id, name="Account", price_vnd=40, product_type="account_stocked")
        await add_account(product_id, "fixture")
        order_id = await self._order("stock-refund", 40, "pending", product_type="account_stocked")
        db = await get_db()
        await db.execute("UPDATE orders SET product_id = ? WHERE id = ?", (product_id, order_id))
        await db.commit()
        self.assertEqual(len(await reserve_accounts(product_id, order_id, 1)), 1)
        await add_balance(self.user_id, 100, "seed")
        await charge_pending_order_from_wallet(order_id)
        self.assertEqual(await refund_order_to_wallet(order_id, reason="test"), 100)
        cursor = await db.execute("SELECT sold_order_id, is_sold FROM account_stocks WHERE product_id = ?", (product_id,))
        self.assertEqual(tuple(await cursor.fetchone()), (None, 0))

    async def test_refund_rejects_existing_remote_operation(self):
        await add_balance(self.user_id, 100, "seed")
        order_id = await self._order("operation-refund", 40, "pending", product_type="key_new")
        await charge_pending_order_from_wallet(order_id)
        db = await get_db()
        cursor = await db.execute("SELECT id FROM fulfillment_jobs WHERE order_id = ?", (order_id,))
        job_id = (await cursor.fetchone())[0]
        await db.execute("""INSERT INTO fulfillment_operations (job_id, item_index, operation_key, status)
                            VALUES (?, 0, 'test-operation', 'sending')""", (job_id,))
        await db.commit()
        self.assertIsNone(await refund_order_to_wallet(order_id, reason="test"))
        self.assertEqual(await get_balance(self.user_id), 60)


if __name__ == "__main__":
    unittest.main()
