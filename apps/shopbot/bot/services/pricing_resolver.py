"""
bot/services/pricing_resolver.py - Resolve pricing snapshots for API key and non-API orders.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from db.queries.pricing import (
    get_active_product_promotions,
    get_active_server_pricing_version,
    get_matching_discount_tier,
    sync_server_pricing_version,
)
from db.queries.spend import get_user_server_total_spend
from db.queries.users import get_user_by_id


KEY_PRODUCT_TYPES = frozenset({"key_new", "key_topup"})


async def _resolve_discount_policy(user_id: int | None) -> dict[str, Any]:
    if not user_id:
        return {
            "discounts_enabled": True,
            "reason": None,
            "is_admin": False,
            "disable_discounts": False,
        }

    user = await get_user_by_id(user_id)
    is_admin = bool(user and user.get("is_admin"))
    disable_discounts = bool(user and user.get("disable_discounts"))
    reason = None
    if is_admin:
        reason = "admin_bypass"
    elif disable_discounts:
        reason = "user_discount_disabled"

    return {
        "discounts_enabled": not is_admin and not disable_discounts,
        "reason": reason,
        "is_admin": is_admin,
        "disable_discounts": disable_discounts,
    }


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _round_value(raw_value: float, mode: str, step: int) -> int:
    if step <= 0:
        step = 1

    scaled = raw_value / step
    if mode == "floor":
        rounded = int(scaled // 1)
    elif mode == "ceil":
        rounded = int(-(-scaled // 1))
    else:
        rounded = int(round(scaled))
    return rounded * step


def dollars_from_quota(quota: int, pricing_version: dict) -> float:
    quota_per_unit = max(_safe_int(pricing_version.get("quota_per_unit"), 1), 1)
    dollar_per_unit = max(_safe_float(pricing_version.get("dollar_per_unit"), 10.0), 0.0001)
    quota_multiple = max(_safe_float(pricing_version.get("quota_multiple"), 1.0), 0.0001)
    return quota * dollar_per_unit / quota_per_unit / quota_multiple


def quota_from_dollars(dollars: float, pricing_version: dict) -> int:
    quota_per_unit = max(_safe_int(pricing_version.get("quota_per_unit"), 1), 1)
    dollar_per_unit = max(_safe_float(pricing_version.get("dollar_per_unit"), 10.0), 0.0001)
    quota_multiple = max(_safe_float(pricing_version.get("quota_multiple"), 1.0), 0.0001)
    return int(dollars * quota_per_unit / dollar_per_unit * quota_multiple)


def vnd_from_dollars(dollars: float, pricing_version: dict) -> int:
    price_per_unit = _safe_float(pricing_version.get("price_per_unit"), 0.0)
    dollar_per_unit = max(_safe_float(pricing_version.get("dollar_per_unit"), 10.0), 0.0001)
    step = _safe_int(pricing_version.get("rounding_step"), 1)
    mode = str(pricing_version.get("rounding_mode") or "round")
    return max(0, _round_value(dollars * price_per_unit / dollar_per_unit, mode, step))


def vnd_from_quota(quota: int, pricing_version: dict) -> int:
    return vnd_from_dollars(dollars_from_quota(quota, pricing_version), pricing_version)


@dataclass(slots=True)
class QuoteContext:
    base_amount: int
    payable_amount: int
    discount_amount: int
    cashback_amount: int
    spend_credit_amount: int
    quota_amount: int
    dollar_amount: float
    applied_tier_id: int | None
    pricing_version_id: int | None
    pricing_snapshot: dict[str, Any]
    promotion_snapshot: dict[str, Any] | None


def _base_api_amount(
    *,
    product: dict | None,
    custom_dollar: float | None,
    custom_quota: int | None,
    pricing_version: dict,
) -> tuple[int, int, float]:
    if custom_dollar is not None:
        quota_amount = quota_from_dollars(custom_dollar, pricing_version)
        return vnd_from_dollars(custom_dollar, pricing_version), quota_amount, custom_dollar

    if custom_quota is not None:
        dollar_amount = dollars_from_quota(custom_quota, pricing_version)
        return vnd_from_quota(custom_quota, pricing_version), custom_quota, dollar_amount

    if not product:
        return 0, 0, 0.0

    quota_amount = _safe_int(product.get("quota_amount"), 0)
    dollar_amount = _safe_float(product.get("dollar_amount"), 0.0)

    if dollar_amount <= 0 and quota_amount > 0:
        dollar_amount = dollars_from_quota(quota_amount, pricing_version)
    if quota_amount <= 0 and dollar_amount > 0:
        quota_amount = quota_from_dollars(dollar_amount, pricing_version)

    base_amount = _safe_int(product.get("price_vnd"), 0)
    if base_amount <= 0:
        if dollar_amount > 0:
            base_amount = vnd_from_dollars(dollar_amount, pricing_version)
        elif quota_amount > 0:
            base_amount = vnd_from_quota(quota_amount, pricing_version)

    return base_amount, quota_amount, dollar_amount


def _build_price_override_amount(
    *,
    benefit: dict,
    base_amount: int,
    quota_amount: int,
    dollar_amount: float,
    pricing_version: dict,
) -> int | None:
    config = benefit.get("config") or {}
    price_per_dollar = config.get("price_per_dollar")
    if price_per_dollar is None and benefit.get("value") is not None:
        price_per_dollar = benefit.get("value")
    if price_per_dollar is not None and dollar_amount > 0:
        return max(0, int(round(dollar_amount * _safe_float(price_per_dollar))))

    price_per_unit = config.get("price_per_unit")
    dollar_per_unit = config.get("dollar_per_unit", pricing_version.get("dollar_per_unit"))
    if price_per_unit is not None and dollar_amount > 0:
        return max(
            0,
            int(round(dollar_amount * _safe_float(price_per_unit) / max(_safe_float(dollar_per_unit, 10.0), 0.0001))),
        )

    if quota_amount > 0 and price_per_unit is not None:
        override_version = {
            **pricing_version,
            "price_per_unit": _safe_int(price_per_unit, _safe_int(pricing_version.get("price_per_unit"), 0)),
            "dollar_per_unit": _safe_float(dollar_per_unit, _safe_float(pricing_version.get("dollar_per_unit"), 10.0)),
        }
        return vnd_from_quota(quota_amount, override_version)

    return None


def _evaluate_benefit(
    benefit: dict,
    *,
    base_amount: int,
    quota_amount: int,
    dollar_amount: float,
    pricing_version: dict,
) -> dict[str, Any]:
    benefit_type = str(benefit.get("type") or benefit.get("benefit_type") or "")
    value = _safe_float(benefit.get("value"))
    result = {
        "type": benefit_type,
        "discount_amount": 0,
        "cashback_amount": 0,
        "payable_amount": base_amount,
        "detail": {
            "type": benefit_type,
            "value": benefit.get("value"),
            "config": benefit.get("config") or {},
        },
    }

    if benefit_type == "percent_off":
        discount_amount = max(0, int(round(base_amount * value / 100.0)))
        result["discount_amount"] = min(discount_amount, base_amount)
        result["payable_amount"] = max(0, base_amount - result["discount_amount"])
    elif benefit_type == "fixed_off":
        discount_amount = max(0, _safe_int(benefit.get("value")))
        result["discount_amount"] = min(discount_amount, base_amount)
        result["payable_amount"] = max(0, base_amount - result["discount_amount"])
    elif benefit_type == "cashback":
        config = benefit.get("config") or {}
        mode = str(config.get("mode") or "percent")
        if mode == "fixed":
            result["cashback_amount"] = max(0, _safe_int(benefit.get("value")))
        else:
            result["cashback_amount"] = max(0, int(round(base_amount * value / 100.0)))
    elif benefit_type == "tier_price":
        override_amount = _build_price_override_amount(
            benefit=benefit,
            base_amount=base_amount,
            quota_amount=quota_amount,
            dollar_amount=dollar_amount,
            pricing_version=pricing_version,
        )
        if override_amount is not None:
            result["payable_amount"] = max(0, override_amount)
            result["discount_amount"] = max(0, base_amount - result["payable_amount"])

    return result


def _choose_exclusive_benefit(
    benefits: list[dict],
    *,
    base_amount: int,
    quota_amount: int,
    dollar_amount: float,
    pricing_version: dict,
) -> tuple[int, int, list[dict[str, Any]]]:
    best = {"payable_amount": base_amount, "cashback_amount": 0, "discount_amount": 0, "detail": None}
    best_net_cost = base_amount
    breakdown: list[dict[str, Any]] = []

    for benefit in benefits:
        candidate = _evaluate_benefit(
            benefit,
            base_amount=base_amount,
            quota_amount=quota_amount,
            dollar_amount=dollar_amount,
            pricing_version=pricing_version,
        )
        net_cost = candidate["payable_amount"] - candidate["cashback_amount"]
        if net_cost < best_net_cost:
            best = candidate
            best_net_cost = net_cost
            breakdown = [candidate["detail"]]

    return best["discount_amount"], best["cashback_amount"], breakdown


def _apply_combined_benefits(
    benefits: list[dict],
    *,
    allowed_types: set[str],
    base_amount: int,
    quota_amount: int,
    dollar_amount: float,
    pricing_version: dict,
) -> tuple[int, int, list[dict[str, Any]]]:
    filtered = [benefit for benefit in benefits if str(benefit.get("type") or benefit.get("benefit_type")) in allowed_types]
    breakdown: list[dict[str, Any]] = []
    discount_amount = 0
    cashback_amount = 0

    tier_price_benefits = [
        benefit for benefit in filtered if str(benefit.get("type") or benefit.get("benefit_type")) == "tier_price"
    ]
    if tier_price_benefits:
        tier_price = _evaluate_benefit(
            tier_price_benefits[0],
            base_amount=base_amount,
            quota_amount=quota_amount,
            dollar_amount=dollar_amount,
            pricing_version=pricing_version,
        )
        discount_amount += tier_price["discount_amount"]
        breakdown.append(tier_price["detail"])
        filtered = [
            benefit
            for benefit in filtered
            if str(benefit.get("type") or benefit.get("benefit_type")) == "cashback"
        ]

    current_payable = max(0, base_amount - discount_amount)
    for benefit in filtered:
        benefit_type = str(benefit.get("type") or benefit.get("benefit_type"))
        if benefit_type == "cashback":
            evaluated = _evaluate_benefit(
                benefit,
                base_amount=current_payable,
                quota_amount=quota_amount,
                dollar_amount=dollar_amount,
                pricing_version=pricing_version,
            )
            cashback_amount += evaluated["cashback_amount"]
            breakdown.append(evaluated["detail"])
            continue

        evaluated = _evaluate_benefit(
            benefit,
            base_amount=current_payable,
            quota_amount=quota_amount,
            dollar_amount=dollar_amount,
            pricing_version=pricing_version,
        )
        current_payable = evaluated["payable_amount"]
        discount_amount = max(0, base_amount - current_payable)
        breakdown.append(evaluated["detail"])

    return discount_amount, cashback_amount, breakdown


async def quote_api_order(
    *,
    user_id: int,
    server: dict,
    product: dict | None = None,
    custom_dollar: float | None = None,
    custom_quota: int | None = None,
) -> QuoteContext:
    discount_policy = await _resolve_discount_policy(user_id)
    pricing_version = await get_active_server_pricing_version(server["id"])
    if pricing_version is None:
        pricing_version = await sync_server_pricing_version(server["id"])
    if pricing_version is None:
        pricing_version = {
            "id": None,
            "price_per_unit": int(server.get("price_per_unit") or 0),
            "quota_per_unit": int(server.get("quota_per_unit") or 1),
            "dollar_per_unit": float(server.get("dollar_per_unit") or 10.0),
            "quota_multiple": float(server.get("quota_multiple") or 1.0),
            "rounding_mode": "round",
            "rounding_step": 1,
        }

    current_spend = await get_user_server_total_spend(user_id, server["id"])
    tier = None
    if discount_policy["discounts_enabled"]:
        tier = await get_matching_discount_tier(server["id"], current_spend)
    base_amount, quota_amount, dollar_amount = _base_api_amount(
        product=product,
        custom_dollar=custom_dollar,
        custom_quota=custom_quota,
        pricing_version=pricing_version,
    )

    discount_amount = 0
    cashback_amount = 0
    benefit_breakdown: list[dict[str, Any]] = []
    benefits = tier.get("benefits", []) if tier else []
    if benefits:
        stack_mode = str(server.get("discount_stack_mode") or "exclusive")
        allowed_types = {
            item.strip()
            for item in str(server.get("discount_allowed_stack_types") or "").split(",")
            if item.strip()
        }
        if stack_mode == "combine_selected_types":
            discount_amount, cashback_amount, benefit_breakdown = _apply_combined_benefits(
                benefits,
                allowed_types=allowed_types,
                base_amount=base_amount,
                quota_amount=quota_amount,
                dollar_amount=dollar_amount,
                pricing_version=pricing_version,
            )
        else:
            discount_amount, cashback_amount, benefit_breakdown = _choose_exclusive_benefit(
                benefits,
                base_amount=base_amount,
                quota_amount=quota_amount,
                dollar_amount=dollar_amount,
                pricing_version=pricing_version,
            )

    payable_amount = max(0, base_amount - discount_amount)
    return QuoteContext(
        base_amount=base_amount,
        payable_amount=payable_amount,
        discount_amount=discount_amount,
        cashback_amount=cashback_amount,
        spend_credit_amount=payable_amount,
        quota_amount=quota_amount,
        dollar_amount=dollar_amount,
        applied_tier_id=tier["id"] if tier else None,
        pricing_version_id=pricing_version.get("id"),
        pricing_snapshot={
            "kind": "api_order",
            "server_id": server["id"],
            "pricing_version_id": pricing_version.get("id"),
            "price_per_unit": pricing_version.get("price_per_unit"),
            "quota_per_unit": pricing_version.get("quota_per_unit"),
            "dollar_per_unit": pricing_version.get("dollar_per_unit"),
            "quota_multiple": pricing_version.get("quota_multiple"),
            "stack_mode": server.get("discount_stack_mode") or "exclusive",
            "current_spend_before": current_spend,
            "discounts_enabled": discount_policy["discounts_enabled"],
            "discount_policy_reason": discount_policy["reason"],
            "tier_id": tier["id"] if tier else None,
            "tier_name": tier.get("name") if tier else None,
            "benefits": benefit_breakdown,
            "quota_amount": quota_amount,
            "dollar_amount": dollar_amount,
        },
        promotion_snapshot=None,
    )


async def quote_non_api_product(product: dict, *, user_id: int | None = None) -> QuoteContext:
    base_amount = _safe_int(product.get("price_vnd"), 0)
    discount_amount = 0
    promotion_snapshot: dict[str, Any] | None = None
    discount_policy = await _resolve_discount_policy(user_id)
    promotions = await get_active_product_promotions(product["id"]) if discount_policy["discounts_enabled"] else []
    if promotions:
        promotion = promotions[0]
        promotion_type = str(promotion.get("promotion_type") or "")
        value_amount = _safe_float(promotion.get("value_amount"), 0.0)
        if promotion_type == "percent_off":
            discount_amount = min(base_amount, max(0, int(round(base_amount * value_amount / 100.0))))
        elif promotion_type == "fixed_off":
            discount_amount = min(base_amount, max(0, _safe_int(value_amount)))
        elif promotion_type == "override_price":
            discount_amount = max(0, base_amount - max(0, _safe_int(value_amount)))

        promotion_snapshot = {
            "promotion_id": promotion.get("id"),
            "promotion_type": promotion_type,
            "value_amount": promotion.get("value_amount"),
            "priority": promotion.get("priority"),
            "name": promotion.get("name"),
        }

    payable_amount = max(0, base_amount - discount_amount)
    return QuoteContext(
        base_amount=base_amount,
        payable_amount=payable_amount,
        discount_amount=discount_amount,
        cashback_amount=0,
        spend_credit_amount=0,
        quota_amount=_safe_int(product.get("quota_amount"), 0),
        dollar_amount=_safe_float(product.get("dollar_amount"), 0.0),
        applied_tier_id=None,
        pricing_version_id=None,
        pricing_snapshot={
            "kind": "product_price",
            "product_id": product["id"],
            "discounts_enabled": discount_policy["discounts_enabled"],
            "discount_policy_reason": discount_policy["reason"],
        },
        promotion_snapshot=promotion_snapshot,
    )
