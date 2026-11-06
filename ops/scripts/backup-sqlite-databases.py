#!/usr/bin/env python3
"""Create verified online backups of Shupremium SQLite databases."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import socket
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path


DEFAULT_DATABASES = {
    "portal": Path("/srv/shupremium-stack/shared/portal/data/hub.db"),
    "platform-control": Path(
        "/srv/shupremium-stack/shared/platform-control/data/platform_control.db"
    ),
    "shopbot": Path("/srv/shupremium-stack/shared/shopbot/data/shopbot.db"),
    "key-vault": Path(
        "/srv/shupremium-stack/shared/key-vault-worker/data/key_vault.db"
    ),
}
RUN_NAME = re.compile(r"^\d{8}T\d{6}Z$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_database(value: str) -> tuple[str, Path]:
    label, separator, raw_path = value.partition("=")
    if not separator or not label or not raw_path:
        raise argparse.ArgumentTypeError("database must use LABEL=/absolute/path.db")
    path = Path(raw_path)
    if not path.is_absolute():
        raise argparse.ArgumentTypeError("database path must be absolute")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", label):
        raise argparse.ArgumentTypeError("database label contains invalid characters")
    return label, path


def backup_database(label: str, source: Path, run_dir: Path) -> dict[str, object]:
    resolved = source.resolve(strict=True)
    if not resolved.is_file():
        raise RuntimeError(f"{label}: source is not a file: {source}")

    raw_backup = run_dir / f".{label}.db.tmp"
    compressed = run_dir / f"{label}.db.gz"

    source_uri = resolved.as_uri() + "?mode=ro"
    with closing(sqlite3.connect(source_uri, uri=True, timeout=30)) as source_db:
        with closing(sqlite3.connect(raw_backup, timeout=30)) as backup_db:
            source_db.backup(backup_db, pages=4096, sleep=0.05)

    backup_uri = raw_backup.resolve(strict=True).as_uri() + "?mode=ro"
    with closing(sqlite3.connect(backup_uri, uri=True, timeout=30)) as verify_db:
        quick_check = verify_db.execute("PRAGMA quick_check").fetchone()
        if not quick_check or quick_check[0] != "ok":
            raise RuntimeError(f"{label}: SQLite quick_check failed")
        foreign_key_violation = verify_db.execute(
            "PRAGMA foreign_key_check"
        ).fetchone()
        if foreign_key_violation is not None:
            raise RuntimeError(f"{label}: SQLite foreign_key_check failed")

    raw_size = raw_backup.stat().st_size
    with raw_backup.open("rb") as source_stream:
        with gzip.open(compressed, "wb", compresslevel=1) as output_stream:
            shutil.copyfileobj(source_stream, output_stream, length=1024 * 1024)
    raw_backup.unlink()

    return {
        "label": label,
        "source": str(resolved),
        "backup": compressed.name,
        "uncompressed_bytes": raw_size,
        "compressed_bytes": compressed.stat().st_size,
        "sha256": sha256_file(compressed),
        "quick_check": "ok",
        "foreign_key_violations": 0,
    }


def prune_old_backups(backup_root: Path, retention_days: int, keep: Path) -> int:
    if retention_days <= 0:
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    removed = 0
    for candidate in backup_root.iterdir():
        if candidate == keep or not candidate.is_dir():
            continue
        if not RUN_NAME.fullmatch(candidate.name):
            continue
        timestamp = datetime.strptime(candidate.name, "%Y%m%dT%H%M%SZ").replace(
            tzinfo=timezone.utc
        )
        if timestamp >= cutoff:
            continue
        shutil.rmtree(candidate)
        removed += 1
    return removed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--backup-root",
        type=Path,
        default=Path(
            os.getenv(
                "SHUPREMIUM_BACKUP_ROOT",
                "/home/ubuntu/shupremium-backups/sqlite",
            )
        ),
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=int(os.getenv("SHUPREMIUM_BACKUP_RETENTION_DAYS", "14")),
    )
    parser.add_argument(
        "--db",
        action="append",
        type=parse_database,
        help="Override defaults with LABEL=/absolute/path.db; repeat as needed",
    )
    args = parser.parse_args()

    os.umask(0o077)
    if args.retention_days < 0:
        parser.error("--retention-days must be >= 0")

    databases = dict(args.db) if args.db else DEFAULT_DATABASES
    backup_root = args.backup_root.expanduser().resolve()
    backup_root.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    final_dir = backup_root / stamp
    if final_dir.exists():
        raise RuntimeError(f"backup directory already exists: {final_dir}")
    working_dir = backup_root / f".{stamp}.tmp-{os.getpid()}"
    working_dir.mkdir()

    try:
        records = [
            backup_database(label, path, working_dir)
            for label, path in databases.items()
        ]
        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "host": socket.gethostname(),
            "databases": records,
        }
        (working_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        working_dir.rename(final_dir)
    except Exception:
        shutil.rmtree(working_dir, ignore_errors=True)
        raise

    removed = prune_old_backups(
        backup_root, args.retention_days, keep=final_dir
    )
    print(f"Backup created: {final_dir}")
    for record in records:
        print(
            f"{record['label']}: quick_check=ok "
            f"foreign_key_violations=0 sha256={record['sha256']}"
        )
    print(f"Old backup directories removed: {removed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
