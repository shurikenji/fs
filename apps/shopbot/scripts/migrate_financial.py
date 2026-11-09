"""Apply the financial schema migration to an existing, backed-up SQLite database."""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db.financial_migration import migrate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path, help="Path to an existing backed-up Shopbot database")
    args = parser.parse_args()
    path = args.database.resolve(strict=True)
    if not path.is_file():
        parser.error("database must be an existing file")
    connection = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=5)
    try:
        applied = migrate(connection)
        print("Financial migration applied." if applied else "Financial migration already applied.")
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
