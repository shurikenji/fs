"""Verify manual top-up reconciliation on an isolated real SQLite schema."""
import asyncio
import re
import sqlite3
import sys
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bot.config import settings
from bot.services import notification_worker
from bot.services.key_valuation import KeyValuationService, hash_api_key
from db.bootstrap import init_db
from db.database import close_db, get_db, open_write_transaction
from db.financial_migration import migrate
from db.queries.fulfillment import claim_next, enqueue_paid_order, finish_claim
from db.queries.manual_topup import complete_manual_topup
from db.queries.orders import create_order, get_order_by_id, update_order_status
from db.queries.servers import create_server, get_server_by_id
from db.queries.settings import set_setting
from db.queries.users import create_user


class ManualTopupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.previous = settings.db_path
        await close_db()
        object.__setattr__(settings, 'db_path', str(Path(self.temp.name) / 'test.sqlite'))
        await init_db()
        await close_db()
        with closing(sqlite3.connect(settings.db_path)) as db:
            migrate(db)
        user = await create_user(telegram_id=99442, username='test', full_name='Test')
        self.user_id = user['id']
        self.server_id = await create_server(name='Test', base_url='https://example.test', user_id_header='42',
                                             access_token='test', price_per_unit=1000, quota_per_unit=500000)
        self.order_id = await create_order(order_code='ORDTOPUP01', user_id=self.user_id, product_type='key_topup',
                                           amount=1000, payment_method='qr', server_id=self.server_id,
                                           existing_key='sk-example', custom_quota=100)
        await update_order_status(self.order_id, 'paid')
        db = await open_write_transaction()
        try:
            await enqueue_paid_order(db, self.order_id)
            await db.commit()
        finally:
            await db.close()
        self.claim = await claim_next('worker')

    async def asyncTearDown(self):
        await close_db()
        object.__setattr__(settings, 'db_path', self.previous)
        self.temp.cleanup()

    async def review(self):
        await finish_claim(self.claim['id'], self.claim['lease_token'], succeeded=True)

    async def complete(self):
        return await complete_manual_topup(self.order_id, 42, 500, 600, 100, 'ticket-123', 'password')

    async def test_requires_review_and_rejects_invalid_evidence(self):
        self.assertFalse(await self.complete())
        await self.review()
        with self.assertRaises(ValueError):
            await complete_manual_topup(self.order_id, 42, 500, 601, 100, 'ticket-123', 'password')
        with self.assertRaises(ValueError):
            await complete_manual_topup(self.order_id, 42, 500, 700, 200, 'ticket-123', 'password')
        self.assertEqual((await get_order_by_id(self.order_id))['status'], 'processing')

    async def test_concurrent_completion_is_once_and_notifications_work(self):
        await self.review()
        self.assertEqual(sorted(await asyncio.gather(self.complete(), self.complete())), [False, True])
        db = await get_db()
        for table in ('api_key_valuation_events', 'fulfillment_operations', 'spend_ledger', 'user_keys'):
            cursor = await db.execute(f'SELECT COUNT(*) FROM {table}')
            self.assertEqual((await cursor.fetchone())[0], 1)
        with patch.object(notification_worker, 'notify_user', AsyncMock(return_value=True)) as user_send, \
             patch.object(notification_worker, 'notify_admin_order_completed', AsyncMock(return_value=(1, 0, 0))) as admin_send, \
             patch.object(notification_worker, 'notify_admins', AsyncMock()) as review_send:
            for _ in range(4):
                self.assertTrue(await notification_worker.run_one_notification(None))
        user_send.assert_awaited_once()
        admin_send.assert_awaited_once()
        review_send.assert_not_awaited()

    async def test_failure_rolls_back_all_reconciliation_changes(self):
        await self.review()
        db = await get_db()
        await db.execute("CREATE TRIGGER fail_ledger BEFORE INSERT ON spend_ledger BEGIN SELECT RAISE(ABORT, 'injected'); END")
        await db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            await self.complete()
        self.assertEqual((await get_order_by_id(self.order_id))['status'], 'processing')
        for table in ('api_key_valuation_events', 'fulfillment_operations', 'spend_ledger', 'user_keys'):
            cursor = await db.execute(f'SELECT COUNT(*) FROM {table}')
            self.assertEqual((await cursor.fetchone())[0], 0)

    async def test_conflicting_key_or_pending_operation_are_rejected(self):
        await self.review()
        other = await create_user(telegram_id=99443, username='other', full_name='Other')
        db = await get_db()
        await db.execute("INSERT INTO api_key_registry (server_id, api_key_hash, owner_user_id) VALUES (?, ?, ?)",
                         (self.server_id, hash_api_key('sk-example'), other['id']))
        await db.commit()
        with self.assertRaises(ValueError):
            await self.complete()
        await db.execute('DELETE FROM api_key_registry')
        await db.execute("INSERT INTO fulfillment_operations (job_id, item_index, operation_key, status) VALUES (?, 0, 'uncertain', 'sending')", (self.claim['id'],))
        await db.commit()
        self.assertFalse(await self.complete())
        self.assertEqual((await get_order_by_id(self.order_id))['status'], 'processing')

    async def test_import_waits_for_pending_topup_and_does_not_double_credit(self):
        await self.review()
        server = await get_server_by_id(self.server_id)
        args = dict(user_id=self.user_id, server=server, api_key='sk-example',
                    token_data={'remain_quota': 550, 'used_quota': 50})
        self.assertEqual((await KeyValuationService.evaluate_imported_key(**args))['status'], 'pending_reconciliation')
        db = await get_db()
        await db.execute('UPDATE orders SET is_refunded = NULL WHERE id = ?', (self.order_id,))
        await db.commit()
        self.assertEqual((await KeyValuationService.evaluate_imported_key(**args))['status'], 'pending_reconciliation')
        await db.execute('UPDATE orders SET is_refunded = 0 WHERE id = ?', (self.order_id,))
        await db.commit()
        self.assertTrue(await self.complete())
        self.assertEqual((await KeyValuationService.evaluate_imported_key(**args))['status'], 'no_change')
        db = await get_db()
        cursor = await db.execute('SELECT COUNT(*), SUM(amount) FROM spend_ledger')
        self.assertEqual(tuple(await cursor.fetchone()), (1, 1000))

    async def test_admin_route_requires_session_csrf_and_confirmation(self):
        from admin.app import create_admin_app

        await self.review()
        await set_setting('admin_password', 'test password for reconciliation')
        url = f'/orders/{self.order_id}/complete-manual-topup'
        payload = {'token_id': '42', 'total_before': '500', 'total_after': '600',
                   'quota_added': '100', 'evidence': 'ticket-123'}
        with TestClient(create_admin_app(), base_url='https://testserver') as client:
            self.assertEqual(client.post(url, data=payload, follow_redirects=False).status_code, 303)
            page = client.get(settings.admin_login_path)
            token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
            self.assertEqual(client.post(settings.admin_login_path, data={'password': 'test password for reconciliation', 'csrf_token': token}, follow_redirects=False).status_code, 303)
            page = client.get(f'/orders/{self.order_id}')
            self.assertIn('Đối soát nạp key thủ công', page.text)
            token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
            self.assertEqual(client.post(url, data=payload, follow_redirects=False).status_code, 403)
            payload['csrf_token'] = token
            self.assertEqual(client.post(url, data=payload, follow_redirects=False).status_code, 400)
            payload['confirmed'] = 'yes'
            self.assertEqual(client.post(url, data=payload, follow_redirects=False).status_code, 303)
            self.assertEqual(client.post(url, data=payload, follow_redirects=False).status_code, 409)


if __name__ == '__main__':
    unittest.main()
