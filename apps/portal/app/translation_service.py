"""Translation cache and optional AI translation for public pricing."""
from __future__ import annotations

import json
import logging
from typing import Any

from app.translation_ai_client import request_ai_completion
from app.translation_ai_payloads import (
    normalize_ai_group_response,
    normalize_ai_text_response,
    parse_ai_json,
)
from app.translation_ai_settings import get_runtime_ai_settings
from app.public_pricing_presenter import (
    prepare_public_pricing_presentation,
    render_public_pricing,
)
from app.sanitizer import contains_cjk
from app.schemas import NormalizedPricing
from app.translation_groups import (
    apply_group_translation_map,
    build_fallback_group_translations,
    collect_groups_for_translation,
    group_row_payload,
    needs_group_translation_refresh,
    sanitize_group_translation_payload,
    translate_group_rows_from_map,
)
from app.translation_text import (
    apply_model_description_translation_map,
    apply_model_label_translation_maps,
    build_fallback_text_translations,
    collect_model_description_payloads,
    collect_model_tag_payloads,
    collect_vendor_label_payloads,
    needs_text_translation_refresh,
    sanitize_model_description_text,
    sanitize_short_label_text,
)
from db.queries.translations import (
    get_cached_text_translations,
    get_cached_translations,
    save_text_translations,
    save_translations,
)

logger = logging.getLogger(__name__)
_MODEL_DESCRIPTION_TEXT_TYPE = "model_description"
_MODEL_TAG_TEXT_TYPE = "model_tag"
_VENDOR_LABEL_TEXT_TYPE = "vendor_label"

async def build_public_pricing(pricing: NormalizedPricing, server: dict) -> NormalizedPricing:
    """Apply cached/AI translations before public sanitization."""
    server_type = str(server.get("type") or "newapi")
    pricing = await apply_model_description_translations(pricing, server_type)
    pricing = await apply_model_label_translations(pricing, server_type)
    presentation = await prepare_public_pricing_presentation(pricing, server)

    if presentation.group_catalog:
        return render_public_pricing(pricing, presentation)

    translated = await apply_group_translations(pricing, server_type)
    return render_public_pricing(translated, presentation)


async def translate_group_rows(groups: list[dict[str, Any]], server_type: str) -> list[dict[str, Any]]:
    """Translate a raw server group catalog using the same cache/AI flow as shopbot."""
    payloads = [group_row_payload(group) for group in groups if str(group.get("name") or "").strip()]
    if not payloads:
        return []

    cached = await get_cached_translations(
        [item["original_name"] for item in payloads],
        server_type,
    )
    missing = [
        item
        for item in payloads
        if needs_group_translation_refresh(item, cached.get(item["original_name"]))
    ]

    if missing:
        generated = build_fallback_group_translations(missing)
        ai_generated = await _translate_groups_with_ai(missing)
        if ai_generated:
            generated.update(sanitize_group_translation_payload(ai_generated, missing))
        if generated:
            cached.update(generated)
            await save_translations(generated, server_type)

    return translate_group_rows_from_map(groups, cached)


async def apply_group_translations(pricing: NormalizedPricing, server_type: str) -> NormalizedPricing:
    group_payloads = collect_groups_for_translation(pricing)
    cached = await get_cached_translations([item["original_name"] for item in group_payloads], server_type)
    missing = [item for item in group_payloads if needs_group_translation_refresh(item, cached.get(item["original_name"]))]

    if missing:
        generated = build_fallback_group_translations(missing)
        ai_generated = await _translate_groups_with_ai(missing)
        if ai_generated:
            generated.update(sanitize_group_translation_payload(ai_generated, missing))
        if generated:
            cached.update(generated)
            await save_translations(generated, server_type)

    return apply_group_translation_map(pricing, cached)


async def warm_translation_cache(pricing: NormalizedPricing, server_type: str) -> int:
    """Populate translation cache for a pricing snapshot and return affected group count."""
    group_payloads = collect_groups_for_translation(pricing)
    cached = await get_cached_translations([item["original_name"] for item in group_payloads], server_type)
    missing = [item for item in group_payloads if needs_group_translation_refresh(item, cached.get(item["original_name"]))]
    if not missing:
        return 0

    generated = build_fallback_group_translations(missing)
    ai_generated = await _translate_groups_with_ai(missing)
    if ai_generated:
        generated.update(sanitize_group_translation_payload(ai_generated, missing))
    if generated:
        await save_translations(generated, server_type)
    group_count = len(generated)
    model_count = await warm_model_description_cache(pricing, server_type)
    label_count = await warm_model_label_cache(pricing, server_type)
    return group_count + model_count + label_count


async def apply_model_description_translations(
    pricing: NormalizedPricing,
    server_type: str,
) -> NormalizedPricing:
    payloads = collect_model_description_payloads(pricing)
    if not payloads:
        return pricing

    cached = await get_cached_text_translations(
        [item["original_text"] for item in payloads],
        server_type,
        _MODEL_DESCRIPTION_TEXT_TYPE,
    )
    missing = [
        item
        for item in payloads
        if needs_text_translation_refresh(item["original_text"], cached.get(item["original_text"]))
    ]

    generated: dict[str, str] = {}
    if missing:
        generated.update(build_fallback_text_translations(missing))
        ai_generated = await _translate_model_descriptions_with_ai(missing)
        if ai_generated:
            generated.update(ai_generated)
        if generated:
            await save_text_translations(generated, server_type, _MODEL_DESCRIPTION_TEXT_TYPE)
            cached.update(generated)

    return apply_model_description_translation_map(pricing, {**cached, **generated})


async def warm_model_description_cache(pricing: NormalizedPricing, server_type: str) -> int:
    payloads = collect_model_description_payloads(pricing)
    if not payloads:
        return 0

    cached = await get_cached_text_translations(
        [item["original_text"] for item in payloads],
        server_type,
        _MODEL_DESCRIPTION_TEXT_TYPE,
    )
    missing = [
        item
        for item in payloads
        if needs_text_translation_refresh(item["original_text"], cached.get(item["original_text"]))
    ]
    if not missing:
        return 0

    generated = build_fallback_text_translations(missing)
    ai_generated = await _translate_model_descriptions_with_ai(missing)
    if ai_generated:
        generated.update(ai_generated)
    if generated:
        await save_text_translations(generated, server_type, _MODEL_DESCRIPTION_TEXT_TYPE)
    return len(generated)


async def apply_model_label_translations(
    pricing: NormalizedPricing,
    server_type: str,
) -> NormalizedPricing:
    vendor_map = await _resolve_short_text_translations(
        collect_vendor_label_payloads(pricing),
        server_type,
        _VENDOR_LABEL_TEXT_TYPE,
        label_kind="vendor",
    )
    tag_map = await _resolve_short_text_translations(
        collect_model_tag_payloads(pricing),
        server_type,
        _MODEL_TAG_TEXT_TYPE,
        label_kind="tag",
    )
    return apply_model_label_translation_maps(pricing, vendor_map, tag_map)


async def warm_model_label_cache(pricing: NormalizedPricing, server_type: str) -> int:
    vendor_translations = await _resolve_short_text_translations(
        collect_vendor_label_payloads(pricing),
        server_type,
        _VENDOR_LABEL_TEXT_TYPE,
        label_kind="vendor",
        persist_only=True,
    )
    tag_translations = await _resolve_short_text_translations(
        collect_model_tag_payloads(pricing),
        server_type,
        _MODEL_TAG_TEXT_TYPE,
        label_kind="tag",
        persist_only=True,
    )
    return len(vendor_translations) + len(tag_translations)


async def _translate_groups_with_ai(groups: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    ai_settings = await get_runtime_ai_settings()
    if not ai_settings["enabled"] or not ai_settings["api_key"]:
        return {}

    system_prompt = (
        "You translate API token-group labels and descriptions into concise English for a pricing dashboard. "
        "Use source_text as the richer context when it contains Chinese notes, route hints, or quality markers. "
        "Preserve well-known brand names like Azure, OpenAI, Claude, Gemini, Grok, Kimi, DeepSeek, and Anthropic. "
        "Return English only. No Chinese characters, no mixed Chinese-English output, no markdown. "
        "Return JSON with key 'items'. Each item must include original_name, name_en, desc_en, and category. "
        "Allowed categories: General, Premium, Official, Reverse, Experimental, Regional, Other."
    )
    user_prompt = json.dumps({"items": groups}, ensure_ascii=False)

    try:
        content = await request_ai_completion(
            str(ai_settings["provider"]),
            system_prompt,
            user_prompt,
            api_key=str(ai_settings["api_key"]),
            model=str(ai_settings["model"]),
            base_url=str(ai_settings["base_url"]),
            compatible_only=str(ai_settings["provider"]) == "openai_compatible",
        )
    except Exception as exc:
        logger.warning("AI translation request failed: %s", exc)
        return {}

    return normalize_ai_group_response(parse_ai_json(content))


async def _translate_model_descriptions_with_ai(
    payloads: list[dict[str, str]],
) -> dict[str, str]:
    ai_settings = await get_runtime_ai_settings()
    if not ai_settings["enabled"] or not ai_settings["api_key"]:
        return {}

    system_prompt = (
        "You translate AI model descriptions into concise natural English for a pricing dashboard. "
        "Preserve product names, API terms, and technical wording such as embedding, rerank, reasoning, multimodal, and context window sizes. "
        "Do not add marketing fluff. Return JSON with key 'items'. Each item must include original_text and text_en only."
    )
    user_prompt = json.dumps({"items": payloads}, ensure_ascii=False)

    try:
        content = await request_ai_completion(
            str(ai_settings["provider"]),
            system_prompt,
            user_prompt,
            api_key=str(ai_settings["api_key"]),
            model=str(ai_settings["model"]),
            base_url=str(ai_settings["base_url"]),
            compatible_only=str(ai_settings["provider"]) == "openai_compatible",
        )
    except Exception as exc:
        logger.warning("AI model description translation failed: %s", exc)
        return {}

    return normalize_ai_text_response(parse_ai_json(content))


async def _translate_short_texts_with_ai(
    payloads: list[dict[str, str]],
    *,
    label_kind: str,
) -> dict[str, str]:
    ai_settings = await get_runtime_ai_settings()
    if not ai_settings["enabled"] or not ai_settings["api_key"]:
        return {}

    system_prompt = (
        "You translate short labels for an AI pricing dashboard into concise natural English. "
        "Preserve well-known brands such as OpenAI, Claude, Gemini, Grok, Azure, Anthropic, Google, and DeepSeek. "
        "Never output Chinese characters. Never include markdown, explanations, or URLs. "
        "For vendors, return compact provider names like 'Other' or 'Alibaba Cloud'. "
        "For tags, return concise product labels like 'Video Model' or 'Image Model'. "
        "Return JSON with key 'items'. Each item must include original_text and text_en only."
    )
    user_prompt = json.dumps(
        {
            "kind": label_kind,
            "items": payloads,
        },
        ensure_ascii=False,
    )

    try:
        content = await request_ai_completion(
            str(ai_settings["provider"]),
            system_prompt,
            user_prompt,
            api_key=str(ai_settings["api_key"]),
            model=str(ai_settings["model"]),
            base_url=str(ai_settings["base_url"]),
            compatible_only=str(ai_settings["provider"]) == "openai_compatible",
        )
    except Exception as exc:
        logger.warning("AI short-label translation failed: %s", exc)
        return {}

    return normalize_ai_text_response(parse_ai_json(content))


async def _resolve_short_text_translations(
    payloads: list[dict[str, str]],
    server_type: str,
    text_type: str,
    *,
    label_kind: str,
    persist_only: bool = False,
) -> dict[str, str]:
    if not payloads:
        return {}

    cached = await get_cached_text_translations(
        [item["original_text"] for item in payloads],
        server_type,
        text_type,
    )
    missing = [
        item
        for item in payloads
        if needs_text_translation_refresh(item["original_text"], cached.get(item["original_text"]))
    ]

    generated: dict[str, str] = {}
    if missing:
        generated.update(build_fallback_text_translations(missing))
        ai_generated = await _translate_short_texts_with_ai(missing, label_kind=label_kind)
        if ai_generated:
            generated.update(ai_generated)
        if generated:
            await save_text_translations(generated, server_type, text_type)
            cached.update(generated)

    if persist_only:
        return generated

    resolved: dict[str, str] = {}
    for item in payloads:
        original_text = item["original_text"]
        resolved[original_text] = _sanitize_short_label_text(
            cached.get(original_text)
            or generated.get(original_text)
            or original_text
        )
    return resolved


async def test_ai_connection(provider: str, api_key: str, model: str, base_url: str = "") -> tuple[bool, str]:
    provider_value = (provider or "openai").strip().lower()
    key_value = (api_key or "").strip()
    model_value = (model or "").strip()
    base_url_value = (base_url or "").strip()

    if not key_value:
        return False, "API key is required."
    if not model_value:
        return False, "Model is required."

    system_prompt = "Reply with a short JSON object."
    user_prompt = '{"ping":"ok"}'

    try:
        content = await request_ai_completion(
            provider_value,
            system_prompt,
            user_prompt,
            api_key=key_value,
            model=model_value,
            base_url=base_url_value,
            compatible_only=provider_value == "openai_compatible",
        )
    except Exception as exc:
        return False, str(exc)

    return True, "Connection succeeded." if content is not None else "Connection succeeded."
