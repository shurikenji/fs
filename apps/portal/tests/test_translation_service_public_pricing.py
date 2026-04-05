import unittest
from unittest.mock import AsyncMock, Mock, patch

from app.public_pricing_presenter import PublicPricingPresentation
from app.schemas import NormalizedModel, NormalizedPricing
from app.translation_service import build_public_pricing, apply_model_label_translations


def _sample_pricing(server_name: str = "Server 1") -> NormalizedPricing:
    return NormalizedPricing(
        server_id="server-1",
        server_name=server_name,
        models=[],
        groups=[],
        fetched_at="2026-04-05T00:00:00Z",
    )


class BuildPublicPricingTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_presenter_directly_when_catalog_exists(self) -> None:
        pricing = _sample_pricing()
        described = _sample_pricing("Described")
        labeled = _sample_pricing("Labeled")
        final = _sample_pricing("Final")
        presentation = PublicPricingPresentation(
            hidden_groups=set(),
            excluded_models=set(),
            group_catalog={"g1": {"name": "g1"}},
        )

        with (
            patch(
                "app.translation_service.apply_model_description_translations",
                AsyncMock(return_value=described),
            ) as description_mock,
            patch(
                "app.translation_service.apply_model_label_translations",
                AsyncMock(return_value=labeled),
            ) as label_mock,
            patch(
                "app.translation_service.prepare_public_pricing_presentation",
                AsyncMock(return_value=presentation),
            ) as prepare_mock,
            patch(
                "app.translation_service.apply_group_translations",
                AsyncMock(),
            ) as groups_mock,
            patch(
                "app.translation_service.render_public_pricing",
                Mock(return_value=final),
            ) as render_mock,
        ):
            result = await build_public_pricing(pricing, {"id": "server-1", "type": "newapi"})

        self.assertIs(result, final)
        description_mock.assert_awaited_once_with(pricing, "newapi")
        label_mock.assert_awaited_once_with(described, "newapi")
        prepare_mock.assert_awaited_once_with(labeled, {"id": "server-1", "type": "newapi"})
        groups_mock.assert_not_awaited()
        render_mock.assert_called_once_with(labeled, presentation)

    async def test_falls_back_to_group_translations_when_catalog_missing(self) -> None:
        pricing = _sample_pricing()
        described = _sample_pricing("Described")
        labeled = _sample_pricing("Labeled")
        grouped = _sample_pricing("Grouped")
        final = _sample_pricing("Final")
        presentation = PublicPricingPresentation(
            hidden_groups={"hidden"},
            excluded_models={"blocked"},
            group_catalog=None,
        )

        with (
            patch(
                "app.translation_service.apply_model_description_translations",
                AsyncMock(return_value=described),
            ),
            patch(
                "app.translation_service.apply_model_label_translations",
                AsyncMock(return_value=labeled),
            ),
            patch(
                "app.translation_service.prepare_public_pricing_presentation",
                AsyncMock(return_value=presentation),
            ),
            patch(
                "app.translation_service.apply_group_translations",
                AsyncMock(return_value=grouped),
            ) as groups_mock,
            patch(
                "app.translation_service.render_public_pricing",
                Mock(return_value=final),
            ) as render_mock,
        ):
            result = await build_public_pricing(pricing, {"id": "server-1", "type": "newapi"})

        self.assertIs(result, final)
        groups_mock.assert_awaited_once_with(labeled, "newapi")
        render_mock.assert_called_once_with(grouped, presentation)


class ApplyModelLabelTranslationsTests(unittest.IsolatedAsyncioTestCase):
    async def test_short_text_translation_uses_public_sanitizer_name(self) -> None:
        pricing = NormalizedPricing(
            server_id="server-1",
            server_name="Server 1",
            models=[
                NormalizedModel(
                    model_name="alpha",
                    vendor_name="阿里云",
                    tags=["视频模型"],
                )
            ],
            groups=[],
            fetched_at="2026-04-05T00:00:00Z",
        )

        with (
            patch(
                "app.translation_service.get_cached_text_translations",
                AsyncMock(
                    side_effect=[
                        {"阿里云": "Alibaba Cloud"},
                        {"视频模型": "Video Model"},
                    ]
                ),
            ),
            patch(
                "app.translation_service.save_text_translations",
                AsyncMock(),
            ),
        ):
            translated = await apply_model_label_translations(pricing, "newapi")

        self.assertEqual(translated.models[0].vendor_name, "Alibaba Cloud")
        self.assertEqual(translated.models[0].tags, ["Video Model"])
