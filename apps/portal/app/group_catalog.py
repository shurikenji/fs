"""Canonical server group catalog using the same fetch/translate/cache flow as shopbot."""
from __future__ import annotations

import json
from typing import Any

from app.adapters import get_adapter
from app.adapters.base import extract_ratio_hint
from app.sanitizer import canonical_group_label
from db.queries.servers import update_server_cache


def _parse_groups_cache(raw: str | None) -> list[dict[str, Any]]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _split_group_names(group_value: str | None) -> list[str]:
    text = str(group_value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        parsed = None
    if isinstance(parsed, list):
        return [str(part or "").strip() for part in parsed if str(part or "").strip()]
    return [part.strip() for part in text.split(",") if part.strip()]


def _build_manual_group_rows(manual_groups: str) -> list[dict[str, Any]]:
    """Ported from shopbot manual group override."""
    return [
        {
            "name": name.strip(),
            "label_en": name.strip(),
            "ratio": 1.0,
            "desc": "",
            "category": "Other",
        }
        for name in _split_group_names(manual_groups)
    ]


def _normalize_group_rows(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ported from shopbot admin router normalization."""
    normalized_rows: list[dict[str, Any]] = []
    for group in groups:
        name = str(group.get("name") or "").strip()
        if not name:
            continue
        ratio = group.get("ratio")
        try:
            numeric_ratio = float(ratio or 1.0)
        except (TypeError, ValueError):
            numeric_ratio = extract_ratio_hint(
                group.get("desc"),
                group.get("label_en"),
                group.get("translation_source"),
                name,
                default=1.0,
            )

        normalized_rows.append(
            {
                "name": name,
                "label_en": canonical_group_label(name) or str(
                    group.get("label_en")
                    or group.get("name_en")
                    or group.get("name")
                    or ""
                ).strip(),
                "ratio": numeric_ratio,
                "desc": str(group.get("desc_en") or group.get("desc") or "").strip(),
                "category": str(group.get("category") or "Other").strip() or "Other",
            }
        )
    return normalized_rows


def _is_invalid_placeholder_catalog(groups: list[dict[str, Any]]) -> bool:
    if not groups:
        return False
    names = {str(group.get("name") or "").strip().lower() for group in groups}
    names.discard("")
    return bool(names) and names <= {"error", "failed", "unknown"}


async def ensure_server_group_catalog(
    server: dict,
    *,
    force: bool = False,
) -> list[dict[str, Any]]:
    """Load translated canonical groups from cache or fetch them using shopbot-style parsers."""
    manual_groups = str(server.get("manual_groups") or "").strip()
    if manual_groups:
        from app.translation_service import translate_group_rows

        manual_rows = _build_manual_group_rows(manual_groups)
        translated_manual_rows = await translate_group_rows(
            manual_rows,
            str(server.get("type") or "newapi"),
        )
        return _normalize_group_rows(translated_manual_rows)

    cached_rows = _parse_groups_cache(server.get("groups_cache"))
    if _is_invalid_placeholder_catalog(cached_rows):
        cached_rows = []
    cached_rows = _normalize_group_rows(cached_rows)

    if cached_rows and not force:
        return cached_rows

    adapter = get_adapter(server)
    remote_groups = await adapter.fetch_groups(server)
    if not remote_groups:
        return cached_rows

    from app.translation_service import translate_group_rows

    translated_groups = await translate_group_rows(
        remote_groups,
        str(server.get("type") or "newapi"),
    )
    rows = _normalize_group_rows(translated_groups)
    if _is_invalid_placeholder_catalog(rows):
        return []
    cache_payload = json.dumps(rows, ensure_ascii=False)
    await update_server_cache(server["id"], groups_cache=cache_payload)
    server["groups_cache"] = cache_payload
    return rows


def build_group_catalog_map(groups: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(group.get("name") or "").strip(): group
        for group in groups
        if str(group.get("name") or "").strip()
    }
