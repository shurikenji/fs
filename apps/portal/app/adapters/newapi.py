"""NewAPI adapter — servers like AABao, KKSJ, XJAI.

These servers expose:
  /api/pricing      → model list with quota_type, model_ratio, etc.
  /api/ratio_config → model_ratio, completion_ratio, cache_ratio (optional)

Pricing formula (token-based):
  input_usd_per_1M  = 2 * group_ratio * model_ratio
  output_usd_per_1M = 2 * group_ratio * model_ratio * completion_ratio
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

import aiohttp

from app.adapters.base import (
    BaseAdapter,
    extract_ratio_hint,
    build_headers,
    compute_token_prices,
    infer_endpoints,
    infer_pricing_mode,
    join_url,
    normalize_tags,
    _TIMEOUT,
)
from app.server_profiles import resolve_server_profile
from app.schemas import (
    EndpointAlias,
    GroupPriceSnapshot,
    NormalizedGroup,
    NormalizedModel,
    NormalizedPricing,
    PricingVariant,
    PricingMode,
)
from app.yunwu_pricing import (
    is_yunwu_profile,
    yunwu_billing_profile,
    yunwu_multiplier,
)

logger = logging.getLogger(__name__)


class NewApiAdapter(BaseAdapter):
    """Adapter for standard NewAPI / OneAPI servers."""

    async def fetch_pricing(self, server: dict) -> NormalizedPricing:
        headers = build_headers(server)
        pricing_data = await self._fetch_json(server, server.get("pricing_path") or "/api/pricing", headers)
        ratio_data: dict = {}
        if server.get("ratio_config_enabled"):
            ratio_data = await self._fetch_json(server, server.get("ratio_config_path") or "/api/ratio_config", headers)

        return self._normalize(server, pricing_data, ratio_data)

    # ── internal helpers ─────────────────────────────────────────────────

    async def _fetch_json(self, server: dict, path: str, headers: dict) -> dict:
        url = join_url(server["base_url"], path)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=_TIMEOUT) as resp:
                    data = await resp.json()
                    return data if isinstance(data, dict) else {}
        except Exception as exc:
            logger.error("NewAPI fetch %s failed: %s", url, exc)
            return {}

    def _normalize(
        self,
        server: dict,
        pricing_raw: dict | list,
        ratio_raw: dict,
    ) -> NormalizedPricing:
        now = datetime.now(timezone.utc).isoformat()
        runtime_profile = resolve_server_profile(server, pricing_raw)
        parser_id = str(runtime_profile.get("parser_id") or "")

        # --- Parse ratio_config if available ---
        ratio_map = self._build_ratio_map(ratio_raw)

        # --- Parse groups from pricing data ---
        groups_dict: dict[str, NormalizedGroup] = {}
        raw_data = pricing_raw.get("data", pricing_raw) if isinstance(pricing_raw, dict) else pricing_raw
        owner_map = raw_data.get("owner_by", {}) if isinstance(raw_data, dict) else {}
        model_completion_map = raw_data.get("model_completion_ratio", {}) if isinstance(raw_data, dict) else {}
        group_special_map = raw_data.get("group_special", {}) if isinstance(raw_data, dict) else {}
        model_group_map = raw_data.get("model_group", {}) if isinstance(raw_data, dict) else {}
        supported_endpoint_catalog = pricing_raw.get("supported_endpoint", {}) if isinstance(pricing_raw, dict) else {}
        vendor_map = self._build_vendor_map(pricing_raw)

        # RixAPI-style inline group_info
        group_info = raw_data.get("group_info", {}) if isinstance(raw_data, dict) else {}
        for gname, ginfo in group_info.items():
            if isinstance(ginfo, dict):
                groups_dict[gname] = NormalizedGroup(
                    name=gname,
                    display_name=ginfo.get("DisplayName", gname),
                    ratio=float(ginfo.get("GroupRatio", 1.0)),
                    description=ginfo.get("Description", ""),
                )

        # NewAPI/AABao-style top-level group metadata
        group_ratio = pricing_raw.get("group_ratio", {})
        usable_group = pricing_raw.get("usable_group", {})
        if isinstance(group_ratio, dict) or isinstance(usable_group, dict):
            group_names = set()
            if isinstance(group_ratio, dict):
                group_names.update(str(name) for name in group_ratio.keys())
            if isinstance(usable_group, dict):
                group_names.update(str(name) for name in usable_group.keys())
            for gname in sorted(group_names):
                description = str(usable_group.get(gname, "")) if isinstance(usable_group, dict) else ""
                groups_dict[gname] = NormalizedGroup(
                    name=gname,
                    display_name=self._group_display_name(gname, description),
                    ratio=self._to_float(
                        group_ratio.get(gname) if isinstance(group_ratio, dict) else None,
                        default=extract_ratio_hint(description, default=1.0),
                    ),
                    description=description,
                )

        # Alternative NewAPI shape:
        # data.model_group = {
        #   "<group_name>": {"DisplayName": "...", "GroupRatio": 1.0, "ModelPrice": {...}}
        # }
        if isinstance(model_group_map, dict):
            for gname, ginfo in model_group_map.items():
                if not isinstance(ginfo, dict):
                    continue
                display_name = (
                    ginfo.get("DisplayName")
                    or ginfo.get("display_name")
                    or gname
                )
                description = (
                    ginfo.get("Description")
                    or ginfo.get("description")
                    or display_name
                )
                groups_dict[str(gname)] = NormalizedGroup(
                    name=str(gname),
                    display_name=str(display_name),
                    ratio=self._to_float(
                        ginfo.get("GroupRatio") or ginfo.get("group_ratio"),
                        default=extract_ratio_hint(description, display_name, gname, default=1.0),
                    ),
                    description=str(description),
                )

        # --- Parse models ---
        models: list[NormalizedModel] = []
        model_list: list[dict] = []
        if isinstance(raw_data, dict):
            candidate = raw_data.get("model_info") or raw_data.get("data") or []
            if isinstance(candidate, list):
                model_list = [item for item in candidate if isinstance(item, dict)]
            elif isinstance(candidate, dict):
                model_list = [
                    {
                        **item,
                        "model_name": item.get("model_name") or item.get("name") or model_name,
                    }
                    for model_name, item in candidate.items()
                    if isinstance(item, dict)
                ]
        elif isinstance(raw_data, list):
            model_list = [item for item in raw_data if isinstance(item, dict)]
        if not isinstance(model_list, list):
            model_list = []

        for entry in model_list:
            if not isinstance(entry, dict):
                continue
            model_name = entry.get("model_name") or ""
            if not model_name:
                continue

            # Get ratio data (prefer ratio_config, fallback to pricing inline)
            ratio_info = ratio_map.get(model_name, {})

            # Extract price_info — first group's default pricing as base
            price_info = entry.get("price_info", {})
            base_pricing = self._extract_base_pricing(price_info, ratio_info, entry)

            model_ratio = base_pricing["model_ratio"]
            cache_ratio = base_pricing["cache_ratio"]
            model_price = base_pricing["model_price"]
            quota_type = base_pricing["quota_type"]

            # Tags
            raw_tags = entry.get("tags")
            tags = normalize_tags(raw_tags)
            if "thinking" in model_name.lower() and "thinking" not in tags:
                tags.append("thinking")

            completion_ratio = self._resolve_completion_ratio(
                model_name,
                base_pricing["completion_ratio"] or self._to_float(model_completion_map.get(model_name)),
                tags,
            )

            pricing_mode = infer_pricing_mode(quota_type, model_price, model_ratio, completion_ratio)
            display_values = self._compute_display_values(
                parser_id=parser_id,
                model_name=model_name,
                quota_type=quota_type,
                pricing_mode=pricing_mode,
                model_ratio=model_ratio,
                completion_ratio=completion_ratio,
                cache_ratio=cache_ratio,
                model_price=model_price,
                group_ratio=1.0,
            )
            input_p = display_values["input_price_per_1m"]
            output_p = display_values["output_price_per_1m"]
            cached_p = display_values["cached_input_price_per_1m"]
            request_p = display_values["request_price"]
            billing_label = str(display_values["billing_label"] or "")
            billing_unit = str(display_values["billing_unit"] or "")
            price_multiplier = display_values["price_multiplier"]

            # Endpoints
            endpoints, endpoint_aliases = self._resolve_public_endpoints(
                entry.get("supported_endpoint_types"),
                self._resolve_endpoint_specs(
                    entry.get("endpoints"),
                    supported_endpoint_catalog,
                    entry.get("supported_endpoint_types"),
                ),
                model_name,
                tags,
                runtime_profile.get("endpoint_alias_map") or {},
            )

            # Enable groups
            enable_groups = entry.get("enable_groups") or []
            if not enable_groups and isinstance(price_info, dict):
                enable_groups = [str(name) for name in price_info.keys()]
            if not enable_groups and isinstance(group_special_map, dict):
                groups = group_special_map.get(model_name) or []
                if isinstance(groups, list):
                    enable_groups = [str(name) for name in groups if str(name).strip()]
            if isinstance(model_group_map, dict):
                for gname, ginfo in model_group_map.items():
                    if not isinstance(ginfo, dict):
                        continue
                    model_price_map = ginfo.get("ModelPrice") or ginfo.get("model_price") or {}
                    if isinstance(model_price_map, dict) and model_name in model_price_map:
                        enable_groups.append(str(gname))
            enable_groups = [str(name) for name in enable_groups if str(name).strip()]
            enable_groups = list(dict.fromkeys(enable_groups))

            # Per-group prices
            group_prices: dict[str, GroupPriceSnapshot] = {}
            for gname in enable_groups:
                g = groups_dict.get(gname)
                gr = g.ratio if g else 1.0
                gp_pricing = self._extract_group_pricing(
                    price_info,
                    gname,
                    ratio_info,
                    entry,
                    model_group_map=model_group_map,
                    model_name=model_name,
                    model_completion_map=model_completion_map,
                )
                gp_completion_ratio = self._resolve_completion_ratio(
                    model_name,
                    gp_pricing["completion_ratio"],
                    tags,
                )
                gp_mode = infer_pricing_mode(
                    gp_pricing["quota_type"], gp_pricing["model_price"],
                    gp_pricing["model_ratio"], gp_completion_ratio,
                )
                group_display_values = self._compute_display_values(
                    parser_id=parser_id,
                    model_name=model_name,
                    quota_type=gp_pricing["quota_type"],
                    pricing_mode=gp_mode,
                    model_ratio=gp_pricing["model_ratio"],
                    completion_ratio=gp_completion_ratio,
                    cache_ratio=gp_pricing["cache_ratio"],
                    model_price=gp_pricing["model_price"],
                    group_ratio=gr,
                )
                snap = GroupPriceSnapshot(
                    group_name=gname,
                    group_display_name=g.display_name if g else gname,
                    group_ratio=gr,
                    pricing_mode=group_display_values["pricing_mode"],
                )
                snap.input_price_per_1m = group_display_values["input_price_per_1m"]
                snap.output_price_per_1m = group_display_values["output_price_per_1m"]
                snap.cached_input_price_per_1m = group_display_values["cached_input_price_per_1m"]
                snap.request_price = group_display_values["request_price"]
                group_prices[gname] = snap

            pricing_variants = self._build_pricing_variants(
                entry=entry,
                enable_groups=enable_groups,
                group_prices=group_prices,
                display_profile=str(runtime_profile.get("display_profile") or "flat"),
                variant_pricing_mode=str(runtime_profile.get("variant_pricing_mode") or ""),
                billing_label=billing_label,
                billing_unit=billing_unit,
            )
            display_mode = "variant_matrix" if pricing_variants else "flat"
            variant_request = self._min_variant_request_price(pricing_variants)
            summary_group_prices = self._summarize_variant_group_prices(pricing_variants, group_prices)
            if variant_request is not None:
                request_p = variant_request
            if summary_group_prices:
                group_prices = summary_group_prices

            models.append(NormalizedModel(
                model_name=model_name,
                description=entry.get("description", ""),
                icon=entry.get("icon", ""),
                tags=tags,
                vendor_name=self._resolve_vendor_name(entry, owner_map, vendor_map),
                display_mode=display_mode,
                billing_label=billing_label,
                billing_unit=billing_unit,
                price_multiplier=price_multiplier if isinstance(price_multiplier, (float, int)) else None,
                pricing_mode=pricing_mode,
                model_ratio=model_ratio,
                completion_ratio=completion_ratio,
                cache_ratio=cache_ratio,
                model_price=model_price,
                enable_groups=enable_groups,
                supported_endpoints=endpoints,
                endpoint_aliases=endpoint_aliases,
                input_price_per_1m=input_p,
                output_price_per_1m=output_p,
                cached_input_price_per_1m=cached_p,
                request_price=request_p,
                group_prices=group_prices,
                pricing_variants=pricing_variants,
            ))

        return NormalizedPricing(
            server_id=server["id"],
            server_name=server["name"],
            models=models,
            groups=list(groups_dict.values()),
            fetched_at=now,
        )

    def _build_ratio_map(self, ratio_raw: dict) -> dict[str, dict]:
        ratio_map: dict[str, dict] = {}
        if not ratio_raw:
            return ratio_map

        data = ratio_raw.get("data", ratio_raw)
        if not isinstance(data, dict):
            return ratio_map

        # Shape A: {model_id: {model_ratio, completion_ratio, ...}}
        for model_id, info in data.items():
            if isinstance(info, dict) and any(
                key in info for key in ("model_ratio", "completion_ratio", "cache_ratio", "model_price", "quota_type")
            ):
                ratio_map[str(model_id)] = info

        # Shape B: {model_ratio: {...}, completion_ratio: {...}, ...}
        grouped_fields = {
            "model_ratio": data.get("model_ratio"),
            "completion_ratio": data.get("completion_ratio"),
            "cache_ratio": data.get("cache_ratio"),
            "model_price": data.get("model_price"),
            "quota_type": data.get("quota_type"),
        }
        if any(isinstance(value, dict) for value in grouped_fields.values()):
            model_names: set[str] = set()
            for value in grouped_fields.values():
                if isinstance(value, dict):
                    model_names.update(str(name) for name in value.keys())
            for model_name in model_names:
                info = ratio_map.setdefault(model_name, {})
                for field_name, field_value in grouped_fields.items():
                    if isinstance(field_value, dict) and model_name in field_value:
                        info[field_name] = field_value[model_name]

        return ratio_map

    def _group_display_name(self, group_name: str, description: str) -> str:
        if not description:
            return group_name
        head = description.split("（", 1)[0].strip()
        return head or group_name

    def _is_single_sided_token_model(self, model_name: str, tags: list[str]) -> bool:
        lower_name = model_name.lower()
        if any(tag in {"audio", "rerank"} for tag in tags):
            return True
        return any(
            hint in lower_name
            for hint in (
                "embedding",
                "whisper",
                "tts-",
                "tts_",
                "speech",
                "transcription",
                "rerank",
                "moderation",
            )
        )

    def _resolve_completion_ratio(self, model_name: str, completion_ratio: float, tags: list[str]) -> float:
        if completion_ratio > 0:
            return completion_ratio
        if self._is_single_sided_token_model(model_name, tags):
            return 0.0
        # Some upstream NewAPI servers omit completion_ratio for chat models.
        # Missing should not be interpreted as free output.
        return 1.0

    def _to_float(self, value: object, *, default: float = 0.0) -> float:
        try:
            if value is None or value == "":
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def _default_billing_profile(self, pricing_mode: PricingMode) -> tuple[str, str]:
        if pricing_mode == PricingMode.token:
            return "Per token", ""
        return "Per request", "request"

    def _compute_display_values(
        self,
        *,
        parser_id: str,
        model_name: str,
        quota_type: int,
        pricing_mode: PricingMode,
        model_ratio: float,
        completion_ratio: float,
        cache_ratio: float | None,
        model_price: float,
        group_ratio: float,
    ) -> dict[str, float | str | PricingMode | None]:
        if pricing_mode == PricingMode.token and model_ratio > 0:
            prices = compute_token_prices(model_ratio, max(completion_ratio, 0.0), group_ratio, cache_ratio)
            label, unit = (
                yunwu_billing_profile(model_name, quota_type)
                if is_yunwu_profile(parser_id)
                else self._default_billing_profile(PricingMode.token)
            )
            return {
                "pricing_mode": PricingMode.token,
                "input_price_per_1m": prices["input"],
                "output_price_per_1m": None if completion_ratio <= 0 else prices["output"],
                "cached_input_price_per_1m": prices["cached"],
                "request_price": None,
                "billing_label": label,
                "billing_unit": unit,
                "price_multiplier": None,
            }

        multiplier = 1.0
        label, unit = self._default_billing_profile(pricing_mode)
        if is_yunwu_profile(parser_id):
            multiplier = yunwu_multiplier(model_name, quota_type, model_ratio)
            label, unit = yunwu_billing_profile(model_name, quota_type)
        elif pricing_mode == PricingMode.fixed:
            label, unit = self._default_billing_profile(PricingMode.fixed)

        request_price = None
        if pricing_mode == PricingMode.fixed and model_price > 0:
            request_price = round(model_price * group_ratio * multiplier, 6)

        return {
            "pricing_mode": pricing_mode,
            "input_price_per_1m": None,
            "output_price_per_1m": None,
            "cached_input_price_per_1m": None,
            "request_price": request_price,
            "billing_label": label,
            "billing_unit": unit,
            "price_multiplier": None if abs(multiplier - 1.0) < 1e-9 else multiplier,
        }

    def _extract_base_pricing(self, price_info: dict, ratio_info: dict, entry: dict | None = None) -> dict:
        """Extract base pricing from first available group or ratio_config."""
        model_ratio = self._to_float(ratio_info.get("model_ratio"))
        completion_ratio = self._to_float(ratio_info.get("completion_ratio"))
        cache_ratio_val = ratio_info.get("cache_ratio")
        cache_ratio = self._to_float(cache_ratio_val, default=0.0) if cache_ratio_val is not None else None
        model_price = self._to_float(ratio_info.get("model_price"))
        quota_type = int(self._to_float(ratio_info.get("quota_type"), default=1))

        if entry:
            if model_ratio <= 0:
                model_ratio = self._to_float(entry.get("model_ratio"))
            if completion_ratio <= 0:
                completion_ratio = self._to_float(entry.get("completion_ratio"))
            if model_price <= 0:
                model_price = self._to_float(entry.get("model_price"))
            if quota_type == 1 and entry.get("quota_type") is not None:
                quota_type = int(self._to_float(entry.get("quota_type"), default=1))

        # If ratio_config has values, use them
        if model_ratio > 0 or model_price > 0:
            return {
                "model_ratio": model_ratio,
                "completion_ratio": completion_ratio,
                "cache_ratio": cache_ratio,
                "model_price": model_price,
                "quota_type": quota_type,
            }

        # Fallback: extract from first group in price_info
        for _gname, gdata in (price_info or {}).items():
            if isinstance(gdata, dict):
                default = gdata.get("default", gdata)
                if isinstance(default, dict):
                    return {
                        "model_ratio": self._to_float(default.get("model_ratio")),
                        "completion_ratio": self._to_float(default.get("model_completion_ratio")),
                        "cache_ratio": self._to_float(cr, default=0.0) if (cr := default.get("model_cache_ratio")) is not None else None,
                        "model_price": self._to_float(default.get("model_price")),
                        "quota_type": int(self._to_float(default.get("quota_type"), default=1)),
                    }
            break

        return {"model_ratio": 0, "completion_ratio": 0, "cache_ratio": None, "model_price": 0, "quota_type": 1}

    def _extract_group_pricing(
        self,
        price_info: dict,
        group_name: str,
        ratio_info: dict,
        entry: dict | None = None,
        *,
        model_group_map: dict | None = None,
        model_name: str = "",
        model_completion_map: dict | None = None,
    ) -> dict:
        """Extract pricing for a specific group."""
        gdata = (price_info or {}).get(group_name, {})
        if isinstance(gdata, dict) and gdata:
            default = gdata.get("default", gdata)
            if isinstance(default, dict) and default:
                return {
                    "model_ratio": self._to_float(default.get("model_ratio")),
                    "completion_ratio": self._to_float(default.get("model_completion_ratio")),
                    "cache_ratio": self._to_float(cr, default=0.0) if (cr := default.get("model_cache_ratio")) is not None else None,
                    "model_price": self._to_float(default.get("model_price")),
                        "quota_type": int(self._to_float(default.get("quota_type"), default=1)),
                }
        group_pricing = self._extract_group_pricing_from_model_group(
            model_group_map or {},
            group_name,
            model_name,
            model_completion_map or {},
        )
        if group_pricing is not None:
            return group_pricing
        # Fallback to ratio_config
        return self._extract_base_pricing(price_info, ratio_info, entry)

    def _extract_group_pricing_from_model_group(
        self,
        model_group_map: dict,
        group_name: str,
        model_name: str,
        model_completion_map: dict,
    ) -> dict | None:
        group_info = model_group_map.get(group_name) if isinstance(model_group_map, dict) else None
        if not isinstance(group_info, dict):
            return None

        model_price_map = group_info.get("ModelPrice") or group_info.get("model_price") or {}
        if not isinstance(model_price_map, dict):
            return None

        override = model_price_map.get(model_name)
        if not isinstance(override, dict):
            return None

        price_type = int(self._to_float(override.get("priceType"), default=0))
        price = self._to_float(override.get("price"))
        completion_ratio = self._to_float(model_completion_map.get(model_name))

        if price <= 0:
            return None

        if price_type == 0:
            return {
                "model_ratio": price,
                "completion_ratio": completion_ratio,
                "cache_ratio": None,
                "model_price": 0.0,
                "quota_type": 1,
            }

        return {
            "model_ratio": 0.0,
            "completion_ratio": completion_ratio,
            "cache_ratio": None,
            "model_price": price,
            "quota_type": 0,
        }

    def _build_vendor_map(self, pricing_raw: Any) -> dict[str, str]:
        if not isinstance(pricing_raw, dict):
            return {}
        vendors = pricing_raw.get("vendors")
        if not isinstance(vendors, list):
            return {}

        out: dict[str, str] = {}
        for item in vendors:
            if not isinstance(item, dict):
                continue
            vendor_id = str(item.get("id") or "").strip()
            vendor_name = str(item.get("name") or "").strip()
            if vendor_id and vendor_name:
                out[vendor_id] = vendor_name
        return out

    def _resolve_endpoint_specs(
        self,
        entry_endpoints: Any,
        supported_endpoint_catalog: Any,
        supported_types: Any,
    ) -> Any:
        if entry_endpoints:
            return entry_endpoints
        if not isinstance(supported_endpoint_catalog, dict):
            return {}

        normalized_types = self._normalize_supported_types(supported_types)
        subset: dict[str, Any] = {}
        for type_name in normalized_types:
            if type_name in supported_endpoint_catalog:
                subset[type_name] = supported_endpoint_catalog[type_name]
        return subset

    def _normalize_supported_types(self, supported_types: Any) -> list[str]:
        if isinstance(supported_types, str):
            value = supported_types.strip()
            return [value] if value else []
        if isinstance(supported_types, list):
            return [str(item).strip() for item in supported_types if str(item).strip()]
        return []

    def _resolve_public_endpoints(
        self,
        supported_types: Any,
        endpoint_specs: Any,
        model_name: str,
        tags: list[str],
        endpoint_alias_map: dict[str, dict[str, str]],
    ) -> tuple[list[str], list[EndpointAlias]]:
        endpoints: list[str] = []
        aliases: list[EndpointAlias] = []
        specs = endpoint_specs if isinstance(endpoint_specs, dict) else {}

        def add_endpoint(value: str) -> None:
            text = str(value or "").strip()
            if text and text not in endpoints:
                endpoints.append(text)

        def add_alias(alias: EndpointAlias) -> None:
            if any(existing.key == alias.key and existing.public_path == alias.public_path for existing in aliases):
                return
            aliases.append(alias)

        normalized_types = self._normalize_supported_types(supported_types)
        for type_name in normalized_types:
            spec = specs.get(type_name)
            alias_config = endpoint_alias_map.get(type_name, {})
            label = str(alias_config.get("label") or self._humanize_endpoint_type(type_name)).strip()
            public_path = ""
            method = str(alias_config.get("method") or "").strip().upper()
            if isinstance(spec, dict):
                raw_path = str(spec.get("path") or "").strip()
                raw_method = str(spec.get("method") or "").strip().upper()
                if raw_path.startswith("/"):
                    public_path = raw_path
                if raw_method:
                    method = raw_method
            elif isinstance(spec, str):
                raw_path = str(spec).strip()
                if raw_path.startswith("/"):
                    public_path = raw_path
            if not public_path:
                public_path = str(alias_config.get("public_path") or "").strip()
            if public_path:
                add_endpoint(public_path)
            elif type_name:
                add_endpoint(type_name)
            add_alias(
                EndpointAlias(
                    key=type_name,
                    label=label,
                    method=method,
                    public_path=public_path or type_name,
                )
            )

        if not endpoints:
            inferred = infer_endpoints(supported_types, None, model_name, tags)
            for endpoint in inferred:
                add_endpoint(endpoint)

        for key, spec in specs.items():
            type_name = str(key or "").strip()
            if not type_name:
                continue
            alias_config = endpoint_alias_map.get(type_name, {})
            safe_method = str(alias_config.get("method") or "").strip().upper()
            public_path = ""
            raw_path = ""
            if isinstance(spec, dict):
                raw_path = str(spec.get("path") or "").strip()
                safe_method = safe_method or str(spec.get("method") or "").strip().upper()
            elif isinstance(spec, str):
                raw_path = str(spec).strip()
            if raw_path.startswith("/"):
                public_path = raw_path
            elif not endpoints and type_name:
                public_path = str(alias_config.get("public_path") or "").strip() or type_name
            if public_path:
                add_endpoint(public_path)
            add_alias(
                EndpointAlias(
                    key=type_name,
                    label=str(alias_config.get("label") or self._humanize_endpoint_type(type_name)).strip(),
                    method=safe_method,
                    public_path=public_path or type_name,
                )
            )

        if not aliases:
            for endpoint in endpoints:
                add_alias(
                    EndpointAlias(
                        key=endpoint,
                        label=self._humanize_endpoint_type(endpoint),
                        public_path=endpoint,
                    )
                )
        return endpoints, aliases

    def _humanize_endpoint_type(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        text = re.sub(r"[/_]+", " ", text)
        text = text.replace("-", " ")
        text = text.replace("异步", " async")
        text = re.sub(r"\s+", " ", text).strip()
        if text.lower() == "aigc image":
            return "AIGC Image"
        if text.lower() == "aigc video":
            return "AIGC Video"
        return " ".join(part[:1].upper() + part[1:] if part else "" for part in text.split())

    def _build_pricing_variants(
        self,
        *,
        entry: dict[str, Any],
        enable_groups: list[str],
        group_prices: dict[str, GroupPriceSnapshot],
        display_profile: str,
        variant_pricing_mode: str,
        billing_label: str,
        billing_unit: str,
    ) -> list[PricingVariant]:
        if display_profile != "variant_matrix" and not variant_pricing_mode:
            return []

        raw_variants = self._extract_raw_variants(entry, variant_pricing_mode)
        if not raw_variants:
            return []

        variants: list[PricingVariant] = []
        for index, item in enumerate(raw_variants, start=1):
            normalized = self._normalize_variant_entry(item, index=index)
            if not normalized:
                continue
            request_price = normalized["request_price"]
            variant_group_prices = self._build_variant_group_prices(
                request_price=request_price,
                enable_groups=enable_groups,
                group_prices=group_prices,
            )
            variants.append(
                PricingVariant(
                    key=normalized["key"],
                    label=normalized["label"],
                    version=normalized["version"],
                    resolution=normalized["resolution"],
                    description=normalized["description"],
                    billing_label=billing_label,
                    billing_unit=billing_unit,
                    pricing_mode=PricingMode.fixed,
                    request_price=request_price,
                    enable_groups=list(enable_groups),
                    group_prices=variant_group_prices,
                )
            )
        return variants

    def _extract_raw_variants(self, entry: dict[str, Any], variant_pricing_mode: str) -> list[dict[str, Any]]:
        del variant_pricing_mode
        candidates = (
            "pricing_variants",
            "price_variants",
            "variants",
            "variant_prices",
            "variant_pricing",
            "tier_prices",
            "price_tiers",
            "resolutions",
            "versions",
        )
        for key in candidates:
            value = entry.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []

    def _normalize_variant_entry(self, item: dict[str, Any], *, index: int) -> dict[str, Any] | None:
        request_price = self._to_float(
            item.get("request_price")
            or item.get("model_price")
            or item.get("price")
            or item.get("amount")
            or item.get("cost")
        )
        if request_price <= 0:
            return None
        return {
            "key": str(item.get("key") or item.get("id") or item.get("name") or f"variant-{index}").strip(),
            "label": str(item.get("label") or item.get("name") or item.get("title") or "").strip(),
            "version": str(item.get("version") or item.get("model_version") or "").strip(),
            "resolution": str(item.get("resolution") or item.get("size") or item.get("quality") or "").strip(),
            "description": str(item.get("description") or item.get("note") or "").strip(),
            "request_price": round(request_price, 6),
        }

    def _build_variant_group_prices(
        self,
        *,
        request_price: float,
        enable_groups: list[str],
        group_prices: dict[str, GroupPriceSnapshot],
    ) -> dict[str, GroupPriceSnapshot]:
        out: dict[str, GroupPriceSnapshot] = {}
        for group_name in enable_groups:
            base = group_prices.get(group_name)
            out[group_name] = GroupPriceSnapshot(
                group_name=group_name,
                group_display_name=base.group_display_name if base else group_name,
                group_ratio=float(base.group_ratio if base else 1.0),
                pricing_mode=PricingMode.fixed,
                request_price=request_price,
            )
        return out

    def _min_variant_request_price(self, variants: list[PricingVariant]) -> float | None:
        prices = [float(variant.request_price) for variant in variants if variant.request_price is not None]
        if not prices:
            return None
        return min(prices)

    def _summarize_variant_group_prices(
        self,
        variants: list[PricingVariant],
        fallback: dict[str, GroupPriceSnapshot],
    ) -> dict[str, GroupPriceSnapshot]:
        summary: dict[str, GroupPriceSnapshot] = {}
        for variant in variants:
            for group_name, snapshot in variant.group_prices.items():
                current = summary.get(group_name)
                if current is None or (
                    snapshot.request_price is not None
                    and (current.request_price is None or snapshot.request_price < current.request_price)
                ):
                    summary[group_name] = snapshot.model_copy()
        return summary or fallback

    def _resolve_vendor_name(self, entry: dict, owner_map: dict, vendor_map: dict[str, str] | None = None) -> str:
        supplier = str(entry.get("supplier") or entry.get("owner_by") or "").strip()
        if supplier and isinstance(owner_map, dict):
            owner_info = owner_map.get(supplier)
            if isinstance(owner_info, dict):
                owner_key = str(owner_info.get("key") or "").strip()
                if owner_key and not any("\u3400" <= ch <= "\u9fff" for ch in owner_key):
                    return self._humanize_provider_key(owner_key)
                owner_name = str(owner_info.get("name") or "").strip()
                if owner_name:
                    return owner_name
        vendor_id = str(entry.get("vendor_id") or "").strip()
        if vendor_id and isinstance(vendor_map, dict):
            vendor_name = str(vendor_map.get(vendor_id) or "").strip()
            if vendor_name:
                return vendor_name
        if supplier and not any("\u3400" <= ch <= "\u9fff" for ch in supplier):
            return self._humanize_provider_key(supplier)
        return supplier

    def _humanize_provider_key(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        text = text.replace("_", " ").replace("/", " ").replace("-", " ")
        text = " ".join(part for part in text.split() if part)
        if not text:
            return value
        return " ".join(
            part if any(ch.isupper() for ch in part[1:]) else part[:1].upper() + part[1:]
            for part in text.split()
        )

    async def fetch_groups(self, server: dict) -> list[dict]:
        groups = await super().fetch_groups(server)
        if groups or server.get("groups_path"):
            return groups

        fallback_server = {**server, "groups_path": "/api/token/group"}
        return await super().fetch_groups(fallback_server)

    def parse_groups(self, data: dict) -> list[dict]:
        """Ported from shopbot NewAPI client group parsing."""
        groups: list[dict] = []

        if (
            isinstance(data, dict)
            and isinstance(data.get("data"), dict)
            and isinstance(data.get("ratios"), dict)
        ):
            descriptions = data.get("data", {})
            ratios = data.get("ratios", {})
            for name, desc in descriptions.items():
                groups.append(
                    {
                        "name": name,
                        "ratio": ratios.get(name, 1.0),
                        "desc": desc if isinstance(desc, str) else "",
                        "translation_source": desc if isinstance(desc, str) else name,
                    }
                )
            return groups

        if isinstance(data, dict):
            for name, info in data.items():
                if isinstance(info, dict):
                    groups.append(
                        {
                            "name": name,
                            "ratio": info.get("ratio", 1.0),
                            "desc": info.get("desc", ""),
                            "translation_source": info.get("desc", "") or name,
                        }
                    )
                else:
                    groups.append(
                        {
                            "name": name,
                            "ratio": 1.0,
                            "desc": "",
                            "translation_source": name,
                        }
                    )
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    name = (
                        item.get("value")
                        or item.get("group")
                        or item.get("name")
                        or item.get("key")
                        or "unknown"
                    )
                    raw_label = item.get("key") or item.get("label") or item.get("description") or ""
                    groups.append(
                        {
                            "name": name,
                            "ratio": item.get("ratio") or item.get("multiplier") or extract_ratio_hint(raw_label, name),
                            "desc": item.get("desc") or item.get("description") or raw_label,
                            "translation_source": raw_label or item.get("description") or item.get("desc") or name,
                        }
                    )

        return groups
