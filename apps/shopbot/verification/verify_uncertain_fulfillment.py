"""Fail-closed checks for ambiguous upstream fulfillment results."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.services import payment_poller
from db.queries import fulfillment


class UncertainFulfillmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_is_not_retried_after_unknown_response(self):
        client = SimpleNamespace(create_token=AsyncMock(return_value=None))
        result = await payment_poller._create_key_with_retry(
            client, server={}, quota=1, group_name="", base_token_name="order", sequence=1
        )
        self.assertEqual(result, (None, None))
        client.create_token.assert_awaited_once()

    async def test_unknown_create_keeps_order_for_review(self):
        order = {"id": 1, "order_code": "A", "user_id": 2}
        client = SimpleNamespace(create_token=AsyncMock(return_value=None))
        with patch.object(payment_poller, "_load_key_order_context", AsyncMock(return_value=({"id": 1}, {"quota_amount": 1}))), \
             patch.object(payment_poller, "get_api_client", return_value=client), \
             patch.object(payment_poller, "update_order_status", AsyncMock()) as status, \
             patch.object(payment_poller, "_refund_order", AsyncMock()) as refund, \
             patch.object(payment_poller, "add_log", AsyncMock()), \
             patch.object(payment_poller, "get_setting", AsyncMock(return_value="support")), \
             patch.object(payment_poller, "notify_user", AsyncMock()):
            await payment_poller._process_key_new(None, order)
        refund.assert_not_awaited()
        self.assertEqual(status.await_args.args[:2], (1, "processing"))
        self.assertTrue(status.await_args.kwargs["api_token_name"])
        client.create_token.assert_awaited_once()

    async def test_attempt_name_is_saved_before_upstream_call(self):
        order = {"id": 1, "order_code": "A", "user_id": 2}
        status = AsyncMock()

        async def interrupted_create(**kwargs):
            self.assertEqual(status.await_args.kwargs["api_token_name"], kwargs["name"])
            raise RuntimeError("process interrupted")

        client = SimpleNamespace(create_token=AsyncMock(side_effect=interrupted_create))
        with patch.object(payment_poller, "_load_key_order_context", AsyncMock(return_value=({"id": 1}, {"quota_amount": 1}))), \
             patch.object(payment_poller, "get_api_client", return_value=client), \
             patch.object(payment_poller, "update_order_status", status):
            with self.assertRaisesRegex(RuntimeError, "process interrupted"):
                await payment_poller._process_key_new(None, order)

    async def test_unknown_topup_does_not_refund(self):
        order = {"id": 1, "order_code": "A", "existing_key": "secret"}
        client = SimpleNamespace(
            search_token=AsyncMock(return_value={"id": 3, "remain_quota": 10}),
            update_token=AsyncMock(return_value=None),
        )
        with patch.object(payment_poller, "_load_key_order_context", AsyncMock(return_value=({"id": 1}, {"quota_amount": 1}))), \
             patch.object(payment_poller, "get_api_client", return_value=client), \
             patch.object(payment_poller, "_refund_order", AsyncMock()) as refund, \
             patch.object(payment_poller, "add_log", AsyncMock()) as log:
            await payment_poller._process_key_topup(None, order)
        refund.assert_not_awaited()
        log.assert_awaited_once()

    async def test_error_after_completion_does_not_refund(self):
        order = {"id": 1, "order_code": "A", "product_type": "key_new"}
        with patch.object(payment_poller, "_process_key_new", AsyncMock(side_effect=RuntimeError("notification failed"))), \
             patch.object(payment_poller, "_refund_order", AsyncMock()) as refund, \
             patch.object(payment_poller, "add_log", AsyncMock()):
            await payment_poller._execute_order(None, order)
        refund.assert_not_awaited()

    async def test_worker_does_not_create_key_without_operation_claim(self):
        order = {"id": 1, "order_code": "A", "user_id": 2,
                 "_fulfillment_claim": {"id": 3, "lease_token": "stale"}}
        with patch.object(payment_poller, "_load_key_order_context", AsyncMock(return_value=({"id": 1}, {"quota_amount": 1}))), \
             patch.object(payment_poller, "get_api_client"), \
             patch.object(payment_poller, "update_order_status", AsyncMock()), \
             patch.object(fulfillment, "begin_operation", AsyncMock(return_value=None)), \
             patch.object(payment_poller, "_create_key_with_retry", AsyncMock()) as create:
            with self.assertRaisesRegex(RuntimeError, "lease is invalid"):
                await payment_poller._process_key_new(None, order)
        create.assert_not_awaited()

    async def test_worker_topup_is_held_for_manual_reconciliation(self):
        order = {"id": 1, "order_code": "A", "user_id": 2,
                 "_fulfillment_claim": {"id": 3, "lease_token": "token"}}
        with patch.object(payment_poller, "_load_key_order_context", AsyncMock()) as context, \
             patch.object(payment_poller, "add_log", AsyncMock()), \
             patch.object(payment_poller, "notify_user", AsyncMock()):
            await payment_poller._process_key_topup(None, order)
        context.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
