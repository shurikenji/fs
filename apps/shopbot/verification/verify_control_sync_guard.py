"""Verify source identity, separate quota and atomic revision updates."""
import sqlite3
import hashlib
import json
import sys
import unittest
from pathlib import Path
from contextlib import closing
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bot.config import settings
from bot.services import control_plane_sync as sync
from db.bootstrap import init_db
from db.database import close_db
from db.queries.servers import create_server
from db.queries.settings import get_setting, set_setting


def snapshot(revision, sources):
    payload = {"revision": revision, "sources": sources}
    payload["checksum"] = hashlib.sha256(json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
    return payload


class ControlSyncGuardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.original = settings.db_path
        await close_db()
        object.__setattr__(settings, "db_path", str(Path(self.temp.name) / "sync.sqlite"))
        await init_db()
        self.source = {"id": "source-1", "name": "Provider", "upstream_base_url": "https://upstream.test", "shopbot_quota_multiple": 1}

    async def asyncTearDown(self):
        await close_db()
        object.__setattr__(settings, "db_path", self.original)
        self.temp.cleanup()

    async def add_server(self, name, url, *, source_id=None, active=1, multiplier=2):
        server_id = await create_server(name, url, "42", "test", 100, 1000, quota_multiple=multiplier, control_plane_source_id=source_id)
        with closing(sqlite3.connect(settings.db_path)) as db, db:
            db.execute("UPDATE api_servers SET is_active = ? WHERE id = ?", (active, server_id))
        return server_id

    def test_portal_multiplier_never_changes_bot_multiplier(self):
        source = {**self.source, "quota_multiple": 4}
        del source["shopbot_quota_multiple"]
        self.assertEqual(sync._server_values(source, {"quota_multiple": 2})["quota_multiple"], 2)
        with self.assertRaisesRegex(ValueError, "separate quota multiplier"):
            sync._server_values(source, None)
        for value in (0, -1, "NaN", "inf", "invalid"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                sync._server_values({**source, "shopbot_quota_multiple": value}, None)
        self.assertEqual(sync._server_values({**source, "shopbot_quota_multiple": 3}, {"quota_multiple": 2})["quota_multiple"], 3)

    async def test_unmapped_conflict_is_rejected_without_db_writes(self):
        await self.add_server("Legacy", "https://upstream.test/v1", active=0)
        with self.assertRaisesRegex(ValueError, "review mapping"):
            await sync.apply_snapshot(snapshot(1, [self.source]))
        with closing(sqlite3.connect(settings.db_path)) as db, db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM api_servers").fetchone()[0], 1)
            self.assertIsNone(db.execute("SELECT value FROM settings WHERE key = ?", (sync.REVISION_KEY,)).fetchone())

    async def test_unrelated_unmapped_server_does_not_block_new_source(self):
        await self.add_server("Unrelated", "https://other.test", active=0)
        self.assertEqual(await sync.apply_snapshot(snapshot(1, [self.source])), 1)
        with closing(sqlite3.connect(settings.db_path)) as db, db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM api_servers").fetchone()[0], 2)

    async def test_update_preserves_disabled_server_and_legacy_multiplier(self):
        await self.add_server("Legacy", "https://upstream.test", source_id="source-1", active=0, multiplier=2)
        source = {**self.source, "quota_multiple": 4}
        del source["shopbot_quota_multiple"]
        self.assertEqual(await sync.apply_snapshot(snapshot(1, [source])), 1)
        with closing(sqlite3.connect(settings.db_path)) as db, db:
            self.assertEqual(db.execute("SELECT name, is_active, quota_multiple FROM api_servers").fetchone(), ("Provider", 0, 2))
            self.assertEqual(db.execute("SELECT value FROM settings WHERE key = ?", (sync.REVISION_KEY,)).fetchone()[0], "1")

    async def test_failed_revision_write_rolls_back_server_update(self):
        await self.add_server("Legacy", "https://upstream.test", source_id="source-1", multiplier=2)
        with closing(sqlite3.connect(settings.db_path)) as db, db:
            db.execute("CREATE TRIGGER fail_revision BEFORE INSERT ON settings WHEN NEW.key = 'control_plane_applied_revision' BEGIN SELECT RAISE(ABORT, 'failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            await sync.apply_snapshot(snapshot(1, [self.source]))
        with closing(sqlite3.connect(settings.db_path)) as db, db:
            self.assertEqual(db.execute("SELECT name, quota_multiple FROM api_servers").fetchone(), ("Legacy", 2))
            self.assertIsNone(db.execute("SELECT value FROM settings WHERE key = ?", (sync.REVISION_KEY,)).fetchone())

    async def test_stale_revision_cannot_overwrite_newer_config(self):
        self.assertEqual(await sync.apply_snapshot(snapshot(2, [self.source])), 2)
        older = {**self.source, "name": "Old snapshot"}
        self.assertEqual(await sync.apply_snapshot(snapshot(1, [older])), 2)
        with closing(sqlite3.connect(settings.db_path)) as db, db:
            self.assertEqual(db.execute("SELECT name FROM api_servers").fetchone()[0], "Provider")

    async def test_checksum_tampering_and_same_revision_change_are_rejected(self):
        original = snapshot(2, [self.source])
        corrupted = {**original, "sources": [{**self.source, "name": "Tampered"}]}
        with self.assertRaisesRegex(ValueError, "checksum is invalid"):
            await sync.apply_snapshot(corrupted)
        self.assertEqual(await sync.apply_snapshot(original), 2)
        self.assertEqual(await sync.apply_snapshot(original), 2)
        with self.assertRaisesRegex(ValueError, "without a new revision"):
            await sync.apply_snapshot(snapshot(2, [{**self.source, "name": "Different"}]))
        with closing(sqlite3.connect(settings.db_path)) as db, db:
            self.assertEqual(db.execute("SELECT name FROM api_servers").fetchone()[0], "Provider")

    async def test_invalid_identity_and_nonfinite_pricing_are_rejected(self):
        for source in ({**self.source, "id": " source-1 "}, {**self.source, "id": 42}, {**self.source, "price_per_unit": "NaN"}):
            with self.subTest(source=source), self.assertRaises(ValueError):
                await sync.apply_snapshot(snapshot(1, [source]))
        with closing(sqlite3.connect(settings.db_path)) as db, db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM api_servers").fetchone()[0], 0)

    async def test_stale_response_is_not_acknowledged_as_healthy(self):
        response = MagicMock(status=200, headers={"ETag": '"old"'})
        response.json = AsyncMock(return_value={"revision": 1, "sources": [], "checksum": "old"})
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=response)
        context.__aexit__ = AsyncMock(return_value=None)
        client = MagicMock()
        client.get.return_value = context
        client.post.return_value = context
        config = SimpleNamespace(platform_admin_url="https://control.test", portal_internal_token="test")
        with patch.object(sync, "settings", config), \
             patch.object(sync, "get_setting", AsyncMock(return_value=None)), \
             patch.object(sync, "set_setting", AsyncMock()) as save, \
             patch.object(sync, "apply_snapshot", AsyncMock(return_value=2)):
            self.assertIsNone(await sync.sync_once(client))
        self.assertNotIn((sync.ETAG_KEY, '"old"'), [call.args for call in save.await_args_list])
        self.assertEqual(client.post.call_args.kwargs["json"]["status"], "degraded")

    async def test_failed_ack_is_retried_and_newer_pending_ack_survives(self):
        await sync.apply_snapshot(snapshot(1, [self.source]))
        first_pending = await get_setting(sync.PENDING_ACK_KEY)
        response = MagicMock()
        response.raise_for_status.side_effect = RuntimeError("temporary failure")
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=response)
        context.__aexit__ = AsyncMock(return_value=None)
        client = MagicMock()
        client.post.return_value = context
        config = SimpleNamespace(platform_admin_url="https://control.test")
        with patch.object(sync, "settings", config):
            with self.assertRaises(RuntimeError):
                await sync._ack_pending(client, {})
            self.assertEqual(await get_setting(sync.PENDING_ACK_KEY), first_pending)
            response.raise_for_status.side_effect = None
            async def newer_config():
                await sync.apply_snapshot(snapshot(2, [{**self.source, "name": "New"}]))
                return response
            context.__aenter__.side_effect = newer_config
            await sync._ack_pending(client, {})
            self.assertNotEqual(await get_setting(sync.PENDING_ACK_KEY), first_pending)
            context.__aenter__.side_effect = None
            await sync._ack_pending(client, {})
            self.assertIsNone(await get_setting(sync.PENDING_ACK_KEY))

    async def test_not_modified_retries_pending_ack(self):
        await set_setting(sync.CHECKSUM_KEY, "a" * 64)
        await set_setting(sync.ETAG_KEY, '"' + "a" * 64 + '"')
        response = MagicMock(status=304)
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=response)
        context.__aexit__ = AsyncMock(return_value=None)
        client = MagicMock()
        client.get.return_value = context
        config = SimpleNamespace(platform_admin_url="https://control.test", portal_internal_token="test")
        with patch.object(sync, "settings", config), \
             patch.object(sync, "_ack_pending", AsyncMock()) as ack:
            self.assertEqual(await sync.sync_once(client), 0)
        ack.assert_awaited_once()

    async def test_legacy_etag_without_checksum_forces_full_snapshot(self):
        await set_setting(sync.ETAG_KEY, '"legacy"')
        response = MagicMock(status=304)
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=response)
        context.__aexit__ = AsyncMock(return_value=None)
        client = MagicMock()
        client.get.return_value = context
        config = SimpleNamespace(platform_admin_url="https://control.test", portal_internal_token="test")
        with patch.object(sync, "settings", config):
            self.assertIsNone(await sync.sync_once(client))
        self.assertNotIn("If-None-Match", client.get.call_args.kwargs["headers"])
        self.assertEqual(await get_setting(sync.STATUS_KEY), "degraded")

    async def test_mismatched_etag_cannot_apply_or_ack_snapshot(self):
        payload = snapshot(1, [self.source])
        response = MagicMock(status=200, headers={"ETag": '"different"'})
        response.json = AsyncMock(return_value=payload)
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=response)
        context.__aexit__ = AsyncMock(return_value=None)
        client = MagicMock()
        client.get.return_value = context
        client.post.return_value = context
        config = SimpleNamespace(platform_admin_url="https://control.test", portal_internal_token="test")
        with patch.object(sync, "settings", config):
            self.assertIsNone(await sync.sync_once(client))
        self.assertIsNone(await get_setting(sync.REVISION_KEY))
        self.assertIsNone(await get_setting(sync.ETAG_KEY))
        with closing(sqlite3.connect(settings.db_path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM api_servers").fetchone()[0], 0)

    async def test_sync_recovers_ack_after_not_modified(self):
        payload = snapshot(1, [self.source])
        first = MagicMock(status=200, headers={"ETag": '"' + payload["checksum"] + '"'})
        first.json = AsyncMock(return_value=payload)
        not_modified = MagicMock(status=304)
        ack_failure = MagicMock()
        ack_failure.raise_for_status.side_effect = RuntimeError("offline")
        ack_success = MagicMock()
        def context(response):
            value = MagicMock()
            value.__aenter__ = AsyncMock(return_value=response)
            value.__aexit__ = AsyncMock(return_value=None)
            return value
        client = MagicMock()
        client.get.side_effect = [context(first), context(not_modified)]
        client.post.side_effect = [context(ack_failure), context(ack_success), context(ack_success)]
        config = SimpleNamespace(platform_admin_url="https://control.test", portal_internal_token="test")
        with patch.object(sync, "settings", config):
            self.assertIsNone(await sync.sync_once(client))
            self.assertIsNotNone(await get_setting(sync.PENDING_ACK_KEY))
            self.assertEqual(await sync.sync_once(client), 1)
            self.assertIsNone(await get_setting(sync.PENDING_ACK_KEY))
        self.assertEqual(client.post.call_args.kwargs["json"]["checksum"], payload["checksum"])


if __name__ == "__main__":
    unittest.main()
