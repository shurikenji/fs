"""Verification for admin order notification outbox and retry behavior."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from bot.config import settings
from db.database import close_db
from db.models import init_db
from db.queries.admin_notifications import get_admin_notification_events
from db.queries.orders import create_order, get_order_by_id, update_order_status
from db.queries.servers import create_server
from db.queries.settings import set_setting
from db.queries.users import create_user


async def main() -> None:
    original_db_path = settings.db_path

    with TemporaryDirectory() as temp_dir:
        temp_db = Path(temp_dir) / "admin-order-notifications.db"
        await close_db()
        object.__setattr__(settings, "db_path", str(temp_db))

        try:
            await init_db()

            import bot.services.admin_order_notifications as admin_order_notifications

            user = await create_user(
                telegram_id=41001,
                username="notify-order",
                full_name="Notify Order Verify",
            )
            server_id = await create_server(
                name="Notify Server",
                base_url="https://example.com",
                user_id_header="new-api-user",
                access_token="secret",
                price_per_unit=1000,
                quota_per_unit=1000,
            )
            order_id = await create_order(
                order_code="ADMINNOTIFY001",
                user_id=user["id"],
                product_name="Notification Key",
                product_type="key_new",
                amount=55_000,
                payment_method="qr",
                server_id=server_id,
            )
            order = await get_order_by_id(order_id)
            assert order is not None

            await set_setting("admin_telegram_ids", "90001,90002")
            await set_setting("admin_notify_enabled", "true")
            await set_setting("admin_notify_order_completed", "true")

            sent_messages: list[tuple[int, str]] = []

            async def _fake_send_text(bot, chat_id: int, text: str) -> bool:
                _ = bot
                sent_messages.append((chat_id, text))
                return True

            original_send_text = admin_order_notifications.send_text
            admin_order_notifications.send_text = _fake_send_text
            try:
                first = await admin_order_notifications.notify_admin_order_completed(order, bot=object())
                second = await admin_order_notifications.notify_admin_order_completed(order, bot=object())

                assert first == (2, 0, 0)
                assert second == (0, 0, 2)
                assert len(sent_messages) == 2
                events = await get_admin_notification_events(order_id=order_id)
                assert len(events) == 2
                assert {event["status"] for event in events} == {"sent"}
                print("[OK] completed-order notifications are deduplicated per admin chat id")
            finally:
                admin_order_notifications.send_text = original_send_text

            long_order_id = await create_order(
                order_code="ADMINNOTIFY003",
                user_id=user["id"],
                product_name="Long Service Input",
                product_type="service_upgrade",
                amount=75_000,
                payment_method="qr",
            )
            await update_order_status(
                long_order_id,
                "pending",
                user_input_data="<secret>" + ("A" * 5000),
            )
            long_order = await get_order_by_id(long_order_id)
            assert long_order is not None

            sent_messages = []
            sent_files: list[tuple[int, str]] = []

            async def _fake_send_text_with_summary(bot, chat_id: int, text: str) -> bool:
                _ = bot
                sent_messages.append((chat_id, text))
                return True

            async def _fake_send_user_input_file(bot, chat_id: int, order: dict) -> bool:
                _ = bot
                sent_files.append((chat_id, str(order.get("order_code"))))
                return True

            original_send_text = admin_order_notifications.send_text
            original_send_user_input_file = admin_order_notifications._send_user_input_file
            await set_setting("admin_telegram_ids", "90011")
            admin_order_notifications.send_text = _fake_send_text_with_summary
            admin_order_notifications._send_user_input_file = _fake_send_user_input_file
            try:
                sent_long = await admin_order_notifications.notify_admin_service_paid(long_order, bot=object())
                assert sent_long == (1, 0, 0)
                assert len(sent_messages) == 1
                assert "xem file TXT đính kèm" in sent_messages[0][1]
                assert sent_files == [(90011, "ADMINNOTIFY003")]
                print("[OK] long service input sends a summary plus TXT attachment to admin")
            finally:
                admin_order_notifications.send_text = original_send_text
                admin_order_notifications._send_user_input_file = original_send_user_input_file

            retry_order_id = await create_order(
                order_code="ADMINNOTIFY002",
                user_id=user["id"],
                product_name="Retry Key",
                product_type="key_topup",
                amount=25_000,
                payment_method="wallet",
                server_id=server_id,
            )
            retry_order = await get_order_by_id(retry_order_id)
            assert retry_order is not None

            attempts: list[str] = []

            async def _flaky_send_text(bot, chat_id: int, text: str) -> bool:
                _ = bot, chat_id, text
                attempts.append("call")
                return len(attempts) > 1

            original_send_text = admin_order_notifications.send_text
            await set_setting("admin_telegram_ids", "90003")
            admin_order_notifications.send_text = _flaky_send_text
            try:
                failed = await admin_order_notifications.notify_admin_order_completed(retry_order, bot=object())
                retried = await admin_order_notifications.notify_admin_order_completed(retry_order, bot=object())

                assert failed == (0, 1, 0)
                assert retried == (1, 0, 0)
                retry_events = await get_admin_notification_events(order_id=retry_order_id)
                assert len(retry_events) == 1
                assert retry_events[0]["status"] == "sent"
                print("[OK] failed admin notifications can be retried and eventually marked sent")
            finally:
                admin_order_notifications.send_text = original_send_text

            print("\n=== ADMIN ORDER NOTIFICATION VERIFICATION PASSED ===")
        finally:
            await close_db()
            object.__setattr__(settings, "db_path", original_db_path)


asyncio.run(main())
