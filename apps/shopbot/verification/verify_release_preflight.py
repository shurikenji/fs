"""Ensure deployment preflight rejects wrong or unmigrated databases."""
import sqlite3
import sys
import types
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.modules.setdefault("cairosvg", types.ModuleType("cairosvg"))
from db.financial_migration import VERSION, migrate
from db.models import _CREATE_TABLES
from scripts.preflight_release import check_combined_bind, check_database


class PreflightTests(unittest.TestCase):
    def test_combined_requires_loopback_admin_on_8092(self):
        check_combined_bind("combined", "127.0.0.1", 8092)
        check_combined_bind("shopbot", "0.0.0.0", 8080)
        for host, port in (("0.0.0.0", 8092), ("127.0.0.1", 8080)):
            with self.subTest(host=host, port=port), self.assertRaises(ValueError):
                check_combined_bind("combined", host, port)

    def test_requires_absolute_shared_file_and_explicit_migration(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "shared"
            root.mkdir()
            inside = root / "shopbot.db"
            outside = Path(directory) / "outside.db"
            with closing(sqlite3.connect(inside)) as db, db:
                db.execute("CREATE TABLE something (id INTEGER)")
            with closing(sqlite3.connect(outside)) as db, db:
                db.execute("CREATE TABLE something (id INTEGER)")
            with self.assertRaisesRegex(ValueError, "absolute"):
                check_database("relative.db", str(root))
            with self.assertRaises(ValueError):
                check_database(str(outside), str(root))
            with self.assertRaisesRegex(ValueError, "migration"):
                check_database(str(inside), str(root))
            with closing(sqlite3.connect(inside)) as db, db:
                db.execute("CREATE TABLE shopbot_schema_migrations (version TEXT)")
                db.execute("INSERT INTO shopbot_schema_migrations VALUES (?)", (VERSION,))
            with self.assertRaisesRegex(ValueError, "incomplete"):
                check_database(str(inside), str(root))
            with closing(sqlite3.connect(inside)) as db:
                db.execute("DROP TABLE shopbot_schema_migrations")
                db.executescript(_CREATE_TABLES)
                migrate(db)
            before = inside.read_bytes()
            check_database(str(inside), str(root))
            self.assertEqual(inside.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
