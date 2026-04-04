"""
db/queries/spend.py - Query helpers for spend summaries, ledger, and imported keys.
"""
from __future__ import annotations

from db.queries._helpers import fetch_all_dicts, fetch_one_dict, fetch_scalar


async def get_user_server_spend_summary(user_id: int, server_id: int) -> dict | None:
    return await fetch_one_dict(
        """SELECT *
           FROM user_server_spend_summary
           WHERE user_id = ? AND server_id = ?""",
        (user_id, server_id),
    )


async def get_user_server_total_spend(user_id: int, server_id: int) -> int:
    return int(
        await fetch_scalar(
            """SELECT total_spend_vnd
               FROM user_server_spend_summary
               WHERE user_id = ? AND server_id = ?""",
            (user_id, server_id),
        )
        or 0
    )


async def find_api_key_registry(server_id: int, api_key_hash: str) -> dict | None:
    return await fetch_one_dict(
        """SELECT *
           FROM api_key_registry
           WHERE server_id = ? AND api_key_hash = ?""",
        (server_id, api_key_hash),
    )


async def list_spend_ledger(user_id: int, server_id: int | None = None) -> list[dict]:
    if server_id is None:
        return await fetch_all_dicts(
            """SELECT *
               FROM spend_ledger
               WHERE user_id = ?
               ORDER BY id ASC""",
            (user_id,),
        )

    return await fetch_all_dicts(
        """SELECT *
           FROM spend_ledger
           WHERE user_id = ? AND server_id = ?
           ORDER BY id ASC""",
        (user_id, server_id),
    )


async def list_key_valuation_events(server_id: int, api_key_hash: str | None = None) -> list[dict]:
    if api_key_hash is None:
        return await fetch_all_dicts(
            """SELECT *
               FROM api_key_valuation_events
               WHERE server_id = ?
               ORDER BY id ASC""",
            (server_id,),
        )

    return await fetch_all_dicts(
        """SELECT ev.*
           FROM api_key_valuation_events ev
           JOIN api_key_registry reg ON reg.id = ev.api_key_registry_id
           WHERE ev.server_id = ? AND reg.api_key_hash = ?
           ORDER BY ev.id ASC""",
        (server_id, api_key_hash),
    )
