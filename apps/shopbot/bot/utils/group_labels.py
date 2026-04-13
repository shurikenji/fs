from __future__ import annotations

import json
import re

from bot.services.ai_translator import get_translator
from bot.utils.group_name_policy import (
    contains_cjk,
    fallback_english_group_name,
    sanitize_group_display_name,
)
from db.database import get_db


CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
FALLBACK_GROUP_REPLACEMENTS = (
    ("默认分组", "Default Group"),
    ("默认", "Default"),
    ("官方中转", "Official Relay"),
    ("官方", "Official"),
    ("官逆", "Official Reverse"),
    ("逆向", "Reverse"),
    ("无审", "Unfiltered"),
    ("高并发", "High Concurrency"),
    ("低并发", "Low Concurrency"),
    ("高可用", "High Availability"),
    ("企业级", "Enterprise"),
    ("专属", "Dedicated"),
    ("特价", "Discount"),
    ("限时", "Limited Time"),
    ("优质", "Premium"),
    ("直连", "Direct"),
    ("慢速", "Slow"),
    ("渠道", "Route"),
    ("可用站内大部分模型", "Most Models"),
    ("大模型", "Model Pool"),
    ("纯", "Pure"),
    ("分组", "Group"),
)


def _split_group_names(group_value: str | None) -> list[str]:
    return [part.strip() for part in str(group_value or "").split(",") if part.strip()]


def _contains_cjk(text: object) -> bool:
    return contains_cjk(text)


def _fallback_group_label(label: object, original_name: str) -> str:
    return sanitize_group_display_name(original_name, label) or fallback_english_group_name(original_name)
    value = str(label or original_name or "").strip()
    if not value:
        return ""
    if not _contains_cjk(value):
        return value

    for source, target in FALLBACK_GROUP_REPLACEMENTS:
        value = value.replace(source, f" {target} ")

    value = value.replace("（", "(").replace("）", ")")
    value = re.sub(r"[\[\]{}]", " ", value)
    value = CJK_RE.sub(" ", value)
    value = re.sub(r"\s*[-_/,:;]+\s*", " ", value)
    value = re.sub(r"\(\s*([^)]+?)\s*\)", r" \1 ", value)
    value = re.sub(r"\s+", " ", value).strip(" -_,")
    return value or original_name


def _group_labels_from_cache(server: dict | None) -> dict[str, str]:
    if not server:
        return {}

    raw_cache = server.get("groups_cache")
    if not raw_cache:
        return {}

    try:
        rows = json.loads(raw_cache)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}

    if not isinstance(rows, list):
        return {}

    label_map: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        label_en = str(
            row.get("label_en") or row.get("name_en") or row.get("name") or ""
        ).strip()
        if name:
            label_map[name] = sanitize_group_display_name(name, label_en or name)
    return label_map


async def _get_cached_group_labels(
    group_names: list[str], api_type: str
) -> dict[str, str]:
    if not group_names:
        return {}

    db = await get_db()
    placeholders = ",".join("?" * len(group_names))
    cursor = await db.execute(
        f"""SELECT original_name, name_en
            FROM group_translations
            WHERE original_name IN ({placeholders}) AND api_type = ?""",
        (*group_names, api_type),
    )
    rows = await cursor.fetchall()
    return {
        str(row[0]): sanitize_group_display_name(row[0], str(row[1] or row[0]).strip())
        for row in rows
        if row and row[0]
    }


async def format_group_display_names(
    group_value: str | None, server: dict | None = None
) -> str:
    group_names = _split_group_names(group_value)
    if not group_names:
        return ""

    label_map = _group_labels_from_cache(server)
    missing_names = [
        name
        for name in group_names
        if not label_map.get(name) or _contains_cjk(label_map.get(name))
    ]

    if missing_names and server:
        api_type = str(server.get("api_type") or "newapi")
        label_map.update(await _get_cached_group_labels(missing_names, api_type))
        unresolved_names = [
            name
            for name in missing_names
            if not label_map.get(name) or _contains_cjk(label_map.get(name))
        ]
        if unresolved_names:
            translator = await get_translator()
            if translator.is_configured:
                translated_groups = await translator.translate_groups(
                    [{"name": name} for name in unresolved_names],
                    api_type,
                )
                for group in translated_groups:
                    name = str(group.get("name") or "").strip()
                    label_en = str(
                        group.get("label_en")
                        or group.get("name_en")
                        or group.get("name")
                        or ""
                    ).strip()
                    if name and label_en:
                        label_map[name] = label_en

    return ", ".join(
        _fallback_group_label(label_map.get(name), name) for name in group_names
    )
