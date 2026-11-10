"""Shopbot owns commerce policy even when its connection comes from Control."""
import hashlib
import json
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from admin.routers.servers import servers_edit_submit, servers_toggle_active
from bot.config import settings
from bot.services.control_plane_sync import apply_snapshot
from bot.services.pricing_resolver import quote_api_order
from bot.services.spend_ledger import SpendLedgerService
from db.bootstrap import init_db
from db.database import close_db
from db.queries.pricing import get_server_discount_tiers, list_server_pricing_versions, sync_server_pricing_version
from db.queries.servers import create_server, get_all_servers, get_server_by_id
from db.queries.users import create_user


class FormControls(HTMLParser):
    def __init__(self):
        super().__init__()
        self.fieldsets = []
        self.disabled = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "fieldset":
            self.fieldsets.append("disabled" in attrs)
        if tag in {"input", "select", "textarea"} and "name" in attrs:
            self.disabled[attrs["name"]] = "disabled" in attrs or any(self.fieldsets)

    def handle_endtag(self, tag):
        if tag == "fieldset":
            self.fieldsets.pop()


def snapshot(revision, source):
    payload = {"revision": revision, "sources": [source]}
    payload["checksum"] = hashlib.sha256(json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str,
    ).encode()).hexdigest()
    return payload


class LocalPricingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.original = settings.db_path
        await close_db()
        object.__setattr__(settings, "db_path", str(Path(self.temp.name) / "local.sqlite"))
        await init_db()
        self.source = {
            "id": "api1", "name": "API1", "upstream_base_url": "https://provider.test",
            "public_base_url": "https://proxy.test", "auth_token": "central-token",
            "price_per_unit": 1, "quota_per_unit": 123, "dollar_per_unit": 10,
            "shopbot_quota_multiple": 99, "quota_multiple": 42,
            "default_group": "central", "manual_groups": "central",
            "supports_group_chain": 0, "import_spend_accrual_enabled": 0,
            "discount_stack_mode": "exclusive", "discount_allowed_stack_types": "fixed_off",
        }
        self.form = {
            "price_per_unit": "7200", "quota_per_unit": "500000",
            "dollar_per_unit": "1", "quota_multiple": "0.9",
            "default_group": "premium", "manual_groups": "premium,default",
            "supports_multi_group": "1", "import_spend_accrual_enabled": "1",
            "discount_stack_mode": "combine_selected_types",
            "discount_allowed_stack_types": "percent_off,cashback", "is_active": "1",
            "discount_tiers_json": json.dumps([{
                "name": "VIP", "min_spend_vnd": 100000,
                "benefits": [{"type": "percent_off", "value": 10}, {"type": "cashback", "value": 5}],
            }]),
        }

    async def asyncTearDown(self):
        await close_db()
        object.__setattr__(settings, "db_path", self.original)
        self.temp.cleanup()

    async def test_local_price_and_tiers_survive_sync_and_drive_quotes(self):
        server_id = await create_server(
            "Old API1", "https://old.test", "19", "old-token", 4100, 500000,
            dollar_per_unit=1, quota_multiple=0.5, control_plane_source_id="api1",
        )
        await sync_server_pricing_version(server_id)
        request = SimpleNamespace(form=AsyncMock(return_value={
            **self.form, "base_url": "https://tampered.test", "auth_token": "tampered",
            "name": "Tampered", "api_type": "rixapi",
        }))
        response = await servers_edit_submit(request, server_id)
        self.assertEqual(response.headers["location"], "/servers")
        versions = await list_server_pricing_versions(server_id)
        self.assertEqual(len(versions), 2)
        tier_id = (await get_server_discount_tiers(server_id))[0]["id"]
        await apply_snapshot(snapshot(1, self.source))
        await apply_snapshot(snapshot(2, {**self.source, "name": "API1 updated"}))
        server = await get_server_by_id(server_id)
        self.assertEqual(server["name"], "API1 updated")
        self.assertEqual(server["base_url"], "https://provider.test")
        self.assertEqual(server["auth_token"], "central-token")
        self.assertEqual(server["api_type"], "newapi")
        for key in ("price_per_unit", "quota_per_unit", "dollar_per_unit", "quota_multiple"):
            self.assertEqual(float(server[key]), float(self.form[key]))
        self.assertEqual(server["default_group"], "premium")
        self.assertEqual(server["manual_groups"], "premium,default")
        self.assertEqual(server["supports_multi_group"], 1)
        self.assertEqual(server["import_spend_accrual_enabled"], 1)
        self.assertEqual(server["discount_stack_mode"], "combine_selected_types")
        self.assertEqual(server["discount_allowed_stack_types"], "percent_off,cashback")
        self.assertEqual(server["is_active"], 1)
        self.assertEqual(await list_server_pricing_versions(server_id), versions)
        self.assertEqual((await get_server_discount_tiers(server_id))[0]["id"], tier_id)
        user = await create_user(telegram_id=910001, username="local_pricing", full_name="Local Pricing")
        await SpendLedgerService.record(user_id=user["id"], server_id=server_id,
            source_type="verification", source_ref="vip", amount=100000)
        quote = await quote_api_order(user_id=user["id"], server=server, custom_dollar=10)
        self.assertEqual((quote.base_amount, quote.payable_amount, quote.cashback_amount), (72000, 64800, 3240))
        self.assertEqual(quote.quota_amount, 4500000)
        self.assertEqual(quote.pricing_version_id, versions[0]["id"])

    async def test_new_source_waits_for_local_price_and_can_be_toggled(self):
        await apply_snapshot(snapshot(1, self.source))
        server = (await get_all_servers())[0]
        self.assertEqual((server["is_active"], server["price_per_unit"], server["quota_multiple"]), (0, 0, 1))
        request = SimpleNamespace(form=AsyncMock(return_value={}), headers={})
        response = await servers_toggle_active(request, server["id"])
        self.assertIn("invalid_pricing", response.headers["location"])
        request.form.return_value = self.form
        await servers_edit_submit(request, server["id"])
        request.form.return_value = {}
        await servers_toggle_active(request, server["id"])
        self.assertEqual((await get_server_by_id(server["id"]))["is_active"], 0)
        await apply_snapshot(snapshot(2, self.source))
        self.assertEqual((await get_server_by_id(server["id"]))["is_active"], 0)
        await servers_toggle_active(request, server["id"])
        self.assertEqual((await get_server_by_id(server["id"]))["is_active"], 1)

    async def test_invalid_local_price_cannot_write_or_activate_source(self):
        await apply_snapshot(snapshot(1, self.source))
        server = (await get_all_servers())[0]
        for key, value in (("price_per_unit", "-1"), ("price_per_unit", "0"),
                           ("quota_per_unit", "0"), ("quota_multiple", "nan"),
                           ("quota_multiple", "-1"), ("dollar_per_unit", "inf")):
            with self.subTest(key=key, value=value):
                request = SimpleNamespace(form=AsyncMock(return_value={**self.form, key: value}))
                response = await servers_edit_submit(request, server["id"])
                self.assertIn("invalid_pricing", response.headers["location"])
                self.assertEqual(await get_server_by_id(server["id"]), server)
                self.assertEqual(await get_server_discount_tiers(server["id"]), [])
                self.assertEqual(await list_server_pricing_versions(server["id"]), [])

    async def test_managed_modal_can_submit_commerce_settings(self):
        from admin.app import create_admin_app
        from admin.deps import require_admin, verify_csrf

        await apply_snapshot(snapshot(1, self.source))
        server = (await get_all_servers())[0]
        app = create_admin_app()
        app.dependency_overrides[require_admin] = lambda: {"admin": True}
        app.dependency_overrides[verify_csrf] = lambda: None
        with TestClient(app) as client:
            response = client.get(f"/servers/{server['id']}/edit-modal")
            self.assertEqual(response.status_code, 200)
            controls = FormControls()
            controls.feed(response.text)
            for name in ("name", "base_url", "api_type", "auth_token", "groups_endpoint"):
                self.assertTrue(controls.disabled[name], name)
            for name in (*self.form,):
                self.assertFalse(controls.disabled[name], name)
            response = client.post(f"/servers/{server['id']}/edit", data=self.form, follow_redirects=False)
            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers["location"], "/servers")
            page = client.get("/servers")
            self.assertEqual(page.status_code, 200)
            self.assertIn("Pricing managed here", page.text)
        self.assertEqual((await get_server_by_id(server["id"]))["price_per_unit"], 7200)


if __name__ == "__main__":
    unittest.main()
