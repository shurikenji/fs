"""Do not trigger or silently mislabel local backups in remote Vault mode."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from admin.routers import key_backup


class RemoteVaultGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_dashboard_shows_vault_state_without_enabling_old_backup(self):
        from admin.app import create_admin_app
        from admin.deps import require_admin
        from bot.services import key_vault_client

        app = create_admin_app()
        app.dependency_overrides[require_admin] = lambda: {"admin": True}
        config = SimpleNamespace(key_vault_url="https://vault.test", key_vault_api_token="token", key_vault_lookup_secret="lookup")
        rows = [{"server": {"id": 1, "name": "server", "base_url": "https://example.test"}, "snapshot": None,
                 "status": "missing", "total_keys": 0, "total_balance": 0}]
        summary = [{"source_id": "source-1", "last_run_at": "2026-11-05 00:00:00", "last_status": "success", "active_count": 3, "stored_key_count": 2}]
        with patch.object(key_backup, "settings", config), patch.object(key_backup, "_build_overview_rows", AsyncMock(return_value=rows)), \
             patch.object(key_vault_client, "get_summary", AsyncMock(return_value=summary)):
            with TestClient(app, base_url="https://testserver") as client:
                response = client.get("/key-backup")
        self.assertEqual(response.status_code, 200)
        self.assertIn("source-1", response.text)
        self.assertIn("key được quan sát trong lần backup trước", response.text)
        self.assertNotIn('action="/key-backup/trigger/1"', response.text)

    async def test_summary_failure_is_not_misreported_as_empty(self):
        from bot.services import key_vault_client

        with patch.object(key_vault_client, "settings", SimpleNamespace(key_vault_url="", key_vault_api_token="token")):
            self.assertIsNone(await key_vault_client.get_summary())

    async def test_remote_or_incomplete_config_blocks_old_backup_paths(self):
        for config in (
            SimpleNamespace(key_vault_url="https://vault.test", key_vault_api_token="", key_vault_lookup_secret=""),
            SimpleNamespace(key_vault_url="", key_vault_api_token="test", key_vault_lookup_secret=""),
        ):
            with self.subTest(config=config), patch.object(key_backup, "settings", config), \
                 patch.object(key_backup, "backup_all_servers_now", AsyncMock()) as all_servers, \
                 patch.object(key_backup, "backup_server_now", AsyncMock()) as one_server:
                self.assertEqual((await key_backup.trigger_key_backup_all()).status_code, 303)
                self.assertEqual((await key_backup.trigger_key_backup_server(1)).status_code, 303)
                all_servers.assert_not_awaited()
                one_server.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
