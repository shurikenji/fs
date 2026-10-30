import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.proxy_routes import connection_profiles, effective_prefixes, normalize_prefix  # noqa: E402


class ProxyRouteTests(unittest.TestCase):
    def test_presets_and_custom_prefixes_are_deduplicated(self):
        self.assertEqual(
            effective_prefixes(["openai_compatible", "gemini_openai_compatible"], ["/vendor/", "/v1/"]),
            ["/v1/", "/v1beta/openai/", "/vendor/"],
        )

    def test_reserved_and_unsafe_prefixes_are_rejected(self):
        for prefix in ("/", "/_internal/health", "/admin/../", "/api/?secret=1", "/bad;directive", "/vendor/(.*)"):
            with self.assertRaises(ValueError):
                normalize_prefix(prefix)

    def test_connection_profiles_only_include_enabled_protocols(self):
        profiles = connection_profiles(
            "gemini.example.com",
            {
                "presets": ["gemini_native", "gemini_openai_compatible"],
                "custom_prefixes": ["/vendor/custom/"],
            },
        )
        self.assertEqual(
            profiles,
            [
                {"protocol": "gemini_native", "base_url": "https://gemini.example.com"},
                {"protocol": "gemini_openai", "base_url": "https://gemini.example.com/v1beta/openai"},
                {"protocol": "custom", "base_url": "https://gemini.example.com/vendor/custom"},
            ],
        )


if __name__ == "__main__":
    unittest.main()
