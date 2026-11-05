"""Check critical worker failure shuts down the integrated bot cleanly."""
import asyncio
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# The lifecycle test never renders a QR image.
sys.modules.setdefault("cairosvg", types.ModuleType("cairosvg"))
from bot import main as bot_main
from bot.config import Settings


class WorkerLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def test_blank_portal_session_secret_falls_back_to_admin_secret(self):
        with patch.dict(os.environ, {"ADMIN_SECRET_KEY": "admin-secret-for-test", "PORTAL_SESSION_SECRET": ""}):
            self.assertEqual(Settings().portal_session_secret, "admin-secret-for-test")
        with patch.dict(os.environ, {"ADMIN_SECRET_KEY": "admin-secret-for-test", "PORTAL_SESSION_SECRET": "separate-secret"}):
            self.assertEqual(Settings().portal_session_secret, "separate-secret")

    def test_runtime_requires_explicit_nondefault_admin_secret(self):
        example = "Y2qhnQoDMTtoIj3O2M5q9Ke9zWoqDyQ0"
        for value in ("", "short", example, " " * 40):
            with self.subTest(value=value), patch.dict(os.environ, {"ADMIN_SECRET_KEY": value}), \
                 patch.object(bot_main, "settings", types.SimpleNamespace(admin_secret_key=value)):
                with self.assertRaises(RuntimeError):
                    bot_main.validate_runtime_secrets()
        value = "test-only-secret-" + "x" * 32
        with patch.dict(os.environ, {"ADMIN_SECRET_KEY": value}), \
             patch.object(bot_main, "settings", types.SimpleNamespace(admin_secret_key=value)):
            bot_main.validate_runtime_secrets()

    async def test_admin_server_uses_configured_loopback_host(self):
        config = types.SimpleNamespace(admin_host="127.0.0.1", admin_port=8080)
        server = types.SimpleNamespace(serve=AsyncMock())
        with patch.object(bot_main, "settings", config), \
             patch("admin.app.create_admin_app", return_value=object()), \
             patch("uvicorn.Config") as uvicorn_config, \
             patch("uvicorn.Server", return_value=server):
            task = await bot_main.start_admin_server()
            await task
        self.assertEqual(uvicorn_config.call_args.kwargs["host"], "127.0.0.1")
        server.serve.assert_awaited_once()

    async def test_bad_admin_secret_stops_before_database_access(self):
        config = types.SimpleNamespace(bot_token="test", admin_secret_key="short")
        with patch.dict(os.environ, {"ADMIN_SECRET_KEY": "short"}), \
             patch.object(bot_main, "settings", config), \
             patch.object(bot_main, "init_db", AsyncMock()) as init_db:
            with self.assertRaisesRegex(RuntimeError, "ADMIN_SECRET_KEY"):
                await bot_main.main()
        init_db.assert_not_awaited()

    async def test_critical_worker_exit_stops_bot(self):
        async def wait_forever(*args, **kwargs):
            await asyncio.Event().wait()

        bot = types.SimpleNamespace(session=types.SimpleNamespace(close=AsyncMock()))
        dispatcher = types.SimpleNamespace(start_polling=AsyncMock(side_effect=wait_forever))
        config = types.SimpleNamespace(bot_token="test", key_vault_url="", key_vault_api_token="", key_vault_lookup_secret="")
        with patch.object(bot_main, "settings", config), \
             patch.object(bot_main, "validate_runtime_secrets"), \
             patch.object(bot_main, "init_db", AsyncMock()), \
             patch.object(bot_main, "require_financial_schema", AsyncMock()), \
             patch.object(bot_main, "close_db", AsyncMock()) as close_db, \
             patch.object(bot_main, "build_bot", return_value=bot), \
             patch.object(bot_main, "build_dispatcher", return_value=dispatcher), \
             patch.object(bot_main, "register_bot_commands", AsyncMock()), \
             patch.object(bot_main, "start_payment_poller", AsyncMock()), \
             patch.object(bot_main, "start_fulfillment_worker", AsyncMock(side_effect=wait_forever)), \
             patch.object(bot_main, "start_notification_worker", AsyncMock(side_effect=wait_forever)), \
             patch.object(bot_main, "start_key_alert_poller", AsyncMock(side_effect=wait_forever)), \
             patch.object(bot_main, "start_key_backup_poller", AsyncMock(side_effect=wait_forever)), \
             patch.object(bot_main, "start_control_plane_sync", AsyncMock(side_effect=wait_forever)), \
             patch.object(bot_main, "start_admin_server", AsyncMock(return_value=None)):
            with self.assertRaisesRegex(RuntimeError, "critical background task"):
                await asyncio.wait_for(bot_main.main(), 5)
        close_db.assert_awaited_once()
        bot.session.close.assert_awaited_once()

    async def test_missing_migration_closes_database(self):
        config = types.SimpleNamespace(bot_token="test")
        with patch.object(bot_main, "settings", config), \
             patch.object(bot_main, "validate_runtime_secrets"), \
             patch.object(bot_main, "init_db", AsyncMock()), \
             patch.object(bot_main, "require_financial_schema", AsyncMock(side_effect=RuntimeError("migration required"))), \
             patch.object(bot_main, "close_db", AsyncMock()) as close_db:
            with self.assertRaisesRegex(RuntimeError, "migration required"):
                await bot_main.main()
        close_db.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
