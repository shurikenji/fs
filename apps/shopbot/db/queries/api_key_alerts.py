"""
db/queries/api_key_alerts.py - Alert state helpers for API key low-balance notifications.
"""
from __future__ import annotations

from typing import Optional

from db.queries._helpers import execute_commit, fetch_one_dict


async def get_api_key_alert_state(
    *,
    user_id: int,
    server_id: int,
    api_key_hash: str,
) -> Optional[dict]:
    """Load the current alert state for one user key."""
    return await fetch_one_dict(
        """SELECT * FROM api_key_alert_states
           WHERE user_id = ? AND server_id = ? AND api_key_hash = ?""",
        (user_id, server_id, api_key_hash),
    )


async def upsert_api_key_alert_state(
    *,
    user_id: int,
    server_id: int,
    api_key_hash: str,
    masked_key: str,
    last_seen_remain_quota: int,
    last_seen_balance_dollar: float,
    last_alert_threshold: float | None,
    last_alert_sent_at: str | None = None,
    last_error: str | None = None,
) -> None:
    """Create or update the last observed alert state for one user key."""
    await execute_commit(
        """INSERT INTO api_key_alert_states
           (
               user_id,
               server_id,
               api_key_hash,
               masked_key,
               last_seen_remain_quota,
               last_seen_balance_dollar,
               last_alert_threshold,
               last_alert_sent_at,
               last_checked_at,
               last_error,
               updated_at
           )
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?, datetime('now'))
           ON CONFLICT(user_id, server_id, api_key_hash) DO UPDATE
           SET masked_key = excluded.masked_key,
               last_seen_remain_quota = excluded.last_seen_remain_quota,
               last_seen_balance_dollar = excluded.last_seen_balance_dollar,
               last_alert_threshold = excluded.last_alert_threshold,
               last_alert_sent_at = COALESCE(excluded.last_alert_sent_at, api_key_alert_states.last_alert_sent_at),
               last_checked_at = datetime('now'),
               last_error = excluded.last_error,
               updated_at = datetime('now')""",
        (
            user_id,
            server_id,
            api_key_hash,
            masked_key,
            last_seen_remain_quota,
            last_seen_balance_dollar,
            last_alert_threshold,
            last_alert_sent_at,
            last_error,
        ),
    )
