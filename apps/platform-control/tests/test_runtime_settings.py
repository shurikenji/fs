import unittest
from types import SimpleNamespace
from unittest.mock import patch

from main import main, validate_runtime_settings


class RuntimeSettingsTests(unittest.TestCase):
    def test_rejects_missing_or_default_credentials(self):
        fields = ("admin_secret", "admin_password", "control_plane_token", "proxy_operator_token", "pricing_admin_token", "shopbot_launch_secret")
        valid = {name: "unique-test-value" for name in fields}
        validate_runtime_settings(SimpleNamespace(**valid))
        for name in fields:
            for bad in ("", "  ", "CHANGE-ME"):
                with self.subTest(name=name, bad=bad), self.assertRaises(RuntimeError):
                    validate_runtime_settings(SimpleNamespace(**{**valid, name: bad}))

    def test_server_does_not_start_with_default_credentials(self):
        with patch("main.get_settings", return_value=SimpleNamespace(admin_secret="change-me")), \
             patch("main.uvicorn.run") as run:
            with self.assertRaises(RuntimeError):
                main()
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
