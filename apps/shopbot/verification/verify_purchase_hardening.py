"""Verify purchase idempotency and lightweight bot hardening."""
from __future__ import annotations

import asyncio
import inspect
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot import main as bot_main
from bot.keyboards.inline_kb import WALLET_TOPUP_PRESET_AMOUNTS
from bot.middlewares.telemetry import MetricsMiddleware
from bot.utils.purchase_nonce import callback_purchase_nonce, message_purchase_nonce
from db.bootstrap import init_db
from db.database import close_db, get_db
from db.queries.orders import create_order_idempotent, update_order_status


async def verify_order_idempotency() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "shopbot-test.db")
        with patch("bot.config.settings", SimpleNamespace(db_path=db_path)):
            await close_db()
            await init_db()
            db = await get_db()
            cursor = await db.execute(
                "INSERT INTO users (telegram_id, username) VALUES (?, ?)",
                (900001, "idempotency-test"),
            )
            await db.commit()
            user_id = int(cursor.lastrowid)

            async def create(code: str):
                return await create_order_idempotent(
                    purchase_nonce="same-purchase",
                    order_code=code,
                    user_id=user_id,
                    product_type="wallet_topup",
                    amount=50_000,
                    payment_method="qr",
                    product_name="Nạp ví",
                )

            first, second = await asyncio.gather(create("TEST-A"), create("TEST-B"))
            assert first[0]["id"] == second[0]["id"]
            assert sorted((first[1], second[1])) == [False, True]

            await update_order_status(int(first[0]["id"]), "completed")
            third, created = await create("TEST-C")
            assert created is True
            assert third["id"] != first[0]["id"]
            await close_db()

    print("[OK] concurrent duplicate purchase creates one pending order and can be reused after completion")


def verify_event_nonces() -> None:
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=7),
        chat=SimpleNamespace(id=11),
        message_id=13,
    )
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=7),
        id="callback-1",
        data="wallet_topup:50000",
        message=message,
    )
    assert callback_purchase_nonce(callback) == callback_purchase_nonce(callback)
    assert message_purchase_nonce(message) == message_purchase_nonce(message)
    callback.data = "wallet_topup:100000"
    assert callback_purchase_nonce(callback) != message_purchase_nonce(message)
    print("[OK] Telegram event-derived purchase nonces are stable and action-specific")


def verify_callback_and_metrics_guards() -> None:
    assert 50_000 in WALLET_TOPUP_PRESET_AMOUNTS
    assert 12_345 not in WALLET_TOPUP_PRESET_AMOUNTS
    assert MetricsMiddleware.percentile([1.0, 2.0, 3.0, 4.0], 0.50) == 2.0
    assert MetricsMiddleware.percentile(list(range(1, 101)), 0.95) == 95
    source = inspect.getsource(bot_main.main)
    assert 'allowed_updates=["message", "callback_query"]' in source
    print("[OK] wallet presets, p50/p95 calculation, and allowed_updates guard are configured")


async def main() -> None:
    await verify_order_idempotency()
    verify_event_nonces()
    verify_callback_and_metrics_guards()


if __name__ == "__main__":
    asyncio.run(main())
