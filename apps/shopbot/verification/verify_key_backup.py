"""Verification for upstream key backup storage and alert-poller integration."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from starlette.requests import Request

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from bot.config import settings
from db.database import close_db
from db.models import init_db
from db.queries.api_key_alerts import get_api_key_alert_state
from db.queries.key_backup import (
    bulk_insert_backup_items,
    create_snapshot,
    find_backup_item_for_user_key,
    get_latest_items_by_server,
    key_search_matches,
)
from db.queries.servers import create_server
from db.queries.settings import get_setting
from db.queries.user_keys import create_user_key
from db.queries.users import create_user


class _UnexpectedClient:
    def __init__(self) -> None:
        self.calls = 0

    async def search_token(self, server: dict, api_key: str) -> dict | None:
        _ = server, api_key
        self.calls += 1
        return None


async def _verify_settings_ui_and_save() -> None:
    from admin.deps import get_templates
    from admin.routers.settings import settings_save

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/settings",
            "headers": [],
            "query_string": b"",
        }
    )
    response = get_templates().TemplateResponse(
        "settings.html",
        {
            "request": request,
            "all_settings": {
                "key_backup_enabled": "true",
                "key_backup_interval_min": "10",
                "key_backup_retention_days": "7",
            },
            "ai_providers": [],
            "ai_models": {},
        },
    )
    body = response.body.decode("utf-8")
    assert "key_backup_enabled" in body
    assert "key_backup_interval_min" in body
    assert "key_backup_retention_days" in body

    class _FormRequest:
        async def form(self) -> dict[str, str]:
            return {
                "key_backup_interval_min": "12",
                "key_backup_retention_days": "9",
                "key_backup_enabled": "true",
            }

    await settings_save(_FormRequest())  # type: ignore[arg-type]
    assert await get_setting("key_backup_enabled") == "true"
    assert await get_setting("key_backup_interval_min") == "12"
    assert await get_setting("key_backup_retention_days") == "9"

    class _DisabledFormRequest:
        async def form(self) -> dict[str, str]:
            return {
                "key_backup_interval_min": "15",
                "key_backup_retention_days": "11",
            }

    await settings_save(_DisabledFormRequest())  # type: ignore[arg-type]
    assert await get_setting("key_backup_enabled") == "false"
    assert await get_setting("key_backup_interval_min") == "15"
    assert await get_setting("key_backup_retention_days") == "11"


async def main() -> None:
    original_db_path = settings.db_path

    with TemporaryDirectory() as temp_dir:
        temp_db = Path(temp_dir) / "key-backup.db"
        await close_db()
        object.__setattr__(settings, "db_path", str(temp_db))

        try:
            await init_db()
            await _verify_settings_ui_and_save()

            user = await create_user(
                telegram_id=52001,
                username="backup-user",
                full_name="Backup User",
            )
            server_id = await create_server(
                name="Backup Server",
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
                api_key="sk-TPhUabcdefghijklAdnC",
                api_token_id=18258,
                label="key_28loiv31_1",
            )

            snapshot_id = await create_snapshot(server_id, 1, 3.0)
            await bulk_insert_backup_items(
                snapshot_id,
                server_id,
                [
                    {
                        "token_id": 18258,
                        "token_name": "key_28loiv31_1",
                        "key_masked": "sk-TPhU**********AdnC",
                        "remain_quota": 1_500_000,
                        "used_quota": 500_000,
                        "total_quota": 2_000_000,
                        "balance_dollar": 3.0,
                        "group_name": "OpenAI",
                    }
                ],
            )

            matched = await find_backup_item_for_user_key(
                server_id,
                None,
                None,
                "sk-TPhUabcdefghijklAdnC",
            )
            assert matched is not None
            assert matched["token_id"] == 18258
            assert key_search_matches(
                "sk-TPhUabcdefghijklAdnC",
                "sk-TPhU**********AdnC",
            )
            assert key_search_matches("28loiv31", "key_28loiv31_1")
            assert key_search_matches("open", "OpenAI")

            items = await get_latest_items_by_server(server_id)
            assert len(items) == 1
            assert items[0]["shopbot_match"] is True

            import bot.services.key_alert_poller as key_alert_poller

            fake_client = _UnexpectedClient()
            original_get_api_client = key_alert_poller.get_api_client
            original_notify_user = key_alert_poller.notify_user
            key_alert_poller.get_api_client = lambda server: fake_client
            key_alert_poller.notify_user = lambda user_id, text, *, bot=None: True
            try:
                await key_alert_poller._poll_cycle(bot=object())
                assert fake_client.calls == 0
                state = await get_api_key_alert_state(
                    user_id=user["id"],
                    server_id=server_id,
                    api_key_hash=key_alert_poller.hash_api_key("sk-TPhUabcdefghijklAdnC"),
                )
                assert state is not None
                assert int(state["last_seen_remain_quota"]) == 1_500_000
            finally:
                key_alert_poller.get_api_client = original_get_api_client
                key_alert_poller.notify_user = original_notify_user

            import bot.services.key_backup_poller as key_backup_poller
            from admin.routers.key_backup import _apply_item_search

            async def _fake_fetch_all_tokens(server: dict) -> list[dict]:
                _ = server
                return [
                    {
                        "id": 20001,
                        "name": "fresh_key",
                        "key": "FullKeyValue123456",
                        "remain_quota": 500_000,
                        "used_quota": 0,
                        "group": "OpenAI",
                    },
                    {
                        "id": 20002,
                        "name": "masked_key",
                        "key": "Mask**********Tail",
                        "remain_quota": 250_000,
                        "used_quota": 0,
                        "group": "Claude",
                    }
                ]

            original_fetch_all_tokens = key_backup_poller._fetch_all_tokens
            key_backup_poller._fetch_all_tokens = _fake_fetch_all_tokens
            try:
                result = await key_backup_poller.backup_server_now(server_id)
                assert result is not None
                assert result["status"] == "success"
                assert result["total_keys"] == 2
            finally:
                key_backup_poller._fetch_all_tokens = original_fetch_all_tokens

            latest_items = await get_latest_items_by_server(server_id)
            fresh_item = next(item for item in latest_items if item["token_name"] == "fresh_key")
            masked_item = next(item for item in latest_items if item["token_name"] == "masked_key")
            assert fresh_item["key_value"] == "sk-FullKeyValue123456"
            assert fresh_item["key_masked"].startswith("sk-")
            assert masked_item["key_value"] is None
            assert masked_item["key_masked"] == "sk-Mask**********Tail"
            assert _apply_item_search(latest_items, "FullKeyValue")
            assert _apply_item_search(latest_items, "sk-MaskabcdefghTail")
            assert _apply_item_search(latest_items, "Claude")

            print("[OK] key backup stores snapshots, matches masked keys, and feeds alert polling")
            print("\n=== KEY BACKUP VERIFICATION PASSED ===")
        finally:
            await close_db()
            object.__setattr__(settings, "db_path", original_db_path)


asyncio.run(main())
