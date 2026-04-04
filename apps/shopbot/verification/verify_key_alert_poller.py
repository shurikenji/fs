"""Verification for low-balance API key alert polling."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from bot.config import settings
from db.database import close_db
from db.models import init_db
from db.queries.api_key_alerts import get_api_key_alert_state
from db.queries.servers import create_server
from db.queries.settings import set_setting
from db.queries.user_keys import create_user_key
from db.queries.users import create_user


class _FakeClient:
    def __init__(self, quotas: list[int]) -> None:
        self._quotas = quotas
        self._index = 0

    async def search_token(self, server: dict, api_key: str) -> dict:
        _ = server, api_key
        quota = self._quotas[min(self._index, len(self._quotas) - 1)]
        self._index += 1
        return {"remain_quota": quota}


async def main() -> None:
    original_db_path = settings.db_path

    with TemporaryDirectory() as temp_dir:
        temp_db = Path(temp_dir) / "key-alert-poller.db"
        await close_db()
        object.__setattr__(settings, "db_path", str(temp_db))

        try:
            await init_db()

            import bot.services.key_alert_poller as key_alert_poller

            user = await create_user(
                telegram_id=51001,
                username="alert-user",
                full_name="Alert User",
            )
            server_id = await create_server(
                name="Alert Server",
                base_url="https://example.com",
                user_id_header="new-api-user",
                access_token="secret",
                price_per_unit=1000,
                quota_per_unit=1000,
                quota_multiple=1.0,
            )
            await create_user_key(
                user_id=user["id"],
                server_id=server_id,
                api_key="sk-alert-balance-1234567890",
                label="Primary key",
            )

            await set_setting("key_alert_enabled", "true")
            await set_setting("key_alert_thresholds", "5,3,1")

            notifications: list[str] = []
            fake_client = _FakeClient([2_000_000, 1_800_000, 1_200_000, 500_000, 3_500_000, 450_000])

            async def _fake_notify_user(user_id: int, text: str, *, bot=None) -> bool:
                _ = user_id, bot
                notifications.append(text)
                return True

            original_get_api_client = key_alert_poller.get_api_client
            original_notify_user = key_alert_poller.notify_user
            key_alert_poller.get_api_client = lambda server: fake_client
            key_alert_poller.notify_user = _fake_notify_user
            try:
                await key_alert_poller._poll_cycle(bot=object())
                await key_alert_poller._poll_cycle(bot=object())
                await key_alert_poller._poll_cycle(bot=object())
                await key_alert_poller._poll_cycle(bot=object())
                await key_alert_poller._poll_cycle(bot=object())
                await key_alert_poller._poll_cycle(bot=object())

                assert len(notifications) == 4
                assert "$4.00" in notifications[0]
                assert "$2.40" in notifications[1]
                assert "$1.00" in notifications[2]
                assert "$0.90" in notifications[3]

                state = await get_api_key_alert_state(
                    user_id=user["id"],
                    server_id=server_id,
                    api_key_hash=key_alert_poller.hash_api_key("sk-alert-balance-1234567890"),
                )
                assert state is not None
                assert float(state["last_alert_threshold"]) == 1.0
                print("[OK] key alert poller sends only when crossing new thresholds and resets after top-up")
            finally:
                key_alert_poller.get_api_client = original_get_api_client
                key_alert_poller.notify_user = original_notify_user

            print("\n=== KEY ALERT POLLER VERIFICATION PASSED ===")
        finally:
            await close_db()
            object.__setattr__(settings, "db_path", original_db_path)


asyncio.run(main())
