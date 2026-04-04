"""Verification for server query helpers and admin-facing lookup behavior."""
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
from db.queries.servers import (
    create_server,
    get_active_servers,
    get_all_servers,
    get_server_by_id,
    update_server,
)


async def main() -> None:
    original_db_path = settings.db_path

    with TemporaryDirectory() as temp_dir:
        temp_db = Path(temp_dir) / "server-queries.db"
        await close_db()
        object.__setattr__(settings, "db_path", str(temp_db))

        try:
            await init_db()

            primary_id = await create_server(
                name="Primary Server",
                base_url="https://one.example.com",
                user_id_header="new-api-user",
                access_token="secret-1",
                price_per_unit=1000,
                quota_per_unit=1000,
                api_type="newapi",
                supports_multi_group=1,
                manual_groups="alpha, beta",
                sort_order=2,
            )
            secondary_id = await create_server(
                name="Secondary Server",
                base_url="https://two.example.com",
                user_id_header="new-api-user",
                access_token="secret-2",
                price_per_unit=2000,
                quota_per_unit=2000,
                api_type="rixapi",
                supports_multi_group=1,
                sort_order=1,
            )

            await update_server(secondary_id, is_active=0, auth_cookie="session=abc")

            secondary = await get_server_by_id(secondary_id)
            assert secondary is not None
            assert secondary["id"] == secondary_id
            assert secondary["auth_cookie"] == "session=abc"
            assert secondary["api_type"] == "rixapi"
            print("[OK] get_server_by_id returns the full persisted server row")

            all_servers = await get_all_servers()
            assert [server["id"] for server in all_servers] == [secondary_id, primary_id]
            print("[OK] get_all_servers preserves admin ordering by sort_order then id")

            active_servers = await get_active_servers()
            assert [server["id"] for server in active_servers] == [primary_id]
            print("[OK] get_active_servers filters inactive servers while keeping row shape")

            print("\n=== SERVER QUERY VERIFICATION PASSED ===")
        finally:
            await close_db()
            object.__setattr__(settings, "db_path", original_db_path)


asyncio.run(main())
