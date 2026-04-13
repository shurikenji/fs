"""RixAPI adapter — servers like 996444.cn.

RixAPI pricing endpoint returns both group_info and model_info inline.
Group ratios are embedded in group_info with GroupRatio field.
Supports group chain natively.
"""
from __future__ import annotations

import logging

from app.adapters.newapi import NewApiAdapter
from app.sanitizer import strip_group_price_notes

logger = logging.getLogger(__name__)


class RixApiAdapter(NewApiAdapter):
    """RixAPI is a superset of NewAPI with inline group ratios.

    The normalize logic in NewApiAdapter already handles the RixAPI
    ``group_info`` / ``model_info`` structure, so we inherit directly.
    The only difference is RixAPI does NOT need ``/api/ratio_config``.
    """

    async def fetch_pricing(self, server: dict) -> "NormalizedPricing":  # noqa: F821
        from app.adapters.base import build_headers, join_url, _TIMEOUT
        import aiohttp

        headers = build_headers(server)
        url = join_url(server["base_url"], server.get("pricing_path") or "/api/pricing")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=_TIMEOUT) as resp:
                    pricing_data = await resp.json()
                    if not isinstance(pricing_data, dict):
                        pricing_data = {}
        except Exception as exc:
            logger.error("RixAPI fetch %s failed: %s", url, exc)
            pricing_data = {}

        # RixAPI has everything inline — no ratio_config needed
        return self._normalize(server, pricing_data, {})

    def get_groups_path(self, server: dict) -> str:
        return str(server.get("groups_path") or "/api/token/group").strip()

    def parse_groups(self, data: dict) -> list[dict]:
        """Ported from shopbot RixAPI client group parsing."""
        groups: list[dict] = []

        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    name = (
                        item.get("value")
                        or item.get("group")
                        or item.get("name")
                        or item.get("key")
                        or "unknown"
                    )
                    raw_label = item.get("key") or item.get("label") or ""
                    cleaned_label = strip_group_price_notes(raw_label)
                    raw_desc = item.get("desc") or item.get("description") or cleaned_label
                    explicit_ratio = item.get("ratio")
                    if explicit_ratio in (None, ""):
                        explicit_ratio = item.get("multiplier")
                    groups.append(
                        {
                            "name": name,
                            "name_en": strip_group_price_notes(item.get("name_en") or cleaned_label),
                            "ratio": explicit_ratio if explicit_ratio not in (None, "") else self.extract_ratio_hint(raw_label, raw_desc, name),
                            "desc": raw_desc,
                            "translation_source": cleaned_label or name,
                            "ratio_source": str(raw_label or raw_desc or name),
                        }
                    )
        elif isinstance(data, dict):
            for name, info in data.items():
                if isinstance(info, dict):
                    cleaned_name_en = strip_group_price_notes(info.get("name_en") or "")
                    raw_desc = str(info.get("desc") or "")
                    groups.append(
                        {
                            "name": name,
                            "name_en": cleaned_name_en,
                            "ratio": info.get("ratio") if info.get("ratio") not in (None, "") else self.extract_ratio_hint(raw_desc, name),
                            "desc": raw_desc,
                            "translation_source": strip_group_price_notes(cleaned_name_en or info.get("desc") or name),
                            "ratio_source": raw_desc or name,
                        }
                    )
                else:
                    groups.append(
                        {
                            "name": name,
                            "name_en": None,
                            "ratio": 1.0,
                            "desc": "",
                            "translation_source": name,
                            "ratio_source": name,
                        }
                    )

        return groups
