"""Public data sanitizer - hide internal details and normalize group labels."""
from __future__ import annotations

import re

from app.schemas import EndpointAlias, NormalizedGroup, NormalizedPricing, PricingVariant, PublicServer

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
SPACED_URL_RE = re.compile(r"\bhttps?\s+(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?:/\S*)?\b", re.IGNORECASE)
DOMAIN_RE = re.compile(r"\b(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?:/\S*)?\b", re.IGNORECASE)
READABLE_ASCII_GROUP_RE = re.compile(r"^[A-Za-z0-9]+(?: [A-Za-z0-9]+)*$")
ASCII_NAME_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[-_.][A-Za-z0-9]+)*")
GROUP_PRICE_NOTE_PATTERNS = (
    re.compile(
        r"\s*(?:\(|\[|（)\s*[^)\]）]*"
        r"(?:\d+(?:\.\d+)?\s*(?:x|倍(?:率)?|cny|usd|rmb|yuan|token|1m|quota|request|次|刀次)"
        r"|(?:cny|usd|rmb|yuan|token|1m|quota|request|次|刀次|\$|¥)\s*\d+(?:\.\d+)?)"
        r"[^)\]）]*(?:\)|\]|）)\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"\s*(?:[-–:|/]\s*)?(?:x\s*)?\d+(?:\.\d+)?\s*"
        r"(?:x|倍(?:率)?|cny|usd|rmb|yuan|token|1m|quota|request|次|刀次)"
        r"(?:\s*/\s*(?:token|1m|request|quota|次|刀次))?\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"\s*(?:[-–:|/]\s*)?(?:ratio|multiplier|倍率)\s*[:=]?\s*(?:x\s*)?\d+(?:\.\d+)?\s*$",
        re.IGNORECASE,
    ),
)
TRAILING_COMPARE_NUMBER_RE = re.compile(r"\s+\d+(?:\.\d+)?\s*$")
GENERIC_CONTEXT_LABELS = {
    "route",
    "channel",
    "exclusive",
    "official relay route",
    "discount route",
    "dedicated route",
    "premium channel",
    "official route",
    "reverse channel",
}
GROUP_PRICE_NOTE_RE = re.compile(
    r"\s*(?:\(|\[|ï¼ˆ)\s*[^)\]]*"
    r"(?:cny|usd|rmb|yuan|token|1m|quota|\$|¥|ï¿¥|å…ƒ|ç¾Žå…ƒ)"
    r"[^)\]]*(?:\)|\]|ï¼‰)\s*$",
    re.IGNORECASE,
)
GROUP_PRICE_SUFFIX_RE = re.compile(
    r"\s*[-–:|]\s*\d+(?:\.\d+)?\s*"
    r"(?:cny|usd|rmb|yuan|token|quota|\$|¥|ï¿¥|å…ƒ|ç¾Žå…ƒ)"
    r"(?:\s*/\s*(?:token|1m|request|quota|åˆ€|æ¬¡))?\s*$",
    re.IGNORECASE,
)

_FALLBACK_REPLACEMENTS = (
    ("\u5176\u4ed6", "Other"),
    ("\u667a\u8c31AI", "Zhipu AI"),
    ("\u667a\u8c31", "Zhipu"),
    ("\u767e\u5ea6", "Baidu"),
    ("\u7845\u57fa\u6d41\u52a8", "SiliconFlow"),
    ("\u8baf\u98de\u661f\u706b", "iFlytek Spark"),
    ("\u8c46\u5305", "Doubao"),
    ("\u963f\u91cc\u4e91", "Alibaba Cloud"),
    ("\u9ed8\u8ba4\u5206\u7ec4", "Default Group"),
    ("\u9ed8\u8ba4", "Default"),
    ("\u5b98\u65b9\u4e2d\u8f6c", "Official Relay"),
    ("\u5b98\u8f6c", "Official Relay"),
    ("\u5b98\u65b9", "Official"),
    ("\u5b98\u9006", "Official Reverse"),
    ("\u9006\u5411", "Reverse"),
    ("\u65e0\u5ba1", "Unfiltered"),
    ("\u9ad8\u5e76\u53d1", "High Concurrency"),
    ("\u4f4e\u5e76\u53d1", "Low Concurrency"),
    ("\u9ad8\u53ef\u7528", "High Availability"),
    ("\u4f01\u4e1a\u7ea7", "Enterprise"),
    ("\u4e13\u5c5e", "Dedicated"),
    ("\u4e13\u7528", "Dedicated"),
    ("\u7279\u4ef7", "Discount"),
    ("\u9650\u65f6", "Limited Time"),
    ("\u4f18\u8d28", "Premium"),
    ("\u76f4\u8fde", "Direct"),
    ("\u6162\u901f", "Slow"),
    ("\u6e20\u9053", "Route"),
    ("\u53ef\u7528\u7ad9\u5185\u5927\u90e8\u5206\u6a21\u578b", "Most Models"),
    ("\u5927\u6a21\u578b", "Model Pool"),
    ("\u7eaf", "Pure"),
    ("\u5206\u7ec4", "Group"),
    ("\u8be5\u6e20\u9053\u4e0d\u80fd\u8dd1", "Not supported on this route"),
    ("\u53ea\u63a5\u53d7\u5b98\u65b9\u7aef", "Official client only"),
    ("\u7981\u6b62\u9152\u9986", "SillyTavern not allowed"),
    ("\u9152\u9986", "SillyTavern"),
    ("\u6b21\u5361\u6a21\u578b", "Session Model"),
    ("\u7ed8\u753b\u6a21\u578b", "Image Model"),
    ("\u89c6\u9891\u6a21\u578b", "Video Model"),
    ("\u5b9a\u5236", "Custom"),
)

_CANONICAL_GROUP_LABELS = {
    "anthropic": "Anthropic",
    "azure": "Azure",
    "claude": "Claude",
    "claude code": "Claude Code",
    "deepseek": "DeepSeek",
    "default": "Default",
    "gemini": "Gemini",
    "google": "Google",
    "grok": "Grok",
    "kimi": "Kimi",
    "meta": "Meta",
    "microsoft": "Microsoft",
    "official": "Official",
    "openai": "OpenAI",
    "other": "Other",
    "premium": "Premium",
    "reverse": "Reverse",
}


def contains_cjk(text: str) -> bool:
    return bool(text and CJK_RE.search(text))


def fallback_english(text: str) -> str:
    """Best-effort Chinese -> English using a static replacement table."""
    if not text or not contains_cjk(text):
        return text

    value = str(text)
    for source, target in _FALLBACK_REPLACEMENTS:
        value = value.replace(source, f" {target} ")

    value = (
        value
        .replace("（", "(")
        .replace("）", ")")
        .replace("【", " ")
        .replace("】", " ")
        .replace("“", " ")
        .replace("”", " ")
        .replace("‘", " ")
        .replace("’", " ")
        .replace("，", " ")
        .replace("。", " ")
        .replace("！", " ")
        .replace("？", " ")
        .replace("：", " ")
        .replace("；", " ")
        .replace("、", " ")
    )
    value = re.sub(r"[\[\]{}<>]", " ", value)
    value = CJK_RE.sub(" ", value)
    value = re.sub(r"\s*[-_/,:;]+\s*", " ", value)
    value = re.sub(r"\(\s*([^)]+?)\s*\)", r" \1 ", value)
    value = re.sub(r"\s+", " ", value).strip(" -_,.")
    return value or str(text)


def _strip_links(text: str) -> str:
    value = str(text or "")
    value = URL_RE.sub(" ", value)
    value = SPACED_URL_RE.sub(" ", value)
    value = DOMAIN_RE.sub(" ", value)
    value = re.sub(r"\bhttps?\b", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value).strip(" -_,.")
    return value


def strip_group_price_notes(text: str) -> str:
    """Remove trailing price annotations from group labels."""
    value = str(text or "").strip()
    if not value:
        return ""

    previous = None
    while value and value != previous:
        previous = value
        for pattern in GROUP_PRICE_NOTE_PATTERNS:
            value = pattern.sub("", value).strip()

    value = re.sub(r"\s+", " ", value).strip(" -_,.")
    return value or str(text or "").strip()


def normalize_group_name_for_compare(text: str) -> str:
    value = strip_group_price_notes(str(text or "").strip())
    if not value:
        return ""
    value = _strip_links(value)
    value = TRAILING_COMPARE_NUMBER_RE.sub("", value)
    value = re.sub(r"\s+", " ", value).strip(" -_,.")
    return value.lower()


def extract_ascii_name_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for match in ASCII_NAME_TOKEN_RE.findall(strip_group_price_notes(str(text or ""))):
        for part in re.split(r"[-_.]+", match):
            normalized = part.strip().lower()
            if normalized:
                tokens.append(normalized)
    return tokens


def is_context_derived_group_name(name_en: str, *, original_name: str, context_text: str) -> bool:
    current_name = normalize_group_name_for_compare(name_en)
    if not current_name or not contains_cjk(original_name):
        return False

    original_fallback = normalize_group_name_for_compare(fallback_english(original_name))
    context_fallback = normalize_group_name_for_compare(fallback_english(context_text))
    original_tokens = extract_ascii_name_tokens(original_name)
    current_tokens = set(extract_ascii_name_tokens(name_en))

    if original_fallback and context_fallback and current_name == context_fallback and current_name != original_fallback:
        return True

    if original_tokens and not set(original_tokens).issubset(current_tokens):
        return True

    return current_name in GENERIC_CONTEXT_LABELS and current_name != original_fallback


def canonical_group_label(name: str) -> str:
    """Return a stable public label for readable ASCII group names."""
    value = strip_group_price_notes(name)
    if not value or contains_cjk(value):
        return ""

    normalized = re.sub(r"\s+", " ", value).strip()
    if not READABLE_ASCII_GROUP_RE.fullmatch(normalized):
        return ""

    lowered = normalized.lower()
    if lowered in _CANONICAL_GROUP_LABELS:
        return _CANONICAL_GROUP_LABELS[lowered]

    parts: list[str] = []
    for part in normalized.split():
        lowered_part = part.lower()
        if lowered_part in _CANONICAL_GROUP_LABELS:
            parts.append(_CANONICAL_GROUP_LABELS[lowered_part])
        elif any(ch.isupper() for ch in part[1:]) or any(ch.isdigit() for ch in part):
            parts.append(part)
        else:
            parts.append(part[:1].upper() + part[1:])
    return " ".join(parts)


def sanitize_server(server: dict) -> PublicServer:
    """Strip internal fields from server for public display."""
    return PublicServer(
        id=server["id"],
        name=server["name"],
        supports_group_chain=bool(server.get("supports_group_chain")),
        public_pricing_enabled=bool(server.get("public_pricing_enabled")),
        public_balance_enabled=bool(server.get("public_balance_enabled")),
        public_keys_enabled=bool(server.get("public_keys_enabled")),
        public_logs_enabled=bool(server.get("public_logs_enabled")),
    )


def sanitize_group_name(name: str, display_name: str = "") -> str:
    """Return a public-safe English group label."""
    original = strip_group_price_notes(name)
    preferred = strip_group_price_notes(display_name or original)
    if not original and not preferred:
        return ""

    canonical_original = canonical_group_label(original)
    if canonical_original:
        canonical_preferred = canonical_group_label(preferred)
        if canonical_preferred and canonical_preferred.lower() == canonical_original.lower():
            return canonical_preferred
        return canonical_original

    # For non-CJK group IDs, prefer the actual upstream name over any cached
    # display label that may have been derived from descriptions or route notes.
    if original and not contains_cjk(original):
        return original

    if preferred and preferred != original:
        if not contains_cjk(preferred) and not is_context_derived_group_name(
            preferred,
            original_name=original,
            context_text=display_name or preferred,
        ):
            return preferred
        translated_preferred = fallback_english(preferred)
        if translated_preferred and not contains_cjk(translated_preferred) and not is_context_derived_group_name(
            translated_preferred,
            original_name=original,
            context_text=display_name or preferred,
        ):
            return translated_preferred

    if original and re.search(r"[A-Za-z0-9]", original):
        return fallback_english(original) if contains_cjk(original) else original

    if not contains_cjk(preferred):
        return preferred
    return fallback_english(preferred)


def sanitize_description(desc: str) -> str:
    """Clean descriptions for public display and translate CJK when present."""
    if not desc:
        return ""
    cleaned = _strip_links(desc)
    translated = fallback_english(cleaned)
    return _strip_links(translated)


def sanitize_group_description(desc: str) -> str:
    """Public pricing should not expose translated group descriptions."""
    _ = desc
    return ""


def sanitize_tag(tag: str) -> str:
    """Normalize model tags for public display."""
    if not tag:
        return ""
    cleaned = _strip_links(tag)
    translated = fallback_english(cleaned)
    return _strip_links(translated) or str(tag).strip()


def sanitize_vendor_name(name: str) -> str:
    """Normalize provider/vendor labels for public display."""
    if not name:
        return ""
    cleaned = _strip_links(name)
    translated = fallback_english(cleaned)
    return _strip_links(translated) or str(name).strip()


def sanitize_public_endpoint(value: str) -> str:
    text = _strip_links(str(value or "").strip())
    if not text:
        return ""
    if text.startswith("/") and "://" not in text and not any(ch.isspace() for ch in text):
        return text
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,80}", text):
        return text
    return ""


def sanitize_endpoint_aliases(items: list[EndpointAlias]) -> list[EndpointAlias]:
    sanitized: list[EndpointAlias] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        public_path = sanitize_public_endpoint(item.public_path or item.key)
        label = sanitize_description(item.label or item.key)
        method = re.sub(r"[^A-Z]", "", str(item.method or "").upper())[:10]
        if not public_path and not label:
            continue
        dedupe_key = (public_path or item.key, label or public_path)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        sanitized.append(
            EndpointAlias(
                key=sanitize_public_endpoint(item.key) or str(item.key or "").strip(),
                label=label or public_path,
                method=method,
                public_path=public_path or str(item.key or "").strip(),
            )
        )
    return sanitized


def sanitize_pricing_variants(
    variants: list[PricingVariant],
    *,
    hidden_group_names: set[str],
    allowed_group_names: set[str] | None,
    group_display_map: dict[str, str],
    group_catalog: dict[str, dict] | None,
) -> list[PricingVariant]:
    sanitized_variants: list[PricingVariant] = []
    for variant in variants:
        variant_group_prices = {}
        for group_name, snapshot in variant.group_prices.items():
            if group_name in hidden_group_names:
                continue
            if allowed_group_names is not None and group_name not in allowed_group_names:
                continue
            catalog_item = (group_catalog or {}).get(group_name, {})
            copy = snapshot.model_copy()
            copy.group_display_name = group_display_map.get(
                group_name,
                sanitize_group_name(
                    group_name,
                    str(catalog_item.get("label_en") or snapshot.group_display_name or group_name),
                ),
            )
            variant_group_prices[group_name] = copy
        filtered_enable_groups = [
            group_name
            for group_name in variant.enable_groups
            if group_name not in hidden_group_names
            and (allowed_group_names is None or group_name in allowed_group_names)
        ]
        if (variant.enable_groups or variant.group_prices) and not filtered_enable_groups and not variant_group_prices:
            continue
        sanitized_variants.append(
            variant.model_copy(
                update={
                    "label": sanitize_description(variant.label),
                    "version": sanitize_description(variant.version),
                    "resolution": sanitize_description(variant.resolution),
                    "description": sanitize_description(variant.description),
                    "enable_groups": filtered_enable_groups,
                    "group_prices": variant_group_prices,
                }
            )
        )
    return sanitized_variants


def sanitize_pricing(
    pricing: NormalizedPricing,
    *,
    group_catalog: dict[str, dict] | None = None,
    hidden_groups: set[str] | None = None,
    excluded_models: set[str] | None = None,
) -> NormalizedPricing:
    """Sanitize the pricing payload for public consumption."""
    sanitized_groups = []
    allowed_group_names = set(group_catalog or {}) if group_catalog is not None else None
    hidden_group_names = set(hidden_groups or set())
    excluded_model_names = set(excluded_models or set())
    for group in pricing.groups:
        catalog_item = (group_catalog or {}).get(group.name, {})
        if group.name in hidden_group_names:
            continue
        if allowed_group_names is not None and group.name not in allowed_group_names:
            continue
        display_name = sanitize_group_name(
            group.name,
            str(catalog_item.get("label_en") or group.display_name or group.name),
        )
        sanitized_groups.append(
            NormalizedGroup(
                name=group.name,
                display_name=display_name,
                ratio=float(group.ratio or 1.0),
                description=sanitize_group_description(
                    str(catalog_item.get("desc") or group.description or "")
                ),
                category=str(catalog_item.get("category") or group.category or "Other"),
            )
        )

    group_display_map = {group.name: group.display_name for group in sanitized_groups}
    sanitized_models = []
    for model in pricing.models:
        if model.model_name in excluded_model_names:
            continue

        new_group_prices = {}
        for group_name, group_price in model.group_prices.items():
            if group_name in hidden_group_names:
                continue
            if allowed_group_names is not None and group_name not in allowed_group_names:
                continue
            catalog_item = (group_catalog or {}).get(group_name, {})
            copy = group_price.model_copy()
            copy.group_display_name = group_display_map.get(
                group_name,
                sanitize_group_name(
                    group_name,
                    str(
                        catalog_item.get("label_en")
                        or group_price.group_display_name
                        or group_name
                    ),
                ),
            )
            new_group_prices[group_name] = copy

        filtered_enable_groups = [
            group_name
            for group_name in model.enable_groups
            if group_name not in hidden_group_names
            and (allowed_group_names is None or group_name in allowed_group_names)
        ]
        had_group_refs = bool(model.enable_groups or model.group_prices)
        if had_group_refs and not filtered_enable_groups and not new_group_prices:
            continue

        sanitized_models.append(
            model.model_copy(
                update={
                    "vendor_name": sanitize_vendor_name(model.vendor_name),
                    "description": sanitize_description(model.description),
                    "supported_endpoints": [
                        endpoint
                        for endpoint in (sanitize_public_endpoint(item) for item in model.supported_endpoints)
                        if endpoint
                    ],
                    "endpoint_aliases": sanitize_endpoint_aliases(model.endpoint_aliases),
                    "tags": [
                        normalized
                        for normalized in (sanitize_tag(tag) for tag in model.tags)
                        if normalized
                    ],
                    "enable_groups": filtered_enable_groups,
                    "group_prices": new_group_prices,
                    "pricing_variants": sanitize_pricing_variants(
                        model.pricing_variants,
                        hidden_group_names=hidden_group_names,
                        allowed_group_names=allowed_group_names,
                        group_display_map=group_display_map,
                        group_catalog=group_catalog,
                    ),
                }
            )
        )

    return NormalizedPricing(
        server_id=pricing.server_id,
        server_name=pricing.server_name,
        models=sanitized_models,
        groups=sanitized_groups,
        fetched_at=pricing.fetched_at,
    )
