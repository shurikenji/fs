"""
db/queries/pricing.py - Pricing versions, server discount tiers, and product promotions.
"""
from __future__ import annotations

import json
from typing import Any

from bot.utils.time_utils import to_db_time_string
from db.database import get_db
from db.queries._helpers import fetch_all_dicts, fetch_one_dict, fetch_scalar
from db.queries.servers import get_server_by_id


def _now_iso() -> str:
    return to_db_time_string()


def _normalize_datetime(value: str | None) -> str:
    return to_db_time_string(value) if value else _now_iso()


async def list_server_pricing_versions(server_id: int) -> list[dict]:
    return await fetch_all_dicts(
        """SELECT *
           FROM server_pricing_versions
           WHERE server_id = ?
           ORDER BY effective_from DESC, id DESC""",
        (server_id,),
    )


async def get_active_server_pricing_version(
    server_id: int,
    *,
    effective_at: str | None = None,
) -> dict | None:
    resolved_at = _normalize_datetime(effective_at)
    return await fetch_one_dict(
        """SELECT *
           FROM server_pricing_versions
           WHERE server_id = ?
             AND is_active = 1
             AND effective_from <= ?
           ORDER BY effective_from DESC, id DESC
           LIMIT 1""",
        (server_id, resolved_at),
    )


async def create_server_pricing_version(
    server_id: int,
    *,
    name: str | None = None,
    effective_from: str | None = None,
    price_per_unit: int,
    quota_per_unit: int,
    dollar_per_unit: float = 10.0,
    quota_multiple: float = 1.0,
    rounding_mode: str = "round",
    rounding_step: int = 1,
    min_payable_amount: int = 1000,
) -> int:
    db = await get_db()
    next_version = int(
        await fetch_scalar(
            "SELECT COALESCE(MAX(version_code), 0) + 1 FROM server_pricing_versions WHERE server_id = ?",
            (server_id,),
        )
        or 1
    )
    cursor = await db.execute(
        """INSERT INTO server_pricing_versions
           (server_id, version_code, name, effective_from, price_per_unit, quota_per_unit,
            dollar_per_unit, quota_multiple, rounding_mode, rounding_step, min_payable_amount)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            server_id,
            next_version,
            name,
            _normalize_datetime(effective_from),
            price_per_unit,
            quota_per_unit,
            dollar_per_unit,
            quota_multiple,
            rounding_mode,
            rounding_step,
            min_payable_amount,
        ),
    )
    await db.commit()
    return cursor.lastrowid  # type: ignore[return-value]


def _pricing_fields_from_server(server: dict) -> dict[str, Any]:
    return {
        "price_per_unit": int(server.get("price_per_unit") or 0),
        "quota_per_unit": int(server.get("quota_per_unit") or 0),
        "dollar_per_unit": float(server.get("dollar_per_unit") or 10.0),
        "quota_multiple": float(server.get("quota_multiple") or 1.0),
    }


async def sync_server_pricing_version(server_id: int, *, effective_from: str | None = None) -> dict | None:
    server = await get_server_by_id(server_id)
    if not server:
        return None

    current = await get_active_server_pricing_version(server_id, effective_at=effective_from)
    latest_fields = _pricing_fields_from_server(server)
    if current and all(current.get(key) == value for key, value in latest_fields.items()):
        return current

    version_id = await create_server_pricing_version(
        server_id,
        effective_from=effective_from,
        price_per_unit=latest_fields["price_per_unit"],
        quota_per_unit=latest_fields["quota_per_unit"],
        dollar_per_unit=latest_fields["dollar_per_unit"],
        quota_multiple=latest_fields["quota_multiple"],
    )
    return await fetch_one_dict("SELECT * FROM server_pricing_versions WHERE id = ?", (version_id,))


async def replace_server_discount_tiers(server_id: int, tiers: list[dict[str, Any]]) -> None:
    db = await get_db()
    await db.execute("BEGIN IMMEDIATE")
    try:
        await db.execute(
            """DELETE FROM server_tier_benefits
               WHERE tier_id IN (SELECT id FROM server_discount_tiers WHERE server_id = ?)""",
            (server_id,),
        )
        await db.execute("DELETE FROM server_discount_tiers WHERE server_id = ?", (server_id,))

        for sort_order, tier in enumerate(tiers):
            cursor = await db.execute(
                """INSERT INTO server_discount_tiers
                   (server_id, name, min_spend_vnd, is_active, sort_order, updated_at)
                   VALUES (?, ?, ?, ?, ?, datetime('now'))""",
                (
                    server_id,
                    str(tier.get("name") or f"Tier {sort_order + 1}"),
                    int(tier.get("min_spend_vnd") or 0),
                    1 if tier.get("is_active", True) else 0,
                    sort_order,
                ),
            )
            tier_id = int(cursor.lastrowid)
            benefits = tier.get("benefits") or []
            for benefit in benefits:
                await db.execute(
                    """INSERT INTO server_tier_benefits
                       (tier_id, benefit_type, value_amount, config_json, is_active, updated_at)
                       VALUES (?, ?, ?, ?, ?, datetime('now'))""",
                    (
                        tier_id,
                        str(benefit.get("type") or ""),
                        benefit.get("value"),
                        json.dumps(benefit.get("config") or {}, ensure_ascii=True),
                        1 if benefit.get("is_active", True) else 0,
                    ),
                )

        await db.commit()
    except Exception:
        await db.rollback()
        raise


async def get_server_discount_tiers(server_id: int) -> list[dict]:
    tiers = await fetch_all_dicts(
        """SELECT *
           FROM server_discount_tiers
           WHERE server_id = ?
           ORDER BY min_spend_vnd ASC, sort_order ASC, id ASC""",
        (server_id,),
    )
    if not tiers:
        return []

    benefits = await fetch_all_dicts(
        """SELECT *
           FROM server_tier_benefits
           WHERE tier_id IN (
               SELECT id FROM server_discount_tiers WHERE server_id = ?
           )
           ORDER BY id ASC""",
        (server_id,),
    )
    benefit_map: dict[int, list[dict]] = {}
    for benefit in benefits:
        tier_id = int(benefit["tier_id"])
        benefit["type"] = benefit["benefit_type"]
        benefit["value"] = benefit["value_amount"]
        benefit["config"] = json.loads(benefit["config_json"] or "{}")
        benefit_map.setdefault(tier_id, []).append(benefit)

    for tier in tiers:
        tier["benefits"] = benefit_map.get(int(tier["id"]), [])
    return tiers


async def get_matching_discount_tier(server_id: int, spend_vnd: int) -> dict | None:
    tier = await fetch_one_dict(
        """SELECT *
           FROM server_discount_tiers
           WHERE server_id = ?
             AND is_active = 1
             AND min_spend_vnd <= ?
           ORDER BY min_spend_vnd DESC, sort_order DESC, id DESC
           LIMIT 1""",
        (server_id, spend_vnd),
    )
    if not tier:
        return None

    tier["benefits"] = await fetch_all_dicts(
        """SELECT *
           FROM server_tier_benefits
           WHERE tier_id = ?
             AND is_active = 1
           ORDER BY id ASC""",
        (tier["id"],),
    )
    for benefit in tier["benefits"]:
        benefit["type"] = benefit["benefit_type"]
        benefit["value"] = benefit["value_amount"]
        benefit["config"] = json.loads(benefit["config_json"] or "{}")
    return tier


async def list_product_promotions(product_id: int) -> list[dict]:
    rows = await fetch_all_dicts(
        """SELECT *
           FROM product_promotions
           WHERE product_id = ?
           ORDER BY priority DESC, id DESC""",
        (product_id,),
    )
    for row in rows:
        row["config"] = json.loads(row.get("config_json") or "{}")
        row["conditions"] = json.loads(row.get("conditions_json") or "{}")
    return rows


async def get_primary_product_promotion(product_id: int) -> dict | None:
    promotions = await list_product_promotions(product_id)
    return promotions[0] if promotions else None


async def replace_primary_product_promotion(product_id: int, promotion: dict[str, Any] | None) -> None:
    db = await get_db()
    await db.execute("DELETE FROM product_promotions WHERE product_id = ?", (product_id,))
    if not promotion:
        await db.commit()
        return

    await db.execute(
        """INSERT INTO product_promotions
           (product_id, name, promotion_type, value_amount, config_json, conditions_json,
            starts_at, ends_at, priority, is_active, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
        (
            product_id,
            str(promotion.get("name") or "Default promotion"),
            str(promotion.get("promotion_type") or ""),
            promotion.get("value_amount"),
            json.dumps(promotion.get("config") or {}, ensure_ascii=True),
            json.dumps(promotion.get("conditions") or {}, ensure_ascii=True),
            promotion.get("starts_at"),
            promotion.get("ends_at"),
            int(promotion.get("priority") or 0),
            1 if promotion.get("is_active", True) else 0,
        ),
    )
    await db.commit()


async def get_active_product_promotions(product_id: int, *, effective_at: str | None = None) -> list[dict]:
    resolved_at = _normalize_datetime(effective_at)
    rows = await fetch_all_dicts(
        """SELECT *
           FROM product_promotions
           WHERE product_id = ?
             AND is_active = 1
             AND (starts_at IS NULL OR starts_at <= ?)
             AND (ends_at IS NULL OR ends_at >= ?)
           ORDER BY priority DESC, id DESC""",
        (product_id, resolved_at, resolved_at),
    )
    for row in rows:
        row["config"] = json.loads(row.get("config_json") or "{}")
        row["conditions"] = json.loads(row.get("conditions_json") or "{}")
    return rows
