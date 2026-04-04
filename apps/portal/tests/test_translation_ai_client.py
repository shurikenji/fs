import unittest
from unittest.mock import AsyncMock, patch

from app.translation_ai_client import request_ai_completion, resolve_openai_endpoint


class TranslationAiClientTests(unittest.IsolatedAsyncioTestCase):
    def test_resolve_openai_endpoint_normalizes_variants(self) -> None:
        self.assertEqual(
            resolve_openai_endpoint("", compatible_only=False),
            "https://api.openai.com/v1/chat/completions",
        )
        self.assertEqual(
            resolve_openai_endpoint("https://example.test/v1", compatible_only=False),
            "https://example.test/v1/chat/completions",
        )
        self.assertEqual(
            resolve_openai_endpoint("https://example.test/chat/completions", compatible_only=True),
            "https://example.test/chat/completions",
        )
        self.assertEqual(
            resolve_openai_endpoint("https://example.test", compatible_only=True),
            "https://example.test/v1/chat/completions",
        )

    async def test_request_dispatches_to_anthropic(self) -> None:
        with patch(
            "app.translation_ai_client.call_anthropic",
            AsyncMock(return_value="ok"),
        ) as anthropic_mock:
            result = await request_ai_completion(
                "anthropic",
                "sys",
                "user",
                api_key="key",
                model="claude",
            )

        self.assertEqual(result, "ok")
        anthropic_mock.assert_awaited_once_with("sys", "user", api_key="key", model="claude")

    async def test_request_dispatches_to_gemini(self) -> None:
        with patch(
            "app.translation_ai_client.call_gemini",
            AsyncMock(return_value="ok"),
        ) as gemini_mock:
            result = await request_ai_completion(
                "gemini",
                "sys",
                "user",
                api_key="key",
                model="1.5-pro",
            )

        self.assertEqual(result, "ok")
        gemini_mock.assert_awaited_once_with("sys", "user", api_key="key", model="1.5-pro")

    async def test_request_dispatches_to_openai_with_resolved_endpoint(self) -> None:
        with patch(
            "app.translation_ai_client.call_openai_chat",
            AsyncMock(return_value="ok"),
        ) as openai_mock:
            result = await request_ai_completion(
                "openai_compatible",
                "sys",
                "user",
                api_key="key",
                model="gpt-4o-mini",
                base_url="https://example.test",
                compatible_only=True,
            )

        self.assertEqual(result, "ok")
        openai_mock.assert_awaited_once_with(
            "sys",
            "user",
            api_key="key",
            model="gpt-4o-mini",
            endpoint="https://example.test/v1/chat/completions",
        )
