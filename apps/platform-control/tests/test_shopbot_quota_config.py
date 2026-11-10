"""Keep Portal pricing and Shopbot fulfillment multipliers independent."""
import unittest
from unittest.mock import AsyncMock, patch

import aiosqlite
from fastapi.testclient import TestClient

from app.app import create_app
from db.database import _ensure_schema
from db.models import CREATE_TABLES
from db.queries import get_key_vault_config_snapshot, get_shopbot_config_snapshot, record_consumer_sync_status, set_consumer_desired_checksum


class ShopbotQuotaConfigTests(unittest.IsolatedAsyncioTestCase):
    async def test_upgrade_and_snapshot_keep_legacy_unset(self):
        async with aiosqlite.connect(":memory:") as db:
            db.row_factory = aiosqlite.Row
            legacy = CREATE_TABLES.replace("    quota_multiple                 REAL,\n", "")
            await db.executescript(legacy)
            await db.execute("INSERT INTO service_sources (id, name, upstream_base_url, quota_multiple) VALUES ('s', 'Source', 'https://example.test', 4)")
            await db.execute("INSERT INTO shopbot_source_profiles (source_id) VALUES ('s')")
            await _ensure_schema(db)
            await _ensure_schema(db)
            with patch("db.queries.get_db", new=AsyncMock(return_value=db)):
                source = (await get_shopbot_config_snapshot())["sources"][0]
                self.assertEqual(source["quota_multiple"], 4)
                self.assertIsNone(source["shopbot_quota_multiple"])
                await db.execute("UPDATE shopbot_source_profiles SET quota_multiple = 2 WHERE source_id = 's'")
                source = (await get_shopbot_config_snapshot())["sources"][0]
                self.assertEqual(source["quota_multiple"], 4)
                self.assertEqual(source["shopbot_quota_multiple"], 2)
                await db.execute("UPDATE shopbot_source_profiles SET supports_key_lookup_by_id = 1, key_backup_enabled = 1 WHERE source_id = 's'")
                vault_source = (await get_key_vault_config_snapshot())["sources"][0]
                self.assertEqual(vault_source["supports_key_lookup_by_id"], 1)

    async def test_ack_only_marks_desired_checksum_as_applied(self):
        async with aiosqlite.connect(":memory:") as db:
            await db.executescript(CREATE_TABLES)
            await db.execute("INSERT INTO consumer_sync_state (consumer_id, desired_revision, desired_checksum, applied_revision, applied_checksum, status) VALUES ('shopbot', 2, 'new', 1, 'old', 'pending')")
            with patch("db.queries.get_db", new=AsyncMock(return_value=db)):
                for revision, status, checksum in ((1, "healthy", "old"), (2, "healthy", "wrong"), (1, "degraded", "")):
                    await record_consumer_sync_status("shopbot", revision, status, "error", checksum)
                row = await (await db.execute("SELECT applied_revision, applied_checksum, status FROM consumer_sync_state")).fetchone()
                self.assertEqual(tuple(row), (1, "old", "pending"))
                await record_consumer_sync_status("shopbot", 2, "degraded", "unavailable")
                row = await (await db.execute("SELECT applied_revision, applied_checksum, status FROM consumer_sync_state")).fetchone()
                self.assertEqual(tuple(row), (1, "old", "degraded"))
                await record_consumer_sync_status("shopbot", 2, "healthy", checksum="new")
                row = await (await db.execute("SELECT applied_revision, applied_checksum, status FROM consumer_sync_state")).fetchone()
                self.assertEqual(tuple(row), (2, "new", "healthy"))

    async def test_first_desired_checksum_creates_state_and_stale_snapshot_cannot_replace_it(self):
        async with aiosqlite.connect(":memory:") as db:
            await db.executescript(CREATE_TABLES)
            await db.execute("INSERT INTO config_state (id, revision) VALUES (1, 2)")
            with patch("db.queries.get_db", new=AsyncMock(return_value=db)):
                await set_consumer_desired_checksum("shopbot", 2, "new")
                await set_consumer_desired_checksum("shopbot", 1, "old")
                row = await (await db.execute("SELECT desired_revision, desired_checksum, status FROM consumer_sync_state")).fetchone()
                self.assertEqual(tuple(row), (2, "new", "pending"))
                await record_consumer_sync_status("shopbot", 2, "healthy", checksum="new")
                row = await (await db.execute("SELECT applied_revision, applied_checksum, status FROM consumer_sync_state")).fetchone()
                self.assertEqual(tuple(row), (2, "new", "healthy"))


class ShopbotQuotaSaveTests(unittest.TestCase):
    def test_central_save_does_not_write_shopbot_pricing(self):
        data = {
            "source_id": "s", "name": "Source", "upstream_base_url": "https://example.test", "shopbot_enabled": "on",
            "shopbot_price_per_unit": "9999", "shopbot_quota_per_unit": "123",
            "shopbot_dollar_per_unit": "7", "shopbot_default_group": "old",
            "shopbot_import_spend_accrual_enabled": "on", "shopbot_discount_stack_mode": "combine_selected_types",
            "shopbot_discount_allowed_stack_types": "percent_off,cashback",
        }
        with (
            patch("app.app._require_admin_post", new=AsyncMock(return_value=None)),
            patch("app.app.get_service_source", new=AsyncMock(return_value={})),
            patch("app.app.upsert_service_source", new=AsyncMock()) as source_save,
            patch("app.app.upsert_shopbot_source_profile", new=AsyncMock()) as profile_save,
            patch("app.app.create_activity_log", new=AsyncMock()),
            patch("app.app.pricing_import_control_plane", new=AsyncMock(return_value={})),
        ):
            client = TestClient(create_app())
            for value in ("0", "-1", "nan", "inf", "", "2.5"):
                response = client.post("/control/service-sources/save", data={**data, "shopbot_quota_multiple": value}, follow_redirects=False)
                self.assertEqual(response.status_code, 303)
                self.assertEqual(set(profile_save.await_args.kwargs), {
                    "supports_key_lookup_by_id", "token_key_endpoint_template", "key_backup_enabled",
                })
            self.assertEqual(source_save.await_count, 6)


if __name__ == "__main__":
    unittest.main()
