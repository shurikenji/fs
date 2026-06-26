import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.app import _shopbot_launch_action_url  # noqa: E402


def _settings(*, shopbot_admin_url: str, public_base_url: str = "https://admin.shupremium.com"):
    return SimpleNamespace(
        shopbot_admin_url=shopbot_admin_url,
        public_base_url=public_base_url,
    )


class ShopbotLaunchUrlTests(unittest.TestCase):
    def test_launch_action_targets_shopbot_sso_consume(self):
        with patch(
            "app.app.get_settings",
            return_value=_settings(shopbot_admin_url="https://shopbot-admin.shupremium.com/"),
        ):
            self.assertEqual(
                _shopbot_launch_action_url(),
                "https://shopbot-admin.shupremium.com/sso/consume",
            )

    def test_launch_action_rejects_public_base_url_root(self):
        with patch(
            "app.app.get_settings",
            return_value=_settings(shopbot_admin_url="https://admin.shupremium.com"),
        ):
            with self.assertRaisesRegex(RuntimeError, "points back to PUBLIC_BASE_URL"):
                _shopbot_launch_action_url()

    def test_launch_action_allows_same_origin_with_explicit_proxy_path(self):
        with patch(
            "app.app.get_settings",
            return_value=_settings(shopbot_admin_url="https://admin.shupremium.com/shopbot"),
        ):
            self.assertEqual(
                _shopbot_launch_action_url(),
                "https://admin.shupremium.com/shopbot/sso/consume",
            )

    def test_launch_action_requires_browser_accessible_absolute_url(self):
        with patch(
            "app.app.get_settings",
            return_value=_settings(shopbot_admin_url="/shopbot"),
        ):
            with self.assertRaisesRegex(RuntimeError, "absolute browser-accessible"):
                _shopbot_launch_action_url()


if __name__ == "__main__":
    unittest.main()
