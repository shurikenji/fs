"""Async SQLite database connection and initialization."""
from __future__ import annotations

import logging
from pathlib import Path
from datetime import datetime, timezone

import aiosqlite

from app.config import get_settings

logger = logging.getLogger(__name__)

_db: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        settings = get_settings()
        db_path = Path(settings.db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _db = await aiosqlite.connect(str(db_path))
        _db.row_factory = aiosqlite.Row
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.execute("PRAGMA foreign_keys=ON")
    return _db


async def init_db() -> None:
    """Create tables on first startup."""
    from db.models import CREATE_TABLES

    db = await get_db()
    await db.executescript(CREATE_TABLES)
    await _ensure_server_columns(db)
    await _ensure_sync_log_columns(db)
    await _seed_default_data(db)
    await db.commit()
    logger.info("Database initialized at %s", get_settings().db_path)


async def close_db() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None


async def _ensure_server_columns(db: aiosqlite.Connection) -> None:
    cursor = await db.execute("PRAGMA table_info(servers)")
    rows = await cursor.fetchall()
    columns = {str(row[1]) for row in rows}
    if "quota_multiple" not in columns:
        await db.execute("ALTER TABLE servers ADD COLUMN quota_multiple REAL DEFAULT 1.0")
    if "balance_rate" not in columns:
        await db.execute("ALTER TABLE servers ADD COLUMN balance_rate REAL DEFAULT 1.0")
    if "public_pricing_enabled" not in columns:
        await db.execute("ALTER TABLE servers ADD COLUMN public_pricing_enabled INTEGER DEFAULT 1")
    if "public_balance_enabled" not in columns:
        await db.execute("ALTER TABLE servers ADD COLUMN public_balance_enabled INTEGER DEFAULT 0")
    if "public_keys_enabled" not in columns:
        await db.execute("ALTER TABLE servers ADD COLUMN public_keys_enabled INTEGER DEFAULT 1")
    if "public_logs_enabled" not in columns:
        await db.execute("ALTER TABLE servers ADD COLUMN public_logs_enabled INTEGER DEFAULT 1")
    if "manual_groups" not in columns:
        await db.execute("ALTER TABLE servers ADD COLUMN manual_groups TEXT")
    if "hidden_groups" not in columns:
        await db.execute("ALTER TABLE servers ADD COLUMN hidden_groups TEXT")
    if "excluded_models" not in columns:
        await db.execute("ALTER TABLE servers ADD COLUMN excluded_models TEXT")
    if "parser_override" not in columns:
        await db.execute("ALTER TABLE servers ADD COLUMN parser_override TEXT")
    if "display_profile" not in columns:
        await db.execute("ALTER TABLE servers ADD COLUMN display_profile TEXT")
    if "endpoint_aliases_json" not in columns:
        await db.execute("ALTER TABLE servers ADD COLUMN endpoint_aliases_json TEXT")
    if "variant_pricing_mode" not in columns:
        await db.execute("ALTER TABLE servers ADD COLUMN variant_pricing_mode TEXT")


async def _ensure_sync_log_columns(db: aiosqlite.Connection) -> None:
    cursor = await db.execute("PRAGMA table_info(sync_log)")
    rows = await cursor.fetchall()
    columns = {str(row[1]) for row in rows}
    if "trigger" not in columns:
        await db.execute("ALTER TABLE sync_log ADD COLUMN trigger TEXT DEFAULT 'manual'")


def _build_demo_pricing_json() -> str:
    from app.schemas import (
        GroupPriceSnapshot,
        NormalizedGroup,
        NormalizedModel,
        NormalizedPricing,
        PricingMode,
    )

    pricing = NormalizedPricing(
        server_id="demo",
        server_name="Demo Pricing Server",
        groups=[
            NormalizedGroup(
                name="default",
                display_name="Default",
                ratio=1.0,
                description="Balanced access for general workloads.",
                category="General",
            ),
            NormalizedGroup(
                name="premium",
                display_name="Premium",
                ratio=1.35,
                description="Higher SLA and premium routing.",
                category="Premium",
            ),
        ],
        models=[
            NormalizedModel(
                model_name="gpt-4.1-mini",
                description="Fast general-purpose chat model.",
                vendor_name="OpenAI",
                tags=["chat"],
                pricing_mode=PricingMode.token,
                model_ratio=0.2,
                completion_ratio=4.0,
                input_price_per_1m=0.4,
                output_price_per_1m=1.6,
                enable_groups=["default", "premium"],
                supported_endpoints=["/v1/chat/completions"],
                group_prices={
                    "default": GroupPriceSnapshot(
                        group_name="default",
                        group_display_name="Default",
                        group_ratio=1.0,
                        pricing_mode=PricingMode.token,
                        input_price_per_1m=0.4,
                        output_price_per_1m=1.6,
                    ),
                    "premium": GroupPriceSnapshot(
                        group_name="premium",
                        group_display_name="Premium",
                        group_ratio=1.35,
                        pricing_mode=PricingMode.token,
                        input_price_per_1m=0.54,
                        output_price_per_1m=2.16,
                    ),
                },
            ),
            NormalizedModel(
                model_name="claude-sonnet-4",
                description="Higher quality reasoning and coding.",
                vendor_name="Anthropic",
                tags=["chat", "thinking"],
                pricing_mode=PricingMode.token,
                model_ratio=1.5,
                completion_ratio=5.0,
                input_price_per_1m=3.0,
                output_price_per_1m=15.0,
                enable_groups=["default", "premium"],
                supported_endpoints=["/v1/chat/completions", "/v1/messages"],
                group_prices={
                    "default": GroupPriceSnapshot(
                        group_name="default",
                        group_display_name="Default",
                        group_ratio=1.0,
                        pricing_mode=PricingMode.token,
                        input_price_per_1m=3.0,
                        output_price_per_1m=15.0,
                    ),
                    "premium": GroupPriceSnapshot(
                        group_name="premium",
                        group_display_name="Premium",
                        group_ratio=1.35,
                        pricing_mode=PricingMode.token,
                        input_price_per_1m=4.05,
                        output_price_per_1m=20.25,
                    ),
                },
            ),
            NormalizedModel(
                model_name="flux-schnell",
                description="Image generation priced per request.",
                vendor_name="Black Forest Labs",
                tags=["vision", "image"],
                pricing_mode=PricingMode.fixed,
                model_price=0.02,
                request_price=0.02,
                enable_groups=["default"],
                supported_endpoints=["/v1/images/generations"],
                group_prices={
                    "default": GroupPriceSnapshot(
                        group_name="default",
                        group_display_name="Default",
                        group_ratio=1.0,
                        pricing_mode=PricingMode.fixed,
                        request_price=0.02,
                    ),
                },
            ),
        ],
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )
    return pricing.model_dump_json()


async def _seed_default_data(db: aiosqlite.Connection) -> None:
    settings = get_settings()
    if not settings.seed_demo_server:
        return

    cursor = await db.execute("SELECT COUNT(*) FROM servers")
    row = await cursor.fetchone()
    if row and int(row[0]) > 0:
        return

    await db.execute(
        """
        INSERT INTO servers (
            id, name, base_url, type, enabled, sort_order,
            supports_group_chain, ratio_config_enabled,
            auth_mode, pricing_path, ratio_config_path,
            log_path, token_search_path, notes,
            pricing_cache, pricing_fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "demo",
            "Demo Pricing Server",
            "https://demo.local",
            "custom",
            1,
            0,
            1,
            0,
            "none",
            "/api/pricing",
            "/api/ratio_config",
            "/api/log/self",
            "/api/token/search",
            "Seeded automatically for first-run preview.",
            _build_demo_pricing_json(),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    logger.info("Seeded default demo server")
