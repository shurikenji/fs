"""Read-only checks required before switching a Shopbot release."""
from __future__ import annotations

import argparse
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bot.config import settings
from bot.main import validate_runtime_secrets
from db.financial_migration import REQUIRED_COLUMNS, REQUIRED_TABLES, REQUIRED_UNIQUE_INDEX, VERSION


def check_combined_bind(role: str, host: str, port: int) -> None:
    if role == "combined" and (host != "127.0.0.1" or port != 8092):
        raise ValueError("Combined Shopbot admin must use 127.0.0.1:8092")


def check_database(database: str, data_root: str) -> None:
    path = Path(database)
    if not path.is_absolute():
        raise ValueError("DB_PATH must be an absolute path")
    resolved = path.resolve(strict=True)
    root = Path(data_root).resolve(strict=True)
    if not root.is_dir() or not resolved.is_file() or not resolved.is_relative_to(root):
        raise ValueError("DB_PATH must be a database file inside the shared data directory")
    with closing(sqlite3.connect(resolved.as_uri() + "?mode=ro", uri=True)) as db:
        table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='shopbot_schema_migrations'").fetchone()
        if not table or not db.execute("SELECT 1 FROM shopbot_schema_migrations WHERE version = ?", (VERSION,)).fetchone():
            raise ValueError("Explicit financial migration is required")
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if not REQUIRED_TABLES <= tables:
            raise ValueError("Financial schema is incomplete")
        for table, columns in REQUIRED_COLUMNS.items():
            if not columns <= {row[1] for row in db.execute(f"PRAGMA table_info({table})")}:
                raise ValueError("Financial schema is incomplete")
        if not any(row[1] == REQUIRED_UNIQUE_INDEX and row[2] == 1 for row in db.execute("PRAGMA index_list(wallet_transactions)")):
            raise ValueError("Financial schema is incomplete")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--role", required=True)
    args = parser.parse_args()
    validate_runtime_secrets()
    check_combined_bind(args.role, settings.admin_host, settings.admin_port)
    check_database(settings.db_path, args.data_root)
    print("Shopbot secret and financial schema checks passed")


if __name__ == "__main__":
    main()
