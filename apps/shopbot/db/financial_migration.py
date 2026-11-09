"""Explicit, transactional schema migration for payment and fulfillment state."""
from __future__ import annotations

import sqlite3

VERSION = "financial_fulfillment_v1"
REQUIRED_TABLES = frozenset({"payment_receipts", "fulfillment_jobs", "fulfillment_operations", "notification_outbox", "worker_status"})
REQUIRED_COLUMNS = {
    "wallet_transactions": {"operation_key"},
    "payment_receipts": {"provider", "account_identity", "transaction_id", "amount", "transaction_time", "order_code", "description", "status", "order_id", "last_error"},
    "fulfillment_jobs": {"order_id", "job_type", "status", "attempts", "lease_token", "lease_until", "next_attempt_at"},
    "fulfillment_operations": {"job_id", "operation_key", "item_index", "status", "remote_id", "sent_at", "result_summary"},
    "notification_outbox": {"event_key", "event_type", "order_id", "user_id", "status", "attempts", "lease_token", "lease_until", "next_attempt_at"},
}
REQUIRED_UNIQUE_INDEX = "idx_wallet_transactions_operation_key"

_STATEMENTS = (
    """CREATE TABLE payment_receipts (
        id INTEGER PRIMARY KEY, provider TEXT NOT NULL, account_identity TEXT NOT NULL,
        transaction_id TEXT NOT NULL, amount INTEGER NOT NULL CHECK(amount > 0),
        transaction_time TEXT, observed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        order_code TEXT, description TEXT, last_error TEXT,
        status TEXT NOT NULL, order_id INTEGER REFERENCES orders(id),
        UNIQUE(provider, account_identity, transaction_id)
    )""",
    "CREATE INDEX idx_payment_receipts_status ON payment_receipts(status, order_id)",
    """CREATE TABLE fulfillment_jobs (
        id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id),
        job_type TEXT NOT NULL, status TEXT NOT NULL, next_attempt_at TEXT,
        attempts INTEGER NOT NULL DEFAULT 0, lease_owner TEXT, lease_token TEXT,
        lease_until TEXT, last_error TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(order_id, job_type)
    )""",
    "CREATE INDEX idx_fulfillment_jobs_pending ON fulfillment_jobs(status, next_attempt_at)",
    """CREATE TABLE fulfillment_operations (
        id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES fulfillment_jobs(id),
        item_index INTEGER NOT NULL, operation_key TEXT NOT NULL UNIQUE,
        resource_identity TEXT, status TEXT NOT NULL, remote_id TEXT, sent_at TEXT,
        result_summary TEXT, last_error TEXT, UNIQUE(job_id, item_index)
    )""",
    "CREATE INDEX idx_fulfillment_operations_resource ON fulfillment_operations(resource_identity, status)",
    """CREATE TABLE notification_outbox (
        id INTEGER PRIMARY KEY, event_key TEXT NOT NULL UNIQUE, event_type TEXT NOT NULL,
        order_id INTEGER REFERENCES orders(id), user_id INTEGER REFERENCES users(id),
        status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at TEXT,
        lease_token TEXT, lease_until TEXT, last_error TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    "CREATE INDEX idx_notification_outbox_pending ON notification_outbox(status, next_attempt_at)",
    """CREATE TABLE worker_status (
        component TEXT PRIMARY KEY, instance_id TEXT, heartbeat_at TEXT,
        last_success_at TEXT, mode TEXT, last_error TEXT
    )""",
    "CREATE UNIQUE INDEX idx_wallet_transactions_operation_key ON wallet_transactions(operation_key) WHERE operation_key IS NOT NULL",
)


def migrate(connection: sqlite3.Connection) -> bool:
    """Apply this migration once; never backfill unknown historical operations."""
    if connection.in_transaction:
        raise RuntimeError("migration requires its own transaction")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("BEGIN IMMEDIATE")
    try:
        connection.execute("""CREATE TABLE IF NOT EXISTS shopbot_schema_migrations (
            version TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        if connection.execute("SELECT 1 FROM shopbot_schema_migrations WHERE version = ?", (VERSION,)).fetchone():
            connection.rollback()
            return False
        columns = {row[1] for row in connection.execute("PRAGMA table_info(wallet_transactions)")}
        if not columns:
            raise RuntimeError("wallet_transactions does not exist")
        if "operation_key" not in columns:
            connection.execute("ALTER TABLE wallet_transactions ADD COLUMN operation_key TEXT")
        for statement in _STATEMENTS:
            connection.execute(statement)
        connection.execute("INSERT INTO shopbot_schema_migrations(version) VALUES (?)", (VERSION,))
        connection.commit()
        return True
    except BaseException:
        connection.rollback()
        raise
