"""
bot/services/key_valuation.py - Evaluate imported API keys and credit spend safely.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from bot.services.pricing_resolver import vnd_from_quota
from bot.utils.formatting import mask_api_key
from db.database import get_db
from db.queries.pricing import get_active_server_pricing_version, sync_server_pricing_version


def normalize_api_key(api_key: str) -> str:
    value = api_key.strip()
    if value.startswith("sk-"):
        return value
    return f"sk-{value}"


def hash_api_key(api_key: str) -> str:
    normalized = normalize_api_key(api_key)
    token = normalized[3:] if normalized.startswith("sk-") else normalized
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _extract_quota_values(token_data: dict[str, Any]) -> tuple[int | None, int | None]:
    remain = token_data.get("remain_quota")
    used = token_data.get("used_quota")
    if used is None:
        used = token_data.get("usedQuota")
    if remain is None:
        remain = token_data.get("remainQuota")
    if remain is None or used is None:
        return None, None
    try:
        return int(remain), int(used)
    except (TypeError, ValueError):
        return None, None


class KeyValuationService:
    @staticmethod
    async def record_platform_quota_offset(
        *,
        user_id: int,
        server: dict,
        api_key: str,
        quota_delta: int,
        resulting_total_quota: int,
        source: str,
        source_ref: str | None = None,
    ) -> dict[str, Any]:
        """Sync baseline quota for keys that were created or topped up by the platform."""
        normalized_key = normalize_api_key(api_key)
        key_hash = hash_api_key(normalized_key)
        quota_delta = max(0, int(quota_delta or 0))
        resulting_total_quota = max(0, int(resulting_total_quota or 0))

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

        db = await get_db()
        await db.execute("BEGIN IMMEDIATE")
        try:
            registry_cursor = await db.execute(
                """SELECT *
                   FROM api_key_registry
                   WHERE server_id = ? AND api_key_hash = ?""",
                (server["id"], key_hash),
            )
            registry_row = await registry_cursor.fetchone()
            registry = dict(registry_row) if registry_row else None

            if registry is None:
                cursor = await db.execute(
                    """INSERT INTO api_key_registry
                       (server_id, api_key_hash, owner_user_id, masked_key, last_observed_total_quota,
                        last_pricing_version_id, first_seen_at, last_seen_at, is_owner_locked)
                       VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'), 1)""",
                    (
                        server["id"],
                        key_hash,
                        user_id,
                        mask_api_key(normalized_key),
                        resulting_total_quota,
                        pricing_version.get("id"),
                    ),
                )
                registry_id = int(cursor.lastrowid)
                previous_recorded_quota = 0
            else:
                registry_id = int(registry["id"])
                previous_recorded_quota = int(registry.get("last_observed_total_quota") or 0)
                new_recorded_quota = max(previous_recorded_quota, resulting_total_quota)
                await db.execute(
                    """UPDATE api_key_registry
                       SET last_observed_total_quota = ?,
                           last_pricing_version_id = ?,
                           last_seen_at = datetime('now')
                       WHERE id = ?""",
                    (new_recorded_quota, pricing_version.get("id"), registry_id),
                )

            event_delta_quota = max(0, resulting_total_quota - previous_recorded_quota)
            await db.execute(
                """INSERT INTO api_key_valuation_events
                   (server_id, api_key_registry_id, user_id, pricing_version_id, source, source_ref,
                    status, observed_total_quota, previous_recorded_quota, credited_delta_quota,
                    credited_value_vnd, detail_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
                (
                    server["id"],
                    registry_id,
                    user_id,
                    pricing_version.get("id"),
                    source,
                    source_ref,
                    "platform_offset",
                    resulting_total_quota,
                    previous_recorded_quota,
                    event_delta_quota,
                    json.dumps(
                        {
                            "quota_delta": quota_delta,
                            "resulting_total_quota": resulting_total_quota,
                            "pricing_version_id": pricing_version.get("id"),
                        },
                        ensure_ascii=True,
                    ),
                ),
            )
            await db.commit()
            return {
                "status": "platform_offset",
                "registry_id": registry_id,
                "previous_recorded_quota": previous_recorded_quota,
                "recorded_total_quota": max(previous_recorded_quota, resulting_total_quota),
            }
        except Exception:
            await db.rollback()
            raise

    @staticmethod
    async def evaluate_imported_key(
        *,
        user_id: int,
        server: dict,
        api_key: str,
        token_data: dict[str, Any],
        source: str = "manual_topup_input",
        source_ref: str | None = None,
    ) -> dict[str, Any]:
        normalized_key = normalize_api_key(api_key)
        key_hash = hash_api_key(normalized_key)
        remain_quota, used_quota = _extract_quota_values(token_data)
        if remain_quota is None or used_quota is None:
            return {
                "status": "unsupported_usage_payload",
                "credited_value_vnd": 0,
                "credited_delta_quota": 0,
                "observed_total_quota": None,
                "registry_owner_user_id": None,
            }

        observed_total_quota = max(0, remain_quota + used_quota)
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

        db = await get_db()
        await db.execute("BEGIN IMMEDIATE")
        try:
            registry_cursor = await db.execute(
                """SELECT *
                   FROM api_key_registry
                   WHERE server_id = ? AND api_key_hash = ?""",
                (server["id"], key_hash),
            )
            registry_row = await registry_cursor.fetchone()
            registry = dict(registry_row) if registry_row else None

            registry_id: int | None
            previous_recorded_quota = 0
            if registry is None:
                cursor = await db.execute(
                    """INSERT INTO api_key_registry
                       (server_id, api_key_hash, owner_user_id, masked_key, last_observed_total_quota,
                        last_pricing_version_id, first_seen_at, last_seen_at, is_owner_locked)
                       VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'), 1)""",
                    (
                        server["id"],
                        key_hash,
                        user_id,
                        mask_api_key(normalized_key),
                        observed_total_quota,
                        pricing_version.get("id"),
                    ),
                )
                registry_id = int(cursor.lastrowid)
            else:
                registry_id = int(registry["id"])
                previous_recorded_quota = int(registry.get("last_observed_total_quota") or 0)
                owner_user_id = int(registry.get("owner_user_id") or 0)
                if owner_user_id != user_id:
                    event_cursor = await db.execute(
                        """INSERT INTO api_key_valuation_events
                           (server_id, api_key_registry_id, user_id, pricing_version_id, source, source_ref,
                            status, observed_total_quota, previous_recorded_quota, credited_delta_quota,
                            credited_value_vnd, detail_json)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?)""",
                        (
                            server["id"],
                            registry_id,
                            user_id,
                            pricing_version.get("id"),
                            source,
                            source_ref,
                            "owner_mismatch",
                            observed_total_quota,
                            previous_recorded_quota,
                            json.dumps({"registry_owner_user_id": owner_user_id}, ensure_ascii=True),
                        ),
                    )
                    await db.execute(
                        """UPDATE api_key_registry
                           SET last_seen_at = datetime('now')
                           WHERE id = ?""",
                        (registry_id,),
                    )
                    user_key_cursor = await db.execute(
                        """SELECT id
                           FROM user_keys
                           WHERE user_id = ? AND api_key = ?""",
                        (user_id, normalized_key),
                    )
                    user_key_row = await user_key_cursor.fetchone()
                    if user_key_row:
                        await db.execute(
                            """UPDATE user_keys
                               SET server_id = ?,
                                   api_token_id = COALESCE(?, api_token_id),
                                   label = ?,
                                   is_active = 1,
                                   updated_at = datetime('now', '+7 hours')
                               WHERE id = ?""",
                            (
                                server["id"],
                                token_data.get("id"),
                                mask_api_key(normalized_key),
                                int(user_key_row["id"]),
                            ),
                        )
                    else:
                        await db.execute(
                            """INSERT INTO user_keys
                               (user_id, server_id, api_key, api_token_id, label, is_active)
                               VALUES (?, ?, ?, ?, ?, 1)""",
                            (
                                user_id,
                                server["id"],
                                normalized_key,
                                token_data.get("id"),
                                mask_api_key(normalized_key),
                            ),
                        )
                    await db.commit()
                    return {
                        "status": "owner_mismatch",
                        "credited_value_vnd": 0,
                        "credited_delta_quota": 0,
                        "observed_total_quota": observed_total_quota,
                        "registry_owner_user_id": owner_user_id,
                        "valuation_event_id": int(event_cursor.lastrowid),
                    }

            credited_delta_quota = max(0, observed_total_quota - previous_recorded_quota)
            credited_value_vnd = vnd_from_quota(credited_delta_quota, pricing_version)
            event_status = "credited" if credited_delta_quota > 0 else "no_change"

            event_cursor = await db.execute(
                """INSERT INTO api_key_valuation_events
                   (server_id, api_key_registry_id, user_id, pricing_version_id, source, source_ref,
                    status, observed_total_quota, previous_recorded_quota, credited_delta_quota,
                    credited_value_vnd, detail_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    server["id"],
                    registry_id,
                    user_id,
                    pricing_version.get("id"),
                    source,
                    source_ref,
                    event_status,
                    observed_total_quota,
                    previous_recorded_quota,
                    credited_delta_quota,
                    credited_value_vnd,
                    json.dumps(
                        {
                            "remain_quota": remain_quota,
                            "used_quota": used_quota,
                            "pricing_version_id": pricing_version.get("id"),
                        },
                        ensure_ascii=True,
                    ),
                ),
            )
            valuation_event_id = int(event_cursor.lastrowid)

            if credited_delta_quota > 0:
                await db.execute(
                    """UPDATE api_key_registry
                       SET last_observed_total_quota = ?,
                           last_pricing_version_id = ?,
                           last_seen_at = datetime('now')
                       WHERE id = ?""",
                    (observed_total_quota, pricing_version.get("id"), registry_id),
                )
                ledger_cursor = await db.execute(
                    """INSERT INTO spend_ledger
                       (user_id, server_id, source_type, source_ref, amount, direction, description, detail_json)
                       VALUES (?, ?, ?, ?, ?, 'credit', ?, ?)""",
                    (
                        user_id,
                        server["id"],
                        "key_import_credit",
                        str(valuation_event_id),
                        credited_value_vnd,
                        f"Imported key delta for {mask_api_key(normalized_key)}",
                        json.dumps(
                            {
                                "valuation_event_id": valuation_event_id,
                                "credited_delta_quota": credited_delta_quota,
                                "pricing_version_id": pricing_version.get("id"),
                            },
                            ensure_ascii=True,
                        ),
                    ),
                )
                ledger_id = int(ledger_cursor.lastrowid)
                summary_cursor = await db.execute(
                    """SELECT total_spend_vnd
                       FROM user_server_spend_summary
                       WHERE user_id = ? AND server_id = ?""",
                    (user_id, server["id"]),
                )
                summary_row = await summary_cursor.fetchone()
                new_total = int((summary_row["total_spend_vnd"] if summary_row else 0) + credited_value_vnd)
                await db.execute(
                    """INSERT INTO user_server_spend_summary
                       (user_id, server_id, total_spend_vnd, last_ledger_id, created_at, updated_at)
                       VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))
                       ON CONFLICT(user_id, server_id) DO UPDATE SET
                           total_spend_vnd = excluded.total_spend_vnd,
                           last_ledger_id = excluded.last_ledger_id,
                           updated_at = datetime('now')""",
                    (user_id, server["id"], new_total, ledger_id),
                )
            else:
                await db.execute(
                    """UPDATE api_key_registry
                       SET last_seen_at = datetime('now')
                       WHERE id = ?""",
                    (registry_id,),
                )

            user_key_cursor = await db.execute(
                """SELECT id
                   FROM user_keys
                   WHERE user_id = ? AND api_key = ?""",
                (user_id, normalized_key),
            )
            user_key_row = await user_key_cursor.fetchone()
            if user_key_row:
                await db.execute(
                    """UPDATE user_keys
                       SET server_id = ?,
                           api_token_id = COALESCE(?, api_token_id),
                           label = ?,
                           is_active = 1,
                           updated_at = datetime('now', '+7 hours')
                       WHERE id = ?""",
                    (
                        server["id"],
                        token_data.get("id"),
                        mask_api_key(normalized_key),
                        int(user_key_row["id"]),
                    ),
                )
            else:
                await db.execute(
                    """INSERT INTO user_keys
                       (user_id, server_id, api_key, api_token_id, label, is_active)
                       VALUES (?, ?, ?, ?, ?, 1)""",
                    (
                        user_id,
                        server["id"],
                        normalized_key,
                        token_data.get("id"),
                        mask_api_key(normalized_key),
                    ),
                )

            await db.commit()
            return {
                "status": event_status,
                "credited_value_vnd": credited_value_vnd,
                "credited_delta_quota": credited_delta_quota,
                "observed_total_quota": observed_total_quota,
                "registry_owner_user_id": user_id,
                "valuation_event_id": valuation_event_id,
                "pricing_version_id": pricing_version.get("id"),
            }
        except Exception:
            await db.rollback()
            raise
