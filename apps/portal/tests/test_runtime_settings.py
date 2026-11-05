import unittest
from types import SimpleNamespace
from unittest.mock import patch

from main import main, validate_runtime_settings


class RuntimeSettingsTests(unittest.TestCase):
    def test_rejects_defaults_and_requires_control_token_only_for_sync(self):
        valid = {"admin_secret": "test-secret", "pricing_admin_token": "test-token", "control_plane_token": "", "control_plane_sync_enabled": False}
        validate_runtime_settings(SimpleNamespace(**valid))
        for name, value in (("admin_secret", "change-me-to-a-strong-secret"), ("pricing_admin_token", "")):
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                validate_runtime_settings(SimpleNamespace(**{**valid, name: value}))
        with self.assertRaises(RuntimeError):
            validate_runtime_settings(SimpleNamespace(**{**valid, "control_plane_sync_enabled": True}))
        validate_runtime_settings(SimpleNamespace(**{**valid, "control_plane_sync_enabled": True, "control_plane_token": "test-control-token"}))

    def test_server_does_not_start_with_default_credentials(self):
        settings = SimpleNamespace(control_plane_sync_enabled=False, admin_secret="change-me", pricing_admin_token="test")
        with patch("main.get_settings", return_value=settings), patch("main.uvicorn.run") as run:
            with self.assertRaises(RuntimeError):
                main()
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
