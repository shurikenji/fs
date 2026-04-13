from __future__ import annotations

import re

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
ASCII_NAME_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[-_.][A-Za-z0-9]+)*")
READABLE_ASCII_GROUP_RE = re.compile(r"^[A-Za-z0-9]+(?: [A-Za-z0-9]+)*$")
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
GROUP_RATIO_PATTERNS = (
    re.compile(r"(\d+(?:\.\d+)?)\s*(?:cny|usd|rmb|yuan)\s*/\s*(?:token|request|quota|1m|次|刀次)", re.IGNORECASE),
    re.compile(r"(?:倍率|ratio|multiplier)\s*[:=]?\s*(\d+(?:\.\d+)?)", re.IGNORECASE),
    re.compile(r"(?:^|[^\w])x\s*(\d+(?:\.\d+)?)(?:$|[^\w])", re.IGNORECASE),
    re.compile(r"(?:^|[^\w])(\d+(?:\.\d+)?)\s*x(?:$|[^\w])", re.IGNORECASE),
    re.compile(r"\((\d+(?:\.\d+)?)[^)]*(?:cny|usd|rmb|yuan|token|request|quota|1m|x|倍)", re.IGNORECASE),
)
FALLBACK_GROUP_REPLACEMENTS = (
    ("默认分组", "Default Group"),
    ("默认", "Default"),
    ("官方中转", "Official Relay"),
    ("官转", "Official Relay"),
    ("官方", "Official"),
    ("官逆", "Official Reverse"),
    ("逆向", "Reverse"),
    ("无审", "Unfiltered"),
    ("高并发", "High Concurrency"),
    ("低并发", "Low Concurrency"),
    ("高可用", "High Availability"),
    ("企业级", "Enterprise"),
    ("专属", "Dedicated"),
    ("专用", "Dedicated"),
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
CANONICAL_GROUP_LABELS = {
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


def contains_cjk(text: object) -> bool:
    return bool(text and CJK_RE.search(str(text)))


def extract_ratio_hint_from_texts(*texts: object, default: float = 1.0) -> float:
    for text in texts:
        if not text:
            continue
        value = str(text)
        for pattern in GROUP_RATIO_PATTERNS:
            match = pattern.search(value)
            if match:
                try:
                    return float(match.group(1))
                except (TypeError, ValueError):
                    continue
    return default


def strip_group_price_notes(text: object) -> str:
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


def fallback_english_group_name(text: object) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    if not contains_cjk(value):
        return strip_group_price_notes(value)

    for source, target in FALLBACK_GROUP_REPLACEMENTS:
        value = value.replace(source, f" {target} ")

    value = value.replace("（", "(").replace("）", ")")
    value = re.sub(r"[\[\]{}<>]", " ", value)
    value = CJK_RE.sub(" ", value)
    value = re.sub(r"\s*[-_/,:;]+\s*", " ", value)
    value = re.sub(r"\(\s*([^)]+?)\s*\)", r" \1 ", value)
    value = re.sub(r"\s+", " ", value).strip(" -_,.")
    return strip_group_price_notes(value)


def normalize_group_name_for_compare(text: object) -> str:
    value = strip_group_price_notes(text)
    if not value:
        return ""
    value = TRAILING_COMPARE_NUMBER_RE.sub("", value)
    value = re.sub(r"\s+", " ", value).strip(" -_,.")
    return value.lower()


def extract_ascii_name_tokens(text: object) -> list[str]:
    tokens: list[str] = []
    for match in ASCII_NAME_TOKEN_RE.findall(strip_group_price_notes(text)):
        for part in re.split(r"[-_.]+", match):
            normalized = part.strip().lower()
            if normalized:
                tokens.append(normalized)
    return tokens


def canonical_group_label(name: object) -> str:
    value = strip_group_price_notes(name)
    if not value or contains_cjk(value):
        return ""

    normalized = re.sub(r"\s+", " ", value).strip()
    if not READABLE_ASCII_GROUP_RE.fullmatch(normalized):
        return ""

    lowered = normalized.lower()
    if lowered in CANONICAL_GROUP_LABELS:
        return CANONICAL_GROUP_LABELS[lowered]

    parts: list[str] = []
    for part in normalized.split():
        lowered_part = part.lower()
        if lowered_part in CANONICAL_GROUP_LABELS:
            parts.append(CANONICAL_GROUP_LABELS[lowered_part])
        elif any(ch.isupper() for ch in part[1:]) or any(ch.isdigit() for ch in part):
            parts.append(part)
        else:
            parts.append(part[:1].upper() + part[1:])
    return " ".join(parts)


def is_context_derived_group_name(name_en: object, *, original_name: object, context_text: object) -> bool:
    current_name = normalize_group_name_for_compare(name_en)
    original_text = str(original_name or "").strip()
    if not current_name or not contains_cjk(original_text):
        return False

    original_fallback = normalize_group_name_for_compare(fallback_english_group_name(original_text))
    context_fallback = normalize_group_name_for_compare(fallback_english_group_name(context_text))
    original_tokens = extract_ascii_name_tokens(original_text)
    current_tokens = set(extract_ascii_name_tokens(name_en))

    if original_fallback and context_fallback and current_name == context_fallback and current_name != original_fallback:
        return True

    if original_tokens and not set(original_tokens).issubset(current_tokens):
        return True

    return current_name in GENERIC_CONTEXT_LABELS and current_name != original_fallback


def sanitize_group_display_name(name: object, display_name: object = "") -> str:
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

    if original and not contains_cjk(original):
        return original

    if preferred and preferred != original:
        if not contains_cjk(preferred) and not is_context_derived_group_name(
            preferred,
            original_name=original,
            context_text=display_name or preferred,
        ):
            return preferred
        translated_preferred = fallback_english_group_name(preferred)
        if translated_preferred and not contains_cjk(translated_preferred) and not is_context_derived_group_name(
            translated_preferred,
            original_name=original,
            context_text=display_name or preferred,
        ):
            return translated_preferred

    if original:
        fallback_original = fallback_english_group_name(original)
        if fallback_original:
            return fallback_original

    return fallback_english_group_name(preferred) or preferred
