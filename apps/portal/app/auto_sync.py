"""In-process automatic pricing refresh poller."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Mapping

from app.sync_service import refresh_enabled_server_snapshots
from db.queries.settings import get_settings_dict

logger = logging.getLogger(__name__)

_AUTO_SYNC_DEFAULTS = {
    "auto_sync_enabled": "false",
    "auto_sync_interval_minutes": "15",
}


@dataclass(frozen=True)
class AutoSyncSettings:
    enabled: bool = False
    interval_minutes: int = 15


def parse_auto_sync_settings(values: Mapping[str, str] | None = None) -> AutoSyncSettings:
    data = dict(_AUTO_SYNC_DEFAULTS)
    for key, value in (values or {}).items():
        data[key] = str(value or "")

    enabled = data.get("auto_sync_enabled", "false").strip().lower() == "true"
    try:
        interval_minutes = int(str(data.get("auto_sync_interval_minutes", "15")).strip() or "15")
    except ValueError:
        interval_minutes = 15
    interval_minutes = max(1, interval_minutes)
    return AutoSyncSettings(enabled=enabled, interval_minutes=interval_minutes)


async def load_auto_sync_settings() -> AutoSyncSettings:
    return parse_auto_sync_settings(await get_settings_dict(_AUTO_SYNC_DEFAULTS))


class AutoSyncPoller:
    def __init__(
        self,
        *,
        heartbeat_seconds: float = 15.0,
        initial_delay_seconds: float = 10.0,
    ) -> None:
        self._heartbeat_seconds = heartbeat_seconds
        self._initial_delay_seconds = initial_delay_seconds
        self._task: asyncio.Task | None = None
        self._cycle_lock = asyncio.Lock()
        self._enabled_since: float | None = None
        self._last_run_at: float | None = None

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run_loop(), name="pricing-hub-auto-sync")

    async def stop(self) -> None:
        if not self._task:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

    async def _run_loop(self) -> None:
        while True:
            settings = await load_auto_sync_settings()
            now = time.monotonic()

            if not settings.enabled:
                self._enabled_since = None
                self._last_run_at = None
                await asyncio.sleep(self._heartbeat_seconds)
                continue

            if self._enabled_since is None:
                self._enabled_since = now

            should_run = False
            if self._last_run_at is None:
                should_run = (now - self._enabled_since) >= self._initial_delay_seconds
            else:
                should_run = (now - self._last_run_at) >= (settings.interval_minutes * 60)

            if should_run and not self._cycle_lock.locked():
                async with self._cycle_lock:
                    self._last_run_at = time.monotonic()
                    logger.info(
                        "Starting auto sync cycle for enabled servers (interval=%sm)",
                        settings.interval_minutes,
                    )
                    try:
                        await refresh_enabled_server_snapshots(trigger="auto")
                    except Exception:
                        logger.exception("Auto sync cycle failed")

            await asyncio.sleep(self._heartbeat_seconds)
