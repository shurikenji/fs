import unittest

from app.server_profile_registry import (
    get_default_endpoint_alias_map,
    get_known_server_profile,
)
from app.server_profiles import resolve_server_profile


class ServerProfileRegistryTests(unittest.TestCase):
    def test_known_profile_lookup_returns_normalized_copy(self) -> None:
        known = get_known_server_profile("gpt2")
        self.assertEqual(
            known,
            {
                "parser_id": "rixapi_inline",
                "display_profile": "flat",
                "variant_pricing_mode": "",
            },
        )

        known["parser_id"] = "changed"
        fresh = get_known_server_profile("gpt2")
        self.assertEqual(fresh["parser_id"], "rixapi_inline")

    def test_default_alias_map_returns_copy(self) -> None:
        aliases = get_default_endpoint_alias_map()
        self.assertEqual(aliases["openai"]["public_path"], "/v1/chat/completions")

        aliases["openai"]["public_path"] = "/mutated"
        fresh = get_default_endpoint_alias_map()
        self.assertEqual(fresh["openai"]["public_path"], "/v1/chat/completions")

    def test_explicit_aliases_override_registry_defaults(self) -> None:
        profile = resolve_server_profile(
            {
                "id": "gpt1",
                "type": "newapi",
                "endpoint_aliases_json": '{"openai":{"label":"Custom OpenAI","public_path":"/custom","method":"get"}}',
            }
        )
        self.assertEqual(profile["endpoint_alias_map"]["openai"]["label"], "Custom OpenAI")
        self.assertEqual(profile["endpoint_alias_map"]["openai"]["public_path"], "/custom")
        self.assertEqual(profile["endpoint_alias_map"]["openai"]["method"], "GET")
