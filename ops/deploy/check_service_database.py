"""Validate existing shared Portal/Control databases without writing to them."""
import sqlite3
from contextlib import closing
from pathlib import Path


REQUIRED_TABLES = {
    "portal": {"servers", "app_settings"},
    "platform-control": {"service_sources", "proxy_endpoints", "portal_modules"},
}


def check_combined_bind(app: str, host: str, port: int, role: str) -> None:
    if role != "combined":
        return
    expected = {"portal": 8080, "platform-control": 8090}
    if app not in expected or host != "127.0.0.1" or port != expected[app]:
        raise ValueError("Combined service must use its assigned loopback host and port")


def check_database(app: str, database: str, data_root: str) -> None:
    if app not in REQUIRED_TABLES:
        raise ValueError("Unsupported service database")
    path = Path(database)
    if not path.is_absolute():
        raise ValueError("DB_PATH must be an absolute path")
    resolved = path.resolve(strict=True)
    root = Path(data_root).resolve(strict=True)
    if not root.is_dir() or not resolved.is_file() or not resolved.is_relative_to(root):
        raise ValueError("DB_PATH must be an existing file inside the shared data directory")
    with closing(sqlite3.connect(resolved.as_uri() + "?mode=ro", uri=True)) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if not REQUIRED_TABLES[app] <= tables:
            raise ValueError("Shared database is missing required tables")
