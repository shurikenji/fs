"""Pure helpers for pricing text translation payloads and rendering."""
from __future__ import annotations

import re

from app.sanitizer import contains_cjk, fallback_english, sanitize_description
from app.schemas import NormalizedPricing


def collect_model_description_payloads(pricing: NormalizedPricing) -> list[dict[str, str]]:
    payloads: list[dict[str, str]] = []
    seen: set[str] = set()
    for model in pricing.models:
        description = str(model.description or "").strip()
        if not description or not contains_cjk(description) or description in seen:
            continue
        seen.add(description)
        payloads.append(
            {
                "original_text": description,
                "model_name": str(model.model_name or "").strip(),
            }
        )
    return payloads


def collect_vendor_label_payloads(pricing: NormalizedPricing) -> list[dict[str, str]]:
    payloads: list[dict[str, str]] = []
    seen: set[str] = set()
    for model in pricing.models:
        vendor_name = str(model.vendor_name or "").strip()
        if not vendor_name or not contains_cjk(vendor_name) or vendor_name in seen:
            continue
        seen.add(vendor_name)
        payloads.append(
            {
                "original_text": vendor_name,
                "context": str(model.model_name or "").strip(),
            }
        )
    return payloads


def collect_model_tag_payloads(pricing: NormalizedPricing) -> list[dict[str, str]]:
    payloads: list[dict[str, str]] = []
    seen: set[str] = set()
    for model in pricing.models:
        model_name = str(model.model_name or "").strip()
        for tag in model.tags:
            original_tag = str(tag or "").strip()
            if not original_tag or not contains_cjk(original_tag) or original_tag in seen:
                continue
            seen.add(original_tag)
            payloads.append(
                {
                    "original_text": original_tag,
                    "context": model_name,
                }
            )
    return payloads


def needs_text_translation_refresh(original_text: str, cached_text: str | None = None) -> bool:
    if not contains_cjk(original_text):
        return False
    value = str(cached_text or "").strip()
    return not value or contains_cjk(value)


def sanitize_model_description_text(text: str) -> str:
    cleaned = sanitize_description(text)
    if contains_cjk(cleaned):
        return ""
    return cleaned


def sanitize_short_label_text(text: str) -> str:
    cleaned = sanitize_description(text)
    if contains_cjk(cleaned):
        cleaned = fallback_english(cleaned)
    cleaned = re.sub(r"\s+", " ", str(cleaned or "")).strip(" -_,.")
    return cleaned


def build_fallback_text_translations(payloads: list[dict[str, str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in payloads:
        original_text = item["original_text"]
        out[original_text] = sanitize_model_description_text(fallback_english(original_text))
    return out


def apply_model_description_translation_map(
    pricing: NormalizedPricing,
    translated_texts: dict[str, str],
) -> NormalizedPricing:
    translated_models = []
    for model in pricing.models:
        description = str(model.description or "")
        if contains_cjk(description):
            translated = sanitize_model_description_text(
                translated_texts.get(description) or description
            )
            translated_models.append(model.model_copy(update={"description": translated}))
        else:
            translated_models.append(model)
    return pricing.model_copy(update={"models": translated_models})


def apply_model_label_translation_maps(
    pricing: NormalizedPricing,
    vendor_map: dict[str, str],
    tag_map: dict[str, str],
) -> NormalizedPricing:
    translated_models = []
    for model in pricing.models:
        original_vendor = str(model.vendor_name or "").strip()
        vendor_name = original_vendor
        if contains_cjk(original_vendor):
            vendor_name = sanitize_short_label_text(
                vendor_map.get(original_vendor) or original_vendor
            )

        translated_tags: list[str] = []
        seen_tags: set[str] = set()
        for tag in model.tags:
            original_tag = str(tag or "").strip()
            if not original_tag:
                continue
            translated_tag = tag_map.get(original_tag) if contains_cjk(original_tag) else original_tag
            normalized_tag = sanitize_short_label_text(translated_tag or original_tag)
            if not normalized_tag or normalized_tag in seen_tags:
                continue
            seen_tags.add(normalized_tag)
            translated_tags.append(normalized_tag)

        translated_models.append(
            model.model_copy(
                update={
                    "vendor_name": vendor_name,
                    "tags": translated_tags,
                }
            )
        )

    return pricing.model_copy(update={"models": translated_models})
