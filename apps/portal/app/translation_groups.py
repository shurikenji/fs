"""Pure helpers for pricing group translation payloads and rendering."""
from __future__ import annotations

from typing import Any

from app.sanitizer import (
    canonical_group_label,
    contains_cjk,
    extract_ascii_name_tokens,
    fallback_english,
    is_context_derived_group_name,
    normalize_group_name_for_compare,
    strip_group_price_notes,
)
from app.schemas import NormalizedPricing

_ALLOWED_CATEGORIES = {
    "General",
    "Premium",
    "Official",
    "Reverse",
    "Experimental",
    "Regional",
    "Other",
}


def collect_groups_for_translation(pricing: NormalizedPricing) -> list[dict[str, str]]:
    return [
        group_payload(group)
        for group in pricing.groups
        if contains_cjk(group.display_name or group.name) or contains_cjk(group.description)
    ]


def group_payload(group: Any) -> dict[str, str]:
    original_name = str(group.name or "").strip()
    display_name = str(group.display_name or original_name).strip()
    description = str(group.description or "").strip()
    source_text = strip_group_price_notes(original_name)
    context_text = strip_group_price_notes(description or display_name or original_name)
    return {
        "original_name": original_name,
        "display_name": display_name,
        "description": description,
        "source_text": source_text,
        "context_text": context_text,
        "ratio_source": source_text,
    }


def group_row_payload(group: dict[str, Any]) -> dict[str, str]:
    original_name = str(group.get("name") or "").strip()
    display_name = strip_group_price_notes(str(
        group.get("label_en")
        or group.get("name_en")
        or group.get("display_name")
        or original_name
    ).strip())
    description = str(group.get("desc") or group.get("description") or "").strip()
    source_text = strip_group_price_notes(original_name)
    ratio_source = str(
        group.get("ratio_source")
        or group.get("raw_label")
        or group.get("translation_source")
        or description
        or original_name
    ).strip()
    context_text = strip_group_price_notes(str(
        group.get("translation_source")
        or description
        or display_name
        or original_name
    ).strip())
    return {
        "original_name": original_name,
        "display_name": display_name,
        "description": description,
        "source_text": source_text,
        "context_text": context_text,
        "ratio_source": ratio_source,
    }


def needs_group_translation_refresh(
    group: dict[str, str],
    cached: dict[str, Any] | None = None,
) -> bool:
    current = cached or {}
    name_en = str(current.get("name_en") or "").strip()
    desc_en = str(current.get("desc_en") or "").strip()
    if not name_en or contains_cjk(name_en):
        return True
    if _looks_context_derived_group_name(
        name_en,
        original_name=str(group.get("original_name") or ""),
        context_text=str(group.get("context_text") or group.get("source_text") or ""),
    ):
        return True
    if not desc_en and contains_cjk(str(group.get("context_text") or group.get("source_text") or "")):
        return True
    return contains_cjk(desc_en)


def build_group_translation_fields(
    group: dict[str, str],
    translation: dict[str, Any],
) -> dict[str, str]:
    original_name = str(group.get("original_name") or "")
    source_text = str(group.get("source_text") or original_name)
    context_text = str(group.get("context_text") or source_text or original_name)
    name_en = _resolve_english_name(
        preferred=translation.get("name_en"),
        original_name=original_name,
        source_text=source_text,
        context_text=context_text,
    )
    desc_en = _resolve_english_description(
        preferred=translation.get("desc_en") or group.get("description"),
        source_text=context_text,
        fallback_name=name_en,
    )
    category = str(translation.get("category") or "Other").strip() or "Other"
    if category not in _ALLOWED_CATEGORIES:
        category = "Other"
    return {
        "name_en": name_en,
        "desc_en": desc_en,
        "category": category,
    }


def sanitize_group_translation_payload(
    translations: dict[str, dict[str, Any]],
    groups: list[dict[str, str]],
) -> dict[str, dict[str, str]]:
    source_map = {group["original_name"]: group for group in groups}
    cleaned: dict[str, dict[str, str]] = {}
    for original_name, translation in translations.items():
        group = source_map.get(original_name)
        if not group:
            continue
        cleaned[original_name] = build_group_translation_fields(group, translation)
    return cleaned


def build_fallback_group_translations(
    groups: list[dict[str, str]],
) -> dict[str, dict[str, str]]:
    return {
        item["original_name"]: build_group_translation_fields(item, {})
        for item in groups
    }


def apply_group_translation_map(
    pricing: NormalizedPricing,
    translated_groups: dict[str, dict[str, Any]],
) -> NormalizedPricing:
    updated_groups = []
    for group in pricing.groups:
        data = translated_groups.get(group.name)
        if data:
            normalized = build_group_translation_fields(group_payload(group), data)
            updated_groups.append(group.model_copy(update={
                "display_name": normalized["name_en"],
                "description": normalized["desc_en"],
                "category": normalized["category"] or group.category,
            }))
        else:
            updated_groups.append(group)
    return pricing.model_copy(update={"groups": updated_groups})


def translate_group_rows_from_map(
    groups: list[dict[str, Any]],
    translated_groups: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    translated_rows: list[dict[str, Any]] = []
    payload_map = {
        item["original_name"]: item
        for item in (group_row_payload(group) for group in groups if str(group.get("name") or "").strip())
    }
    for group in groups:
        original_name = str(group.get("name") or "").strip()
        if not original_name:
            continue
        payload = payload_map[original_name]
        translation = translated_groups.get(original_name, {})
        normalized = build_group_translation_fields(payload, translation)
        translated_rows.append(
            {
                **group,
                "label_en": normalized["name_en"],
                "name_en": normalized["name_en"],
                "desc": normalized["desc_en"] or str(group.get("desc") or ""),
                "desc_en": normalized["desc_en"],
                "category": normalized["category"] or str(group.get("category") or "Other"),
                "translation_source": str(
                    group.get("translation_source")
                    or payload.get("context_text")
                    or original_name
                ).strip(),
                "ratio_source": str(
                    group.get("ratio_source")
                    or payload.get("ratio_source")
                    or original_name
                ).strip(),
            }
        )
    return translated_rows


def _resolve_english_name(*, preferred: object, original_name: str, source_text: str, context_text: str) -> str:
    name_en = strip_group_price_notes(str(preferred or "").strip())
    cleaned_original_name = strip_group_price_notes(original_name)
    canonical_original = canonical_group_label(cleaned_original_name)
    if canonical_original:
        return canonical_original
    rejected_translated_name = name_en and not contains_cjk(name_en) and _should_reject_translated_group_name(
        name_en,
        original_name=cleaned_original_name,
        context_text=context_text,
    )
    if name_en and not contains_cjk(name_en) and not rejected_translated_name:
        return name_en
    return (
        ("" if rejected_translated_name else fallback_english(name_en))
        or fallback_english(cleaned_original_name)
        or fallback_english(source_text)
        or cleaned_original_name
        or original_name
    )


def _resolve_english_description(*, preferred: object, source_text: str, fallback_name: str) -> str:
    desc_en = str(preferred or "").strip()
    if desc_en and not contains_cjk(desc_en):
        return desc_en
    return (
        fallback_english(desc_en)
        or fallback_english(source_text)
        or fallback_name
    )


def _looks_context_derived_group_name(name_en: str, *, original_name: str, context_text: str) -> bool:
    return is_context_derived_group_name(
        name_en,
        original_name=original_name,
        context_text=context_text,
    )


def _should_reject_translated_group_name(name_en: str, *, original_name: str, context_text: str) -> bool:
    if _looks_context_derived_group_name(
        name_en,
        original_name=original_name,
        context_text=context_text,
    ):
        return True

    fallback_name = normalize_group_name_for_compare(fallback_english(original_name))
    current_name = normalize_group_name_for_compare(name_en)
    if not current_name or current_name == fallback_name:
        return False

    current_tokens = set(extract_ascii_name_tokens(name_en))
    original_tokens = extract_ascii_name_tokens(original_name)
    return bool(original_tokens and not set(original_tokens).issubset(current_tokens))
