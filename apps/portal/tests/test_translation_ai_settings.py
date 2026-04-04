import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.translation_ai_settings import get_runtime_ai_settings


class TranslationAiSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_env_defaults_when_db_has_no_override(self) -> None:
        env_settings = SimpleNamespace(
            ai_provider="openai",
            ai_api_key="env-key",
            ai_model="gpt-4o-mini",
            ai_base_url="",
            ai_enabled=False,
        )

        with (
            patch("app.translation_ai_settings.get_settings", return_value=env_settings),
            patch(
                "app.translation_ai_settings.get_settings_dict",
                AsyncMock(side_effect=lambda defaults: dict(defaults)),
            ),
        ):
            settings = await get_runtime_ai_settings()

        self.assertEqual(settings["provider"], "openai")
        self.assertEqual(settings["api_key"], "env-key")
        self.assertEqual(settings["model"], "gpt-4o-mini")
        self.assertEqual(settings["base_url"], "")
        self.assertFalse(settings["enabled"])

    async def test_db_overrides_are_trimmed_and_normalized(self) -> None:
        env_settings = SimpleNamespace(
            ai_provider="openai",
            ai_api_key="env-key",
            ai_model="gpt-4o-mini",
            ai_base_url="https://env.test",
            ai_enabled=False,
        )

        with (
            patch("app.translation_ai_settings.get_settings", return_value=env_settings),
            patch(
                "app.translation_ai_settings.get_settings_dict",
                AsyncMock(
                    return_value={
                        "ai_provider": " OpenAI_Compatible ",
                        "ai_api_key": " db-key ",
                        "ai_model": " custom-model ",
                        "ai_base_url": " https://db.test ",
                        "ai_enabled": "TRUE",
                    }
                ),
            ),
        ):
            settings = await get_runtime_ai_settings()

        self.assertEqual(settings["provider"], "openai_compatible")
        self.assertEqual(settings["api_key"], "db-key")
        self.assertEqual(settings["model"], "custom-model")
        self.assertEqual(settings["base_url"], "https://db.test")
        self.assertTrue(settings["enabled"])
