"""Check pricing, spend and key valuation transactions on isolated SQLite."""
import asyncio
import sqlite3
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.config import settings
from bot.services.key_valuation import KeyValuationService
from bot.services.spend_ledger import SpendLedgerService
from db.bootstrap import init_db
from db.database import close_db, get_db, open_write_transaction
from db.financial_migration import migrate
from db.queries.fulfillment import begin_operation, claim_next, complete_key_order, confirm_created_key, enqueue_paid_order
from db.queries.orders import create_order, get_order_by_id, update_order_status
from db.queries.wallets import add_balance, charge_pending_order_from_wallet, get_balance, refund_order_to_wallet
from db.queries.pricing import get_server_discount_tiers, replace_server_discount_tiers, sync_server_pricing_version
from db.queries.servers import create_server, get_server_by_id
from db.queries.users import create_user


class TransactionOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.original_path = settings.db_path
        await close_db()
        object.__setattr__(settings, "db_path", str(Path(self.temp.name) / "transactions.db"))
        await init_db()
        user = await create_user(telegram_id=90002, username="test", full_name="Test")
        self.user_id = user["id"]
        self.server_id = await create_server(
            name="Test", base_url="https://example.test", user_id_header="42", access_token="test",
            price_per_unit=1000, quota_per_unit=500000, api_type="newapi",
        )

    async def asyncTearDown(self):
        await close_db()
        object.__setattr__(settings, "db_path", self.original_path)
        self.temp.cleanup()

    async def test_discount_replacement_rolls_back_on_error(self):
        await replace_server_discount_tiers(self.server_id, [{"name": "old", "min_spend_vnd": 0}])
        with self.assertRaises(sqlite3.ProgrammingError):
            await replace_server_discount_tiers(self.server_id, [{
                "name": "new", "min_spend_vnd": 0,
                "benefits": [{"type": "discount", "value": object()}],
            }])
        tiers = await get_server_discount_tiers(self.server_id)
        self.assertEqual([tier["name"] for tier in tiers], ["old"])

    async def test_concurrent_duplicate_spend_records_are_single(self):
        async def record():
            return await SpendLedgerService.record(
                user_id=self.user_id, server_id=self.server_id, source_type="test",
                source_ref="same-operation", amount=10,
            )
        outcomes = await asyncio.wait_for(asyncio.gather(*(record() for _ in range(5))), 15)
        self.assertEqual(sum(value is not None for value in outcomes), 1)
        db = await get_db()
        cursor = await db.execute("SELECT COUNT(*), SUM(amount) FROM spend_ledger")
        self.assertEqual(tuple(await cursor.fetchone()), (1, 10))
        cursor = await db.execute("SELECT total_spend_vnd FROM user_server_spend_summary")
        self.assertEqual((await cursor.fetchone())[0], 10)

    async def test_simultaneous_key_offsets_keep_highest_baseline(self):
        await sync_server_pricing_version(self.server_id)
        server = await get_server_by_id(self.server_id)
        async def record(total):
            return await KeyValuationService.record_platform_quota_offset(
                user_id=self.user_id, server=server, api_key="sk-test-key",
                quota_delta=100, resulting_total_quota=total, source="test", source_ref=str(total),
            )
        await asyncio.wait_for(asyncio.gather(record(100), record(200)), 15)
        db = await get_db()
        cursor = await db.execute("SELECT COUNT(*), MAX(last_observed_total_quota) FROM api_key_registry")
        self.assertEqual(tuple(await cursor.fetchone()), (1, 200))

    async def test_key_offset_participates_in_owning_transaction(self):
        server = await get_server_by_id(self.server_id)
        db = await open_write_transaction()
        try:
            await KeyValuationService.record_platform_quota_offset(
                user_id=self.user_id, server=server, api_key="sk-test-key", quota_delta=100,
                resulting_total_quota=100, source="test", _db=db, _pricing_version={"id": None},
            )
            await db.rollback()
        finally:
            await db.close()
        db = await get_db()
        for table in ("api_key_registry", "api_key_valuation_events"):
            cursor = await db.execute(f"SELECT COUNT(*) FROM {table}")
            self.assertEqual((await cursor.fetchone())[0], 0)

        transaction = await open_write_transaction()
        try:
            await KeyValuationService.record_platform_quota_offset(
                user_id=self.user_id, server=server, api_key="sk-test-key", quota_delta=100,
                resulting_total_quota=100, source="test", _db=transaction, _pricing_version={"id": None},
            )
            await transaction.commit()
        finally:
            await transaction.close()
        cursor = await db.execute("SELECT last_observed_total_quota FROM api_key_registry")
        self.assertEqual((await cursor.fetchone())[0], 100)

    async def test_key_completion_ledger_and_outbox_commit_together(self):
        await close_db()
        connection = sqlite3.connect(settings.db_path)
        try:
            migrate(connection)
        finally:
            connection.close()
        order_id = await create_order(order_code="ORDTEST0001", user_id=self.user_id, product_type="key_new",
                                      amount=100, payment_method="qr", server_id=self.server_id)
        await update_order_status(order_id, "paid")
        db = await open_write_transaction()
        try:
            await enqueue_paid_order(db, order_id)
            await db.commit()
        finally:
            await db.close()
        claim = await claim_next("worker")
        op = await begin_operation(claim["id"], claim["lease_token"], 0)
        self.assertTrue(await confirm_created_key(claim["id"], claim["lease_token"], op, "test", None, 100))
        self.assertFalse(await complete_key_order(claim["id"], claim["lease_token"], {"api_key": "wrong"}))
        db = await get_db()
        await db.execute("UPDATE api_key_valuation_events SET status = 'invalid'")
        await db.commit()
        self.assertFalse(await complete_key_order(claim["id"], claim["lease_token"], {"api_key": "test"}))
        await db.execute("UPDATE api_key_valuation_events SET status = 'platform_offset'")
        await db.commit()
        await db.execute("""CREATE TRIGGER fail_outbox BEFORE INSERT ON notification_outbox
                            BEGIN SELECT RAISE(ABORT, 'injected failure'); END""")
        await db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            await complete_key_order(claim["id"], claim["lease_token"], {"api_key": "test"})
        cursor = await db.execute("SELECT status FROM orders WHERE id = ?", (order_id,))
        self.assertEqual((await cursor.fetchone())[0], "processing")
        cursor = await db.execute("SELECT COUNT(*) FROM spend_ledger")
        self.assertEqual((await cursor.fetchone())[0], 0)
        await db.execute("DROP TRIGGER fail_outbox")
        await db.commit()
        self.assertTrue(await complete_key_order(claim["id"], claim["lease_token"], {"api_key": "test"}))
        cursor = await db.execute("SELECT COUNT(*), SUM(amount) FROM spend_ledger")
        self.assertEqual(tuple(await cursor.fetchone()), (1, 100))
        cursor = await db.execute("SELECT COUNT(*) FROM notification_outbox")
        self.assertEqual((await cursor.fetchone())[0], 2)

    async def test_refund_and_spend_reversal_roll_back_together(self):
        await close_db()
        connection = sqlite3.connect(settings.db_path)
        try:
            migrate(connection)
        finally:
            connection.close()
        await add_balance(self.user_id, 200, "seed")
        order_id = await create_order(order_code="ORDTEST0002", user_id=self.user_id, product_type="key_new",
                                      amount=100, payment_method="wallet", server_id=self.server_id)
        order = await charge_pending_order_from_wallet(order_id)
        await SpendLedgerService.record_order_completion(order)
        db = await get_db()
        await db.execute("""CREATE TRIGGER fail_reversal BEFORE INSERT ON spend_ledger
                            WHEN NEW.source_type='order_refund' BEGIN SELECT RAISE(ABORT, 'injected'); END""")
        await db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            await refund_order_to_wallet(order_id, reason="test")
        self.assertEqual(await get_balance(self.user_id), 100)
        self.assertEqual((await get_order_by_id(order_id))["status"], "paid")
        await db.execute("DROP TRIGGER fail_reversal")
        await db.commit()
        self.assertEqual(await refund_order_to_wallet(order_id, reason="test"), 200)
        cursor = await db.execute("SELECT COUNT(*), SUM(amount) FROM spend_ledger")
        self.assertEqual(tuple(await cursor.fetchone()), (2, 0))


if __name__ == "__main__":
    unittest.main()
