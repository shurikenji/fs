"""Helpers for parsing and normalizing AI translation payloads."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.translation_text import sanitize_model_description_text

logger = logging.getLogger(__name__)


def parse_ai_json(content: str) -> dict[str, Any]:
    if not content:
        return {}
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                parsed = json.loads(text[start:end])
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                pass
        logger.warning("Could not parse AI translation payload")
        return {}


def normalize_ai_group_response(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if not payload:
        return {}

    items = payload["items"] if isinstance(payload.get("items"), list) else []
    translations: dict[str, dict[str, Any]] = {}

    for item in items:
        if not isinstance(item, dict):
            continue
        original_name = str(item.get("original_name") or "").strip()
        if not original_name:
            continue
        translations[original_name] = {
            "name_en": str(item.get("name_en") or "").strip(),
            "desc_en": str(item.get("desc_en") or "").strip(),
            "category": str(item.get("category") or "Other").strip() or "Other",
        }

    if translations:
        return translations

    for original_name, item in payload.items():
        if original_name == "items" or not isinstance(item, dict):
            continue
        translations[str(original_name).strip()] = {
            "name_en": str(item.get("name_en") or "").strip(),
            "desc_en": str(item.get("desc_en") or "").strip(),
            "category": str(item.get("category") or "Other").strip() or "Other",
        }
    return translations


def normalize_ai_text_response(payload: dict[str, Any]) -> dict[str, str]:
    if not payload:
        return {}

    translations: dict[str, str] = {}
    items = payload.get("items")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            original_text = str(item.get("original_text") or "").strip()
            if not original_text:
                continue
            translations[original_text] = sanitize_model_description_text(
                str(item.get("text_en") or "").strip()
            )

    if translations:
        return translations

    for original_text, value in payload.items():
        if original_text == "items":
            continue
        if isinstance(value, dict):
            translations[str(original_text).strip()] = sanitize_model_description_text(
                str(value.get("text_en") or "").strip()
            )
        elif isinstance(value, str):
            translations[str(original_text).strip()] = sanitize_model_description_text(value)
    return translations
