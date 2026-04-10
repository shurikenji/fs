"""
Database schema bootstrap and best-effort migrations.
"""
from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterable

from db.database import get_db
from db.models import _CREATE_TABLES, _DEFAULT_SETTINGS

logger = logging.getLogger(__name__)

_GMT7_NOW_SQL = "datetime('now', '+7 hours')"
_TIMEZONE_MIGRATION_KEY = "timezone_gmt7_sync_v1"

_BEST_EFFORT_MIGRATIONS = [
    "ALTER TABLE users ADD COLUMN disable_discounts INTEGER DEFAULT 0",
    "ALTER TABLE api_servers ADD COLUMN quota_multiple REAL NOT NULL DEFAULT 1.0",
    "ALTER TABLE orders ADD COLUMN custom_quota INTEGER",
    "ALTER TABLE orders ADD COLUMN quantity INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE api_servers ADD COLUMN default_group TEXT",
    "ALTER TABLE products ADD COLUMN format_template TEXT",
    "ALTER TABLE products ADD COLUMN input_prompt TEXT",
    "ALTER TABLE api_servers ADD COLUMN api_type TEXT DEFAULT 'newapi'",
    "ALTER TABLE api_servers ADD COLUMN supports_multi_group INTEGER DEFAULT 0",
    "ALTER TABLE api_servers ADD COLUMN groups_cache TEXT",
    "ALTER TABLE api_servers ADD COLUMN groups_updated_at TEXT",
    "ALTER TABLE api_servers ADD COLUMN manual_groups TEXT",
    "ALTER TABLE api_servers ADD COLUMN auth_type TEXT DEFAULT 'header'",
    "ALTER TABLE api_servers ADD COLUMN auth_user_header TEXT",
    "ALTER TABLE api_servers ADD COLUMN auth_user_value TEXT",
    "ALTER TABLE api_servers ADD COLUMN auth_token TEXT",
    "ALTER TABLE api_servers ADD COLUMN auth_cookie TEXT",
    "ALTER TABLE api_servers ADD COLUMN custom_headers TEXT",
    "ALTER TABLE api_servers ADD COLUMN groups_endpoint TEXT",
    "ALTER TABLE api_servers ADD COLUMN import_spend_accrual_enabled INTEGER DEFAULT 0",
    "ALTER TABLE api_servers ADD COLUMN discount_stack_mode TEXT DEFAULT 'exclusive'",
    "ALTER TABLE api_servers ADD COLUMN discount_allowed_stack_types TEXT DEFAULT 'cashback'",
    "ALTER TABLE api_servers ADD COLUMN supports_key_lookup_by_id INTEGER DEFAULT 0",
    "ALTER TABLE api_servers ADD COLUMN token_key_endpoint_template TEXT DEFAULT '/api/token/{id}/key'",
    "ALTER TABLE orders ADD COLUMN base_amount INTEGER",
    "ALTER TABLE orders ADD COLUMN discount_amount INTEGER DEFAULT 0",
    "ALTER TABLE orders ADD COLUMN cashback_amount INTEGER DEFAULT 0",
    "ALTER TABLE orders ADD COLUMN spend_credit_amount INTEGER DEFAULT 0",
    "ALTER TABLE orders ADD COLUMN pricing_version_id INTEGER",
    "ALTER TABLE orders ADD COLUMN applied_tier_id INTEGER",
    "ALTER TABLE orders ADD COLUMN pricing_snapshot TEXT",
    "ALTER TABLE orders ADD COLUMN promotion_snapshot TEXT",
    "ALTER TABLE orders ADD COLUMN completed_at TEXT",
    "ALTER TABLE orders ADD COLUMN api_token_name TEXT",
    "ALTER TABLE orders ADD COLUMN delivery_token_names TEXT",
    """UPDATE orders
       SET completed_at = COALESCE(NULLIF(paid_at, ''), NULLIF(updated_at, ''))
       WHERE status = 'completed'
         AND (completed_at IS NULL OR completed_at = '')""",
    "CREATE INDEX IF NOT EXISTS idx_ord_completed_at ON orders(completed_at)",
    "CREATE INDEX IF NOT EXISTS idx_ord_refunded_at ON orders(refunded_at)",
    """UPDATE orders
       SET payment_method = 'wallet',
           updated_at = datetime('now', '+7 hours')
       WHERE payment_method = 'qr'
         AND EXISTS (
             SELECT 1
             FROM wallet_transactions wt
             WHERE wt.user_id = orders.user_id
               AND wt.reference_id = orders.order_code
               AND wt.type = 'purchase'
               AND wt.amount = -orders.amount
         )""",
]

_INSERT_TRIGGER_COLUMNS: dict[str, tuple[str, ...]] = {
    "users": ("created_at", "updated_at"),
    "wallets": ("created_at", "updated_at"),
    "wallet_transactions": ("created_at",),
    "api_servers": ("created_at", "updated_at"),
    "categories": ("created_at", "updated_at"),
    "products": ("created_at", "updated_at"),
    "account_stocks": ("created_at",),
    "orders": ("created_at", "updated_at"),
    "server_pricing_versions": ("created_at",),
    "server_discount_tiers": ("created_at", "updated_at"),
    "server_tier_benefits": ("created_at", "updated_at"),
    "product_promotions": ("created_at", "updated_at"),
    "user_keys": ("created_at", "updated_at"),
    "api_key_registry": ("first_seen_at", "last_seen_at"),
    "api_key_valuation_events": ("created_at",),
    "api_key_alert_states": ("last_checked_at", "created_at", "updated_at"),
    "spend_ledger": ("created_at",),
    "user_server_spend_summary": ("created_at", "updated_at"),
    "admin_notification_events": ("created_at", "updated_at"),
    "fsm_storage": ("updated_at",),
    "settings": ("updated_at",),
    "processed_transactions": ("processed_at",),
    "logs": ("created_at",),
    "group_translations": ("updated_at",),
}

_UPDATE_TRIGGER_COLUMNS: dict[str, tuple[str, ...]] = {
    "users": ("updated_at",),
    "wallets": ("updated_at",),
    "api_servers": ("updated_at",),
    "categories": ("updated_at",),
    "products": ("updated_at",),
    "orders": ("updated_at",),
    "server_discount_tiers": ("updated_at",),
    "server_tier_benefits": ("updated_at",),
    "product_promotions": ("updated_at",),
    "user_keys": ("updated_at",),
    "api_key_registry": ("last_seen_at",),
    "api_key_alert_states": ("last_checked_at", "updated_at"),
    "user_server_spend_summary": ("updated_at",),
    "admin_notification_events": ("updated_at",),
    "fsm_storage": ("updated_at",),
    "settings": ("updated_at",),
    "group_translations": ("updated_at",),
}

_TIMEZONE_BACKFILL_STATEMENTS = [
    "UPDATE users SET created_at = datetime(created_at, '+7 hours') WHERE created_at IS NOT NULL",
    "UPDATE wallets SET created_at = datetime(created_at, '+7 hours') WHERE created_at IS NOT NULL",
    "UPDATE wallet_transactions SET created_at = datetime(created_at, '+7 hours') WHERE created_at IS NOT NULL",
    "UPDATE api_servers SET created_at = datetime(created_at, '+7 hours') WHERE created_at IS NOT NULL",
    "UPDATE api_servers SET groups_updated_at = datetime(groups_updated_at, '+7 hours') WHERE groups_updated_at IS NOT NULL",
    "UPDATE categories SET created_at = datetime(created_at, '+7 hours') WHERE created_at IS NOT NULL",
    "UPDATE products SET created_at = datetime(created_at, '+7 hours') WHERE created_at IS NOT NULL",
    "UPDATE account_stocks SET created_at = datetime(created_at, '+7 hours') WHERE created_at IS NOT NULL",
    "UPDATE orders SET created_at = datetime(created_at, '+7 hours') WHERE created_at IS NOT NULL",
    "UPDATE orders SET updated_at = datetime(updated_at, '+7 hours') WHERE updated_at IS NOT NULL",
    "UPDATE orders SET paid_at = datetime(paid_at, '+7 hours') WHERE paid_at IS NOT NULL AND paid_at != ''",
    "UPDATE orders SET completed_at = datetime(completed_at, '+7 hours') WHERE completed_at IS NOT NULL AND completed_at != ''",
    "UPDATE orders SET refunded_at = datetime(refunded_at, '+7 hours') WHERE refunded_at IS NOT NULL AND refunded_at != ''",
    "UPDATE orders SET expired_at = datetime(expired_at, '+7 hours') WHERE expired_at IS NOT NULL AND expired_at != ''",
    "UPDATE server_pricing_versions SET created_at = datetime(created_at, '+7 hours') WHERE created_at IS NOT NULL",
    "UPDATE server_discount_tiers SET created_at = datetime(created_at, '+7 hours') WHERE created_at IS NOT NULL",
    "UPDATE server_tier_benefits SET created_at = datetime(created_at, '+7 hours') WHERE created_at IS NOT NULL",
    "UPDATE product_promotions SET created_at = datetime(created_at, '+7 hours') WHERE created_at IS NOT NULL",
    "UPDATE user_keys SET created_at = datetime(created_at, '+7 hours') WHERE created_at IS NOT NULL",
    "UPDATE api_key_registry SET first_seen_at = datetime(first_seen_at, '+7 hours') WHERE first_seen_at IS NOT NULL",
    "UPDATE api_key_registry SET last_seen_at = datetime(last_seen_at, '+7 hours') WHERE last_seen_at IS NOT NULL",
    "UPDATE api_key_valuation_events SET created_at = datetime(created_at, '+7 hours') WHERE created_at IS NOT NULL",
    "UPDATE api_key_alert_states SET last_alert_sent_at = datetime(last_alert_sent_at, '+7 hours') WHERE last_alert_sent_at IS NOT NULL AND last_alert_sent_at != ''",
    "UPDATE api_key_alert_states SET last_checked_at = datetime(last_checked_at, '+7 hours') WHERE last_checked_at IS NOT NULL",
    "UPDATE api_key_alert_states SET created_at = datetime(created_at, '+7 hours') WHERE created_at IS NOT NULL",
    "UPDATE spend_ledger SET created_at = datetime(created_at, '+7 hours') WHERE created_at IS NOT NULL",
    "UPDATE user_server_spend_summary SET created_at = datetime(created_at, '+7 hours') WHERE created_at IS NOT NULL",
    "UPDATE admin_notification_events SET sent_at = datetime(sent_at, '+7 hours') WHERE sent_at IS NOT NULL AND sent_at != ''",
    "UPDATE admin_notification_events SET created_at = datetime(created_at, '+7 hours') WHERE created_at IS NOT NULL",
    "UPDATE processed_transactions SET processed_at = datetime(processed_at, '+7 hours') WHERE processed_at IS NOT NULL",
    "UPDATE logs SET created_at = datetime(created_at, '+7 hours') WHERE created_at IS NOT NULL",
]


def _iter_statements(script: str) -> Iterable[str]:
    """Split a SQL script into non-empty statements."""
    for statement in script.split(";"):
        statement = statement.strip()
        if statement:
            yield statement


def _can_ignore_migration_error(error: Exception) -> bool:
    """Ignore only known idempotent migration errors."""
    if not isinstance(error, sqlite3.OperationalError):
        return False
    return "duplicate column name" in str(error).lower()


def _build_timestamp_trigger_statements() -> list[str]:
    statements: list[str] = []

    for table, columns in _INSERT_TRIGGER_COLUMNS.items():
        assignments = ", ".join(f"{column} = {_GMT7_NOW_SQL}" for column in columns)
        statements.append(
            f"""CREATE TRIGGER IF NOT EXISTS trg_{table}_gmt7_insert
AFTER INSERT ON {table}
FOR EACH ROW
BEGIN
    UPDATE {table}
       SET {assignments}
     WHERE rowid = NEW.rowid;
END"""
        )

    for table, columns in _UPDATE_TRIGGER_COLUMNS.items():
        assignments = ", ".join(f"{column} = {_GMT7_NOW_SQL}" for column in columns)
        statements.append(
            f"""CREATE TRIGGER IF NOT EXISTS trg_{table}_gmt7_update
AFTER UPDATE ON {table}
FOR EACH ROW
BEGIN
    UPDATE {table}
       SET {assignments}
     WHERE rowid = NEW.rowid;
END"""
        )

    return statements


_TIMESTAMP_TRIGGER_STATEMENTS = _build_timestamp_trigger_statements()


async def _apply_tables(db) -> None:
    """Create tables from the current DDL (skip indexes)."""
    for statement in _iter_statements(_CREATE_TABLES):
        if not statement.lstrip().upper().startswith("CREATE INDEX"):
            await db.execute(statement)


async def _apply_indexes(db) -> None:
    """Create indexes from the current DDL."""
    for statement in _iter_statements(_CREATE_TABLES):
        if statement.lstrip().upper().startswith("CREATE INDEX"):
            await db.execute(statement)


async def _apply_best_effort_migrations(db) -> None:
    """Apply safe migrations for older databases."""
    for statement in _BEST_EFFORT_MIGRATIONS:
        try:
            await db.execute(statement)
        except Exception as exc:
            if _can_ignore_migration_error(exc):
                continue
            logger.warning("Database migration failed: %s", statement)
            raise


async def _apply_timestamp_triggers(db) -> None:
    """Install GMT+7 timestamp triggers for existing SQLite databases."""
    for statement in _TIMESTAMP_TRIGGER_STATEMENTS:
        await db.execute(statement)


async def _backfill_timezone_columns(db) -> None:
    """One-time conversion of legacy UTC timestamps to GMT+7."""
    cursor = await db.execute(
        "SELECT value FROM settings WHERE key = ?",
        (_TIMEZONE_MIGRATION_KEY,),
    )
    row = await cursor.fetchone()
    if row and row[0] == "1":
        return

    for statement in _TIMEZONE_BACKFILL_STATEMENTS:
        await db.execute(statement)

    await db.execute(
        """INSERT INTO settings (key, value, description, updated_at)
           VALUES (?, '1', 'Legacy UTC timestamps converted to GMT+7', datetime('now', '+7 hours'))
           ON CONFLICT(key) DO UPDATE SET
               value = excluded.value,
               description = excluded.description,
               updated_at = excluded.updated_at""",
        (_TIMEZONE_MIGRATION_KEY,),
    )


async def init_db() -> None:
    """Initialize schema, migrations, settings, and timezone sync."""
    db = await get_db()
    await _apply_tables(db)
    await _apply_best_effort_migrations(db)
    await _apply_indexes(db)
    await _apply_timestamp_triggers(db)
    await db.executemany(
        "INSERT OR IGNORE INTO settings (key, value, description) VALUES (?, ?, ?)",
        _DEFAULT_SETTINGS,
    )
    await _backfill_timezone_columns(db)
    await db.commit()
    logger.info("Database bootstrap complete.")
