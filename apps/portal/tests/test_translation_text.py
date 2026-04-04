import unittest

from app.schemas import NormalizedModel, NormalizedPricing
from app.translation_text import (
    apply_model_description_translation_map,
    apply_model_label_translation_maps,
    build_fallback_text_translations,
    collect_model_description_payloads,
    collect_model_tag_payloads,
    collect_vendor_label_payloads,
    needs_text_translation_refresh,
)


def _sample_pricing() -> NormalizedPricing:
    return NormalizedPricing(
        server_id="server-1",
        server_name="Server 1",
        models=[
            NormalizedModel(
                model_name="alpha",
                description="中文说明",
                vendor_name="阿里云",
                tags=["视频模型", "video", "视频模型"],
            ),
            NormalizedModel(
                model_name="beta",
                description="English description",
                vendor_name="OpenAI",
                tags=["chat"],
            ),
            NormalizedModel(
                model_name="gamma",
                description="中文说明",
                vendor_name="阿里云",
                tags=["图像模型"],
            ),
        ],
        groups=[],
        fetched_at="2026-04-05T00:00:00Z",
    )


class TranslationTextTests(unittest.TestCase):
    def test_collectors_only_emit_unique_cjk_payloads(self) -> None:
        pricing = _sample_pricing()

        self.assertEqual(
            collect_model_description_payloads(pricing),
            [{"original_text": "中文说明", "model_name": "alpha"}],
        )
        self.assertEqual(
            collect_vendor_label_payloads(pricing),
            [{"original_text": "阿里云", "context": "alpha"}],
        )
        self.assertEqual(
            collect_model_tag_payloads(pricing),
            [
                {"original_text": "视频模型", "context": "alpha"},
                {"original_text": "图像模型", "context": "gamma"},
            ],
        )

    def test_apply_model_description_translation_map_only_updates_cjk_rows(self) -> None:
        translated = apply_model_description_translation_map(
            _sample_pricing(),
            {"中文说明": "Concise English"},
        )

        self.assertEqual(translated.models[0].description, "Concise English")
        self.assertEqual(translated.models[1].description, "English description")
        self.assertEqual(translated.models[2].description, "Concise English")

    def test_apply_model_label_translation_maps_sanitizes_and_dedupes_tags(self) -> None:
        translated = apply_model_label_translation_maps(
            _sample_pricing(),
            {"阿里云": "Alibaba Cloud"},
            {"视频模型": "Video Model", "图像模型": "Image Model"},
        )

        self.assertEqual(translated.models[0].vendor_name, "Alibaba Cloud")
        self.assertEqual(translated.models[0].tags, ["Video Model", "video"])
        self.assertEqual(translated.models[1].vendor_name, "OpenAI")
        self.assertEqual(translated.models[2].tags, ["Image Model"])

    def test_text_refresh_and_fallback_only_apply_to_cjk_text(self) -> None:
        self.assertTrue(needs_text_translation_refresh("中文说明", ""))
        self.assertFalse(needs_text_translation_refresh("English description", ""))
        self.assertEqual(
            build_fallback_text_translations([{"original_text": "中文说明"}]),
            {"中文说明": ""},
        )
