"""Check notification dispatch without contacting Telegram."""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bot.services import notification_worker


class NotificationWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_delivery_escapes_html_and_marks_success(self):
        event = {"id": 1, "order_id": 2, "user_id": 3, "event_type": "user_order_completed", "lease_token": "token"}
        order = {"id": 2, "user_id": 3, "status": "completed", "product_type": "key_new",
                 "order_code": "ORD1", "api_key": "key<>&"}
        with patch.object(notification_worker, "claim_notification", AsyncMock(return_value=event)), \
             patch.object(notification_worker, "get_order_by_id", AsyncMock(return_value=order)), \
             patch.object(notification_worker, "notify_user", AsyncMock(return_value=True)) as send, \
             patch.object(notification_worker, "finish_notification", AsyncMock()) as finish:
            self.assertTrue(await notification_worker.run_one_notification(None))
        self.assertIn("key&lt;&gt;&amp;", send.await_args.args[1])
        finish.assert_awaited_once_with(1, "token", succeeded=True)

    async def test_missing_delivery_is_retried_without_sending(self):
        event = {"id": 1, "order_id": 2, "user_id": 3, "event_type": "user_order_completed", "lease_token": "token"}
        order = {"id": 2, "user_id": 3, "status": "completed", "product_type": "key_new", "order_code": "ORD1"}
        with patch.object(notification_worker, "claim_notification", AsyncMock(return_value=event)), \
             patch.object(notification_worker, "get_order_by_id", AsyncMock(return_value=order)), \
             patch.object(notification_worker, "notify_user", AsyncMock()) as send, \
             patch.object(notification_worker, "finish_notification", AsyncMock()) as finish:
            self.assertTrue(await notification_worker.run_one_notification(None))
        send.assert_not_awaited()
        finish.assert_awaited_once_with(1, "token", succeeded=False)

    async def test_service_paid_notifies_correct_customer(self):
        event = {"id": 1, "order_id": 2, "user_id": 3, "event_type": "user_service_paid", "lease_token": "token"}
        order = {"id": 2, "user_id": 3, "status": "processing", "product_type": "service_upgrade", "order_code": "ORD1"}
        with patch.object(notification_worker, "claim_notification", AsyncMock(return_value=event)), \
             patch.object(notification_worker, "get_order_by_id", AsyncMock(return_value=order)), \
             patch.object(notification_worker, "notify_user", AsyncMock(return_value=True)) as send, \
             patch.object(notification_worker, "finish_notification", AsyncMock()) as finish:
            self.assertTrue(await notification_worker.run_one_notification(None))
        self.assertEqual(send.await_args.args[0], 3)
        finish.assert_awaited_once_with(1, "token", succeeded=True)

    async def test_review_without_admin_recipient_is_not_marked_sent(self):
        event = {"id": 1, "order_id": 2, "user_id": 3, "event_type": "admin_order_review", "lease_token": "token"}
        order = {"id": 2, "user_id": 3, "status": "processing", "product_type": "key_new", "order_code": "ORD1"}
        with patch.object(notification_worker, "claim_notification", AsyncMock(return_value=event)), \
             patch.object(notification_worker, "get_order_by_id", AsyncMock(return_value=order)), \
             patch.object(notification_worker, "notify_admins", AsyncMock(return_value=(0, 0))), \
             patch.object(notification_worker, "finish_notification", AsyncMock()) as finish:
            self.assertTrue(await notification_worker.run_one_notification(None))
        finish.assert_awaited_once_with(1, "token", succeeded=False)


if __name__ == "__main__":
    unittest.main()
