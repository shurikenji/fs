"""Verify masked search results against full keys returned by the upstream."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from bot.services.api_clients.newapi import NewAPIClient


def response(payload):
    result = MagicMock()
    result.__aenter__ = AsyncMock(return_value=result)
    result.__aexit__ = AsyncMock(return_value=False)
    result.json = AsyncMock(return_value=payload)
    return result


class TokenIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def test_masked_search_result_requires_matching_key_from_id_endpoint(self):
        server = {
            "name": "test",
            "base_url": "https://example.test",
            "supports_key_lookup_by_id": 1,
        }
        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.get.return_value = response({"success": True, "data": [{"id": 7, "key": "abc***xyz"}]})
        full_key_response = response({"success": True, "data": {"key": "abcdefxyz"}})
        session.post.return_value = full_key_response

        with patch("bot.services.api_clients.base.aiohttp.ClientSession", return_value=session):
            client = NewAPIClient()
            self.assertEqual((await client.search_token(server, "sk-abcdefxyz"))["id"], 7)
            self.assertEqual(session.post.call_args.args[0], "https://example.test/api/token/7/key")
            session.post.reset_mock()
            self.assertIsNone(await client.search_token(server, "sk-anotherkey"))
            self.assertEqual(session.post.call_count, 1)
            session.post.reset_mock()
            self.assertIsNone(await client.search_token({**server, "supports_key_lookup_by_id": 0}, "sk-abcdefxyz"))
            session.post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
