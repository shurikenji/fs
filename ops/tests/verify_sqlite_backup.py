"""Verify the production SQLite backup script against isolated databases."""

from __future__ import annotations

import gzip
import json
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "backup-sqlite-databases.py"


def create_database(path: Path, value: str) -> None:
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE parent (id INTEGER PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE child (
                id INTEGER PRIMARY KEY,
                parent_id INTEGER NOT NULL REFERENCES parent(id)
            );
            """
        )
        db.execute("INSERT INTO parent(value) VALUES (?)", (value,))
        db.execute("INSERT INTO child(parent_id) VALUES (1)")


def main() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        first = root / "first.db"
        second = root / "second.db"
        backups = root / "backups"
        old_backup = backups / "20000101T000000Z"
        old_backup.mkdir(parents=True)
        create_database(first, "first")
        create_database(second, "second")

        subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--backup-root",
                str(backups),
                "--retention-days",
                "14",
                "--db",
                f"first={first}",
                "--db",
                f"second={second}",
            ],
            check=True,
        )

        runs = [path for path in backups.iterdir() if path.is_dir()]
        assert len(runs) == 1, runs
        assert not old_backup.exists()
        manifest = json.loads((runs[0] / "manifest.json").read_text("utf-8"))
        assert {item["label"] for item in manifest["databases"]} == {
            "first",
            "second",
        }

        restored = root / "restored.db"
        with gzip.open(runs[0] / "first.db.gz", "rb") as source:
            restored.write_bytes(source.read())
        with closing(sqlite3.connect(restored)) as db:
            assert db.execute("PRAGMA quick_check").fetchone() == ("ok",)
            assert db.execute("PRAGMA foreign_key_check").fetchone() is None
            assert db.execute("SELECT value FROM parent").fetchone() == ("first",)

    print("SQLite backup verification passed")


if __name__ == "__main__":
    main()
