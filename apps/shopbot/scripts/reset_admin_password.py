"""Set the Shopbot admin password without putting it in shell history."""
from __future__ import annotations

import argparse
import getpass
import hmac
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from admin.passwords import hash_password


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path, help="Path to the existing Shopbot database")
    args = parser.parse_args()
    path = args.database.resolve(strict=True)
    if not path.is_file():
        parser.error("database must be an existing file")
    password = getpass.getpass("Mật khẩu mới: ")
    confirmation = getpass.getpass("Nhập lại mật khẩu: ")
    if not 12 <= len(password) <= 1024 or not hmac.compare_digest(password.encode(), confirmation.encode()):
        print("Mật khẩu không khớp hoặc không dài từ 12 đến 1024 ký tự.", file=sys.stderr)
        return 1
    connection = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=5)
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """INSERT INTO settings(key, value, description) VALUES ('admin_password', ?, 'Mật khẩu admin panel')
               ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now', '+7 hours')""",
            (hash_password(password),),
        )
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()
    print("Đã cập nhật mật khẩu admin.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
