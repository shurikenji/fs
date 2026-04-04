import json
import unittest
from pathlib import Path

from app.adapters.newapi import NewApiAdapter
from app.adapters.rixapi import RixApiAdapter
from app.cache import _apply_server_multiple
from app.sanitizer import sanitize_pricing
from app.schemas import EndpointAlias, NormalizedModel, NormalizedPricing, PricingMode
from app.server_profiles import describe_server_profile, resolve_server_profile


_FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((_FIXTURE_DIR / name).read_text(encoding="utf-8"))


class ServerSpecificPricingTests(unittest.TestCase):
    def test_known_server_profiles_follow_expected_defaults(self) -> None:
        self.assertEqual(describe_server_profile({"id": "gpt2", "type": "rixapi"})["parser_id"], "rixapi_inline")
        self.assertEqual(describe_server_profile({"id": "gpt1", "type": "newapi"})["parser_id"], "newapi_standard")
        self.assertEqual(describe_server_profile({"id": "sv1", "type": "newapi"})["parser_id"], "newapi_standard")

    def test_cached_snapshot_can_upgrade_profile_to_yunwu_shape(self) -> None:
        server = {
            "id": "gpt1",
            "type": "newapi",
            "pricing_cache": json.dumps(_load_fixture("yunwu_pricing_new.json")),
        }
        profile = describe_server_profile(server)
        self.assertEqual(profile["parser_id"], "yunwu_pricing_new")
        self.assertEqual(profile["display_profile"], "flat")

    def test_newapi_fixture_stays_flat(self) -> None:
        adapter = NewApiAdapter()
        pricing = adapter._normalize({"id": "gpt1", "name": "GPT1", "type": "newapi"}, _load_fixture("newapi_standard.json"), {})

        self.assertEqual(len(pricing.models), 1)
        model = pricing.models[0]
        self.assertEqual(model.model_name, "gpt-4o-mini")
        self.assertEqual(model.display_mode, "flat")
        self.assertEqual(model.pricing_variants, [])
        self.assertEqual(model.supported_endpoints, ["/v1/chat/completions"])

    def test_rixapi_fixture_stays_flat(self) -> None:
        adapter = RixApiAdapter()
        pricing = adapter._normalize({"id": "gpt2", "name": "GPT2", "type": "rixapi"}, _load_fixture("rixapi_inline.json"), {})

        self.assertEqual(len(pricing.groups), 1)
        self.assertEqual(pricing.groups[0].name, "default")
        model = pricing.models[0]
        self.assertEqual(model.display_mode, "flat")
        self.assertEqual(model.supported_endpoints, ["/v1/messages"])
        self.assertEqual(model.pricing_mode, PricingMode.token)

    def test_yunwu_fixture_builds_public_safe_flat_model(self) -> None:
        adapter = NewApiAdapter()
        pricing = adapter._normalize({"id": "sv1", "name": "SV1", "type": "newapi"}, _load_fixture("yunwu_pricing_new.json"), {})

        model = pricing.models[0]
        self.assertEqual(model.vendor_name, "AIGC")
        self.assertEqual(model.display_mode, "flat")
        self.assertEqual(model.supported_endpoints, ["/tencent-vod/v1/aigc-image"])
        self.assertEqual(len(model.pricing_variants), 0)
        self.assertEqual(model.billing_label, "Per image")
        self.assertEqual(model.billing_unit, "image")
        self.assertEqual(model.price_multiplier, 30.0)
        self.assertEqual(model.request_price, 0.51)
        self.assertEqual(model.group_prices["default"].request_price, 0.51)
        self.assertEqual(model.endpoint_aliases[0].public_path, "/tencent-vod/v1/aigc-image")
        self.assertEqual(model.endpoint_aliases[0].method, "POST")

    def test_quota_multiple_scaling_applies_to_matrix_variants(self) -> None:
        adapter = NewApiAdapter()
        pricing = adapter._normalize({"id": "sv1", "name": "SV1", "type": "newapi"}, _load_fixture("yunwu_pricing_new.json"), {})

        scaled = _apply_server_multiple(pricing, {"quota_multiple": 0.5})
        model = scaled.models[0]

        self.assertEqual(model.request_price, 1.02)
        self.assertEqual(model.group_prices["default"].group_ratio, 2.0)
        self.assertEqual(model.pricing_variants, [])

    def test_public_sanitizer_keeps_endpoint_paths_without_hosts(self) -> None:
        pricing = NormalizedPricing(
            server_id="sv1",
            server_name="SV1",
            models=[
                NormalizedModel(
                    model_name="demo",
                    pricing_mode=PricingMode.fixed,
                    request_price=1.0,
                    supported_endpoints=["/tencent-vod/v1/aigc-image", "aigc-image"],
                    endpoint_aliases=[
                        EndpointAlias(
                            key="aigc-image",
                            label="AIGC Image",
                            method="POST",
                            public_path="/tencent-vod/v1/aigc-image",
                        )
                    ],
                )
            ],
            groups=[],
            fetched_at="2026-04-04T00:00:00Z",
        )

        sanitized = sanitize_pricing(pricing)
        model = sanitized.models[0]
        self.assertEqual(model.supported_endpoints, ["/tencent-vod/v1/aigc-image", "aigc-image"])
        self.assertEqual(model.endpoint_aliases[0].public_path, "/tencent-vod/v1/aigc-image")

    def test_yunwu_quota4_uses_time_multiplier(self) -> None:
        adapter = NewApiAdapter()
        payload = {
            "success": True,
            "group_ratio": {"default": 1.0, "pro": 2.0},
            "usable_group": {"default": "Default", "pro": "Pro"},
            "supported_endpoint": {
                "aigc-video": {
                    "path": "/tencent-vod/v1/aigc-video",
                    "method": "POST",
                }
            },
            "vendors": [],
            "data": [
                {
                    "model_name": "kling-motion-control",
                    "description": "Timed video editing",
                    "quota_type": 4,
                    "model_price": 0.01,
                    "model_ratio": 0,
                    "completion_ratio": 0,
                    "enable_groups": ["default", "pro"],
                    "supported_endpoint_types": ["aigc-video"],
                }
            ],
        }

        pricing = adapter._normalize({"id": "sv1", "name": "SV1", "type": "newapi"}, payload, {})
        model = pricing.models[0]
        self.assertEqual(model.billing_label, "Per second")
        self.assertEqual(model.billing_unit, "s")
        self.assertEqual(model.price_multiplier, 50.0)
        self.assertEqual(model.request_price, 0.5)
        self.assertEqual(model.group_prices["pro"].request_price, 1.0)
        self.assertEqual(model.supported_endpoints, ["/tencent-vod/v1/aigc-video"])

    def test_payload_fingerprint_can_upgrade_newapi_type_to_yunwu_profile(self) -> None:
        profile = resolve_server_profile({"id": "custom-sv", "type": "newapi"}, _load_fixture("yunwu_pricing_new.json"))
        self.assertEqual(profile["parser_id"], "yunwu_pricing_new")


if __name__ == "__main__":
    unittest.main()
