"""Exercise real dispatcher routing when leaving a pending input flow."""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aiogram import Bot
from aiogram.types import Chat, Message, Update, User

from bot.config import settings
from bot.handlers.flow_accounts import UpgradeStates
from bot.handlers.flow_api_key import ApiKeyStates
from bot.handlers.search_order import SearchOrderStates
from bot.handlers.wallet import WalletTopupStates
from bot.keyboards.reply_kb import main_menu_kb
from bot.main import build_dispatcher
from db.bootstrap import init_db
from db.database import close_db
from db.queries.users import get_user_by_telegram_id, set_banned


class MenuNavigationTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.dispatcher = build_dispatcher()

    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.original_path = settings.db_path
        await close_db()
        object.__setattr__(settings, "db_path", str(Path(self.temp.name) / "menu.sqlite"))
        await init_db()
        self.bot = Bot("123456:test-token")
        self.bot._me = User(id=self.bot.id, is_bot=True, first_name="Bot", username="TestMenuBot")
        self.api = AsyncMock(return_value=None)
        self.api_patch = patch.object(Bot, "__call__", self.api)
        self.api_patch.start()
        self.message_id = 0
        self.state = self.dispatcher.fsm.get_context(bot=self.bot, chat_id=7001, user_id=7001)

    async def asyncTearDown(self):
        self.api_patch.stop()
        await self.bot.session.close()
        await close_db()
        object.__setattr__(settings, "db_path", self.original_path)
        self.temp.cleanup()

    async def send(self, text):
        self.message_id += 1
        self.api.reset_mock()
        message = Message(
            message_id=self.message_id, date=datetime.now(timezone.utc),
            chat=Chat(id=7001, type="private"),
            from_user=User(id=7001, is_bot=False, first_name="Customer"), text=text,
        )
        await self.dispatcher.feed_update(self.bot, Update(update_id=self.message_id, message=message))
        return "\n".join(str(call.args[0].text) for call in self.api.await_args_list)

    async def test_search_then_support_or_account_routes_to_the_requested_screen(self):
        for label, expected in (("🆘 Hỗ trợ", "Hỗ trợ"), ("👤 Tài khoản", "Tài khoản của bạn")):
            with self.subTest(label=label):
                await self.send("🔎 Tìm đơn")
                self.assertEqual(await self.state.get_state(), SearchOrderStates.waiting_order_code.state)
                reply = await self.send(label)
                self.assertIn(expected, reply)
                self.assertNotIn("Mã đơn không hợp lệ", reply)
                self.assertIsNone(await self.state.get_state())
                self.assertEqual(await self.state.get_data(), {})

    async def test_all_menu_buttons_leave_all_input_states(self):
        states = (
            SearchOrderStates.waiting_order_code,
            WalletTopupStates.waiting_custom_amount,
            ApiKeyStates.waiting_existing_key,
            ApiKeyStates.waiting_key_search,
            ApiKeyStates.waiting_custom_dollar,
            UpgradeStates.waiting_user_input,
        )
        buttons = [button.text for row in main_menu_kb().keyboard for button in row] + ["🛒 Sản phẩm"]
        for state in states:
            for label in buttons:
                with self.subTest(state=state.state, label=label):
                    await self.state.set_state(state)
                    await self.state.set_data({"server_id": 999, "old_input": "pending"})
                    reply = await self.send(label)
                    self.assertTrue(reply)
                    self.assertNotIn("Mã đơn không hợp lệ", reply)
                    expected = SearchOrderStates.waiting_order_code.state if label == "🔎 Tìm đơn" else None
                    self.assertEqual(await self.state.get_state(), expected)
                    self.assertEqual(await self.state.get_data(), {})

    async def test_navigation_commands_work_in_input_flows(self):
        for command in ("start", "menu", "products", "wallet", "orders", "search", "profile", "support"):
            for suffix in ("", "@TestMenuBot"):
                with self.subTest(command=command, suffix=suffix):
                    await self.state.set_state(UpgradeStates.waiting_user_input)
                    await self.state.set_data({"old_input": "pending"})
                    self.assertTrue(await self.send(f"/{command}{suffix}"))
                    expected = SearchOrderStates.waiting_order_code.state if command == "search" else None
                    self.assertEqual(await self.state.get_state(), expected)
                    self.assertEqual(await self.state.get_data(), {})

    async def test_order_input_and_other_bot_commands_do_not_cancel_the_flow(self):
        await self.send("🔎 Tìm đơn")
        await self.state.set_data({"input_marker": "keep"})
        for text in ("invalid order", "/support@AnotherBot"):
            reply = await self.send(text)
            self.assertIn("Mã đơn không hợp lệ", reply)
            self.assertEqual(await self.state.get_state(), SearchOrderStates.waiting_order_code.state)
            self.assertEqual(await self.state.get_data(), {"input_marker": "keep"})
        with patch("bot.handlers.search_order.get_order_by_code", AsyncMock(return_value=None)) as lookup:
            reply = await self.send("ORD12345678")
            lookup.assert_awaited_once_with("ORD12345678")
            self.assertIn("Không tìm thấy", reply)
            self.assertEqual(await self.state.get_state(), SearchOrderStates.waiting_order_code.state)

    async def test_navigation_still_blocks_banned_users(self):
        await self.send("🔎 Tìm đơn")
        user = await get_user_by_telegram_id(7001)
        await set_banned(user["id"])
        reply = await self.send("🆘 Hỗ trợ")
        self.assertIn("đã bị khóa", reply)
        self.assertNotIn("Liên hệ", reply)


if __name__ == "__main__":
    unittest.main()
