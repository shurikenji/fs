import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.routers.api_keys import KeyUpdateRequest, api_key_update


class KeyUpdateCatalogTests(unittest.IsolatedAsyncioTestCase):
    async def _update(self, catalog, requested, *, hidden=(), pricing=None, catalog_error=None, pricing_error=None):
        server = {"id": "test", "type": "newapi", "auth_token": "configured", "hidden_groups": list(hidden)}
        adapter = AsyncMock()
        adapter.search_token.return_value = {"id": 1, "key": "full-key", "remain_quota": 10}
        adapter.update_token.return_value = {"success": True}
        with (
            patch("app.routers.api_keys.enforce_rate_limit", new_callable=AsyncMock),
            patch("app.routers.api_keys.get_public_server", new_callable=AsyncMock, return_value=server),
            patch("app.routers.api_keys.ensure_server_group_catalog", new_callable=AsyncMock, return_value=catalog, side_effect=catalog_error),
            patch("app.routers.api_keys.fetch_pricing", new_callable=AsyncMock, return_value=pricing, side_effect=pricing_error),
            patch("app.routers.api_keys.build_public_pricing", new_callable=AsyncMock, return_value=pricing),
            patch("app.routers.api_keys.get_adapter", return_value=adapter),
        ):
            result = await api_key_update(
                KeyUpdateRequest(server_id="test", api_key="sk-full-key", groups=[requested]),
                request=None,
            )
        return result, adapter

    async def test_empty_catalog_and_pricing_never_update(self):
        result, adapter = await self._update([], "arbitrary")
        self.assertEqual(result.status_code, 503)
        adapter.search_token.assert_not_awaited()
        adapter.update_token.assert_not_awaited()

    async def test_all_hidden_catalog_never_updates(self):
        result, adapter = await self._update([{"name": "hidden"}], "hidden", hidden=["hidden"])
        self.assertEqual(result.status_code, 503)
        adapter.update_token.assert_not_awaited()

    async def test_unknown_or_hidden_group_is_rejected(self):
        catalog = [{"name": "allowed"}, {"name": "hidden"}]
        for requested in ("hidden", "unknown"):
            with self.subTest(requested=requested):
                result, adapter = await self._update(catalog, requested, hidden=["hidden"])
                self.assertEqual(result.status_code, 400)
                adapter.update_token.assert_not_awaited()

    async def test_visible_group_updates(self):
        result, adapter = await self._update([{"name": "allowed"}], "allowed")
        self.assertTrue(result["success"])
        adapter.update_token.assert_awaited_once()

    async def test_pricing_fallback_cannot_expose_hidden_groups(self):
        pricing = SimpleNamespace(groups=[SimpleNamespace(name="hidden", display_name="Hidden")])
        result, adapter = await self._update([], "hidden", hidden=["hidden"], pricing=pricing)
        self.assertEqual(result.status_code, 503)
        adapter.update_token.assert_not_awaited()

    async def test_lookup_errors_fail_closed(self):
        for options in ({"catalog_error": RuntimeError("failed")}, {"pricing_error": RuntimeError("failed")}):
            with self.subTest(options=options):
                result, adapter = await self._update([], "allowed", **options)
                self.assertEqual(result.status_code, 503)
                adapter.search_token.assert_not_awaited()
                adapter.update_token.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
