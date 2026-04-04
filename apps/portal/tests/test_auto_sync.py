import unittest

from app.auto_sync import AutoSyncSettings, parse_auto_sync_settings


class ParseAutoSyncSettingsTests(unittest.TestCase):
    def test_uses_defaults(self) -> None:
        self.assertEqual(parse_auto_sync_settings(), AutoSyncSettings(enabled=False, interval_minutes=15))

    def test_normalizes_values(self) -> None:
        settings = parse_auto_sync_settings(
            {
                "auto_sync_enabled": "true",
                "auto_sync_interval_minutes": "3",
            }
        )
        self.assertEqual(settings, AutoSyncSettings(enabled=True, interval_minutes=3))

    def test_clamps_invalid_interval(self) -> None:
        settings = parse_auto_sync_settings(
            {
                "auto_sync_enabled": "true",
                "auto_sync_interval_minutes": "0",
            }
        )
        self.assertEqual(settings, AutoSyncSettings(enabled=True, interval_minutes=1))
