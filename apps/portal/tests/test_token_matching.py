import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.adapters.base import match_token_from_items
from app.adapters.newapi import NewApiAdapter


class TokenMatchingTests(unittest.TestCase):
    def test_only_complete_matching_keys_are_accepted(self):
        item = {"id": 1, "key": "full-key"}
        self.assertIs(match_token_from_items([item], "sk-full-key"), item)
        self.assertEqual(match_token_from_items([{"key": "sk-full-key"}], "full-key")["key"], "sk-full-key")
        for key in ("other-key", "full***key", "full...key", "full…key", "", None):
            with self.subTest(key=key):
                self.assertIsNone(match_token_from_items([{"key": key}], "sk-full-key"))
        self.assertIsNone(match_token_from_items([{}], ""))
        self.assertIsNone(match_token_from_items([{"key": "sk-key***"}], "sk-key***"))


class TokenSearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_masked_single_result_does_not_resolve_another_key(self):
        response = MagicMock()
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=False)
        response.json = AsyncMock(return_value={"success": True, "data": [{"id": 1, "key": "full***key"}]})
        session = MagicMock()
        session.get.return_value = response
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        with patch("app.adapters.base.aiohttp.ClientSession", return_value=session):
            result = await NewApiAdapter().search_token({"base_url": "https://example.test"}, "sk-other-key")
        self.assertIsNone(result)
        self.assertGreaterEqual(session.get.call_count, 1)


if __name__ == "__main__":
    unittest.main()
