"""
SQLite-backed FSM storage so bot restarts do not wipe active flows.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Any

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StateType, StorageKey

from db.database import get_db


class SQLiteFSMStorage(BaseStorage):
    """Persist FSM state/data in the main SQLite database."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    @staticmethod
    def _storage_id(key: StorageKey) -> str:
        return json.dumps(
            [
                key.bot_id,
                key.chat_id,
                key.user_id,
                key.thread_id,
                key.business_connection_id,
                key.destiny,
            ],
            ensure_ascii=True,
            separators=(",", ":"),
        )

    async def _fetch_row(self, key: StorageKey):
        db = await get_db()
        cursor = await db.execute(
            """
            SELECT state, data_json
            FROM fsm_storage
            WHERE storage_id = ?
            """,
            (self._storage_id(key),),
        )
        return await cursor.fetchone()

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        state_value = state.state if isinstance(state, State) else state
        async with self._lock:
            row = await self._fetch_row(key)
            data_json = row["data_json"] if row else "{}"
            db = await get_db()
            await db.execute(
                """
                INSERT INTO fsm_storage (
                    storage_id, bot_id, chat_id, user_id, thread_id,
                    business_connection_id, destiny, state, data_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(storage_id) DO UPDATE SET
                    state = excluded.state,
                    updated_at = datetime('now')
                """,
                (
                    self._storage_id(key),
                    key.bot_id,
                    key.chat_id,
                    key.user_id,
                    key.thread_id,
                    key.business_connection_id,
                    key.destiny,
                    state_value,
                    data_json,
                ),
            )
            await db.commit()

    async def get_state(self, key: StorageKey) -> str | None:
        row = await self._fetch_row(key)
        return None if row is None else row["state"]

    async def set_data(self, key: StorageKey, data: Mapping[str, Any]) -> None:
        if not isinstance(data, dict):
            msg = f"Data must be a dict or dict-like object, got {type(data).__name__}"
            raise TypeError(msg)

        async with self._lock:
            row = await self._fetch_row(key)
            state_value = row["state"] if row else None
            db = await get_db()
            await db.execute(
                """
                INSERT INTO fsm_storage (
                    storage_id, bot_id, chat_id, user_id, thread_id,
                    business_connection_id, destiny, state, data_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(storage_id) DO UPDATE SET
                    data_json = excluded.data_json,
                    updated_at = datetime('now')
                """,
                (
                    self._storage_id(key),
                    key.bot_id,
                    key.chat_id,
                    key.user_id,
                    key.thread_id,
                    key.business_connection_id,
                    key.destiny,
                    state_value,
                    json.dumps(dict(data), ensure_ascii=True, separators=(",", ":")),
                ),
            )
            await db.commit()

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        row = await self._fetch_row(key)
        if row is None:
            return {}
        try:
            payload = json.loads(row["data_json"] or "{}")
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    async def close(self) -> None:
        return None
