"""Lightweight latency metrics and callback spam protection."""
from __future__ import annotations

import logging
import math
import time
from collections import OrderedDict, deque
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import CallbackQuery, TelegramObject

logger = logging.getLogger(__name__)


class MetricsMiddleware(BaseMiddleware):
    def __init__(self, *, log_every: int = 100, max_samples: int = 1000) -> None:
        self.log_every = log_every
        self._latencies_ms: deque[float] = deque(maxlen=max_samples)
        self.processed = 0
        self.telegram_429 = 0

    @staticmethod
    def percentile(values: list[float], fraction: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        index = max(0, math.ceil(len(ordered) * fraction) - 1)
        return ordered[index]

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        started = time.perf_counter()
        try:
            return await handler(event, data)
        except TelegramRetryAfter as exc:
            self.telegram_429 += 1
            logger.warning(
                "Telegram 429 retry_after=%ss total_429=%d",
                exc.retry_after,
                self.telegram_429,
            )
            raise
        finally:
            self._latencies_ms.append((time.perf_counter() - started) * 1000)
            self.processed += 1
            if self.log_every > 0 and self.processed % self.log_every == 0:
                samples = list(self._latencies_ms)
                logger.info(
                    "Bot latency updates=%d p50_ms=%.1f p95_ms=%.1f telegram_429=%d",
                    self.processed,
                    self.percentile(samples, 0.50),
                    self.percentile(samples, 0.95),
                    self.telegram_429,
                )


class CallbackDebounceMiddleware(BaseMiddleware):
    def __init__(self, *, interval_seconds: float = 0.25, max_users: int = 5000) -> None:
        self.interval_seconds = interval_seconds
        self.max_users = max_users
        self._last: OrderedDict[int, tuple[str | None, float]] = OrderedDict()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if not isinstance(event, CallbackQuery):
            return await handler(event, data)

        user_id = event.from_user.id
        now = time.monotonic()
        previous = self._last.pop(user_id, None)
        self._last[user_id] = (event.data, now)
        if len(self._last) > self.max_users:
            self._last.popitem(last=False)

        if previous is not None and previous[0] == event.data and now - previous[1] < self.interval_seconds:
            await event.answer()
            return None
        return await handler(event, data)
