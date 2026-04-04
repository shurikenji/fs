"""Verify persistent FSM storage and callback payload sizes."""
import asyncio
import sys
from pathlib import Path

from aiogram.fsm.storage.base import StorageKey

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from bot.callback_data.factories import (  # noqa: E402
    BackCustomAmountCB,
    BackKeyInputCB,
    BackServersCB,
    CustomAmountCB,
    MyKeyInputCB,
    ServerSelectCB,
    UpgradeBackCB,
)
from bot.storage.sqlite_fsm import SQLiteFSMStorage  # noqa: E402
from db.database import close_db, get_db  # noqa: E402
from db.models import init_db  # noqa: E402


async def main() -> None:
    await init_db()

    storage = SQLiteFSMStorage()
    key = StorageKey(bot_id=987654, chat_id=123456789, user_id=123456789)

    await storage.set_state(key, "api-key:waiting_existing_key")
    await storage.set_data(
        key,
        {
            "current_cat_id": 12,
            "current_server_id": 34,
            "key_action": "topup",
        },
    )

    assert await storage.get_state(key) == "api-key:waiting_existing_key"
    data = await storage.get_data(key)
    assert data["current_cat_id"] == 12
    assert data["current_server_id"] == 34
    assert data["key_action"] == "topup"
    print("[OK] SQLite FSM storage persists state and data")

    callbacks = [
        ServerSelectCB(cat_id=12, action="topup", server_id=34).pack(),
        MyKeyInputCB(server_id=34, cat_id=12).pack(),
        CustomAmountCB(cat_id=12, action="new", server_id=34).pack(),
        BackServersCB(cat_id=12, action="topup").pack(),
        BackKeyInputCB(server_id=34, cat_id=12).pack(),
        BackCustomAmountCB(server_id=34, cat_id=12, action="topup").pack(),
        UpgradeBackCB(cat_id=12).pack(),
    ]
    assert all(len(item) <= 64 for item in callbacks)
    print("[OK] Callback payloads stay within Telegram 64-byte limit")

    db = await get_db()
    await db.execute("DELETE FROM fsm_storage WHERE storage_id = ?", (storage._storage_id(key),))
    await db.commit()
    await close_db()
    print("\n=== FSM RESILIENCE TESTS PASSED ===")


asyncio.run(main())
