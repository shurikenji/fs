"""SQLite database bootstrap for platform-control."""
from __future__ import annotations

from pathlib import Path

import aiosqlite

from app.config import get_settings
from db.models import CREATE_TABLES

_db: aiosqlite.Connection | None = None

_SEED_SERVICE_SOURCES = (
    {
        "id": "gpt1",
        "name": "GPT1",
        "upstream_base_url": "https://api.aabao.top",
        "public_base_url": "https://gpt1.shupremium.com",
        "source_type": "newapi",
        "enabled": 1,
        "public_pricing_enabled": 1,
        "public_balance_enabled": 1,
        "public_keys_enabled": 1,
        "public_logs_enabled": 1,
        "balance_rate": 0.3,
    },
    {
        "id": "gpt2",
        "name": "GPT2",
        "upstream_base_url": "https://api.996444.cn",
        "public_base_url": "https://gpt2.shupremium.com",
        "source_type": "newapi",
        "enabled": 1,
        "public_pricing_enabled": 1,
        "public_balance_enabled": 1,
        "public_keys_enabled": 1,
        "public_logs_enabled": 1,
        "balance_rate": 0.5,
    },
    {
        "id": "gpt3",
        "name": "GPT3",
        "upstream_base_url": "https://www.mnapi.com",
        "public_base_url": "https://gpt3.shupremium.com",
        "source_type": "newapi",
        "enabled": 1,
        "public_pricing_enabled": 1,
        "public_balance_enabled": 0,
        "public_keys_enabled": 1,
        "public_logs_enabled": 1,
        "balance_rate": 1.0,
    },
    {
        "id": "gpt4",
        "name": "GPT4",
        "upstream_base_url": "https://api.kksj.org",
        "public_base_url": "https://gpt4.shupremium.com",
        "source_type": "newapi",
        "enabled": 1,
        "public_pricing_enabled": 1,
        "public_balance_enabled": 1,
        "public_keys_enabled": 1,
        "public_logs_enabled": 1,
        "balance_rate": 0.9,
    },
    {
        "id": "gpt5",
        "name": "GPT5",
        "upstream_base_url": "https://new.xjai.cc",
        "public_base_url": "https://gpt5.shupremium.com",
        "source_type": "newapi",
        "enabled": 1,
        "public_pricing_enabled": 1,
        "public_balance_enabled": 1,
        "public_keys_enabled": 1,
        "public_logs_enabled": 1,
        "balance_rate": 1.0,
    },
    {
        "id": "sv1",
        "name": "SV1",
        "upstream_base_url": "https://api.zhongzhuan.chat",
        "public_base_url": "https://sv1.shupremium.com",
        "source_type": "newapi",
        "enabled": 1,
        "public_pricing_enabled": 0,
        "public_balance_enabled": 0,
        "public_keys_enabled": 0,
        "public_logs_enabled": 0,
        "balance_rate": 1.0,
    },
    {
        "id": "sv2",
        "name": "SV2",
        "upstream_base_url": "https://kfcv50.link",
        "public_base_url": "https://sv2.shupremium.com",
        "source_type": "newapi",
        "enabled": 1,
        "public_pricing_enabled": 0,
        "public_balance_enabled": 0,
        "public_keys_enabled": 0,
        "public_logs_enabled": 0,
        "balance_rate": 1.0,
    },
)

_SEED_PROXY_ENDPOINTS = (
    ("gpt1", "gpt1", "GPT1", "gpt1.shupremium.com", "api.aabao.top", "https", 0, 3001, "active"),
    ("gpt2", "gpt2", "GPT2", "gpt2.shupremium.com", "api.996444.cn", "https", 0, 3002, "active"),
    ("gpt3", "", "GPT3", "gpt3.shupremium.com", "www.mnapi.com", "https", 0, 3003, "active"),
    ("gpt4", "gpt4", "GPT4", "gpt4.shupremium.com", "api.kksj.org", "https", 0, 3004, "active"),
    ("gpt5", "gpt5", "GPT5", "gpt5.shupremium.com", "new.xjai.cc", "https", 0, 3005, "active"),
    ("sv1", "sv1", "SV1", "sv1.shupremium.com", "api.zhongzhuan.chat", "https", 0, 4001, "active"),
    ("sv2", "sv2", "SV2", "sv2.shupremium.com", "kfcv50.link", "https", 0, 4002, "active"),
)

_SEED_PORTAL_MODULES = (
    ("pricing", "Pricing Catalog", "/pricing", "https://shupremium.com/pricing", "table", "Public pricing and model catalog", 1, 1, 10),
    ("balance", "Balance Checker", "/check-balance", "https://shupremium.com/check-balance", "wallet2", "Secure balance checker for supported servers", 1, 1, 20),
    ("status", "Service Status", "/status", "https://shupremium.com/status", "activity", "Public proxy and service health surface", 1, 1, 30),
    ("docs", "Docs", "/docs", "", "book", "Operator and customer documentation shell", 1, 0, 40),
)


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        db_path = Path(get_settings().db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _db = await aiosqlite.connect(str(db_path))
        _db.row_factory = aiosqlite.Row
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.execute("PRAGMA foreign_keys=ON")
    return _db


async def init_db() -> None:
    db = await get_db()
    await db.executescript(CREATE_TABLES)
    await _ensure_schema(db)
    await _seed_data(db)
    await db.commit()


async def close_db() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None


async def _seed_data(db: aiosqlite.Connection) -> None:
    for item in _SEED_SERVICE_SOURCES:
        await db.execute(
            """
            INSERT OR IGNORE INTO service_sources (
                id, name, upstream_base_url, public_base_url, source_type, enabled,
                public_pricing_enabled, public_balance_enabled, public_keys_enabled, public_logs_enabled, balance_rate
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["id"],
                item["name"],
                item["upstream_base_url"],
                item["public_base_url"],
                item["source_type"],
                item["enabled"],
                item["public_pricing_enabled"],
                item["public_balance_enabled"],
                item["public_keys_enabled"],
                item["public_logs_enabled"],
                item["balance_rate"],
            ),
        )

    cursor = await db.execute("PRAGMA table_info(proxy_endpoints)")
    columns = {row[1] for row in await cursor.fetchall()}
    if "tls_skip_verify" not in columns:
        await db.execute("ALTER TABLE proxy_endpoints ADD COLUMN tls_skip_verify INTEGER NOT NULL DEFAULT 0")

    for endpoint_id, source_id, name, domain, target_host, target_protocol, tls_skip_verify, port, status in _SEED_PROXY_ENDPOINTS:
        await db.execute(
            """
            INSERT OR IGNORE INTO proxy_endpoints (
                id, source_id, name, domain, target_host, target_protocol, tls_skip_verify, port, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (endpoint_id, source_id or None, name, domain, target_host, target_protocol, tls_skip_verify, port, status),
        )

    for module in _SEED_PORTAL_MODULES:
        await db.execute(
            """
            INSERT OR IGNORE INTO portal_modules (
                id, name, path, public_url, icon, description, enabled, is_public, sort_order
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            module,
        )

    runtime_defaults = {
        "ai_provider": "openai",
        "ai_api_key": "",
        "ai_model": "gpt-4o-mini",
        "ai_base_url": "",
        "ai_enabled": "false",
        "auto_sync_enabled": "false",
        "auto_sync_interval_minutes": "15",
    }
    for key, value in runtime_defaults.items():
        await db.execute(
            """
            INSERT OR IGNORE INTO pricing_runtime_settings (key, value)
            VALUES (?, ?)
            """,
            (key, value),
        )


async def _ensure_schema(db: aiosqlite.Connection) -> None:
    cursor = await db.execute("PRAGMA table_info(service_sources)")
    columns = {row[1] for row in await cursor.fetchall()}
    service_source_columns = {
        "sort_order": "INTEGER NOT NULL DEFAULT 0",
        "quota_multiple": "REAL NOT NULL DEFAULT 1.0",
        "supports_group_chain": "INTEGER NOT NULL DEFAULT 0",
        "ratio_config_enabled": "INTEGER NOT NULL DEFAULT 0",
        "public_keys_enabled": "INTEGER NOT NULL DEFAULT 1",
        "public_logs_enabled": "INTEGER NOT NULL DEFAULT 1",
        "groups_path": "TEXT",
        "manual_groups": "TEXT",
        "hidden_groups": "TEXT",
        "excluded_models": "TEXT",
    }
    for column, ddl in service_source_columns.items():
        if column not in columns:
            await db.execute(f"ALTER TABLE service_sources ADD COLUMN {column} {ddl}")

    cursor = await db.execute("PRAGMA table_info(proxy_endpoints)")
    columns = {row[1] for row in await cursor.fetchall()}
    if "tls_skip_verify" not in columns:
        await db.execute("ALTER TABLE proxy_endpoints ADD COLUMN tls_skip_verify INTEGER NOT NULL DEFAULT 0")
