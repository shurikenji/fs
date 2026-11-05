"""Verify transactional migration and legacy compatibility on isolated SQLite."""
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from db.financial_migration import VERSION, migrate


class FinancialMigrationTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript("""
            CREATE TABLE users (id INTEGER PRIMARY KEY);
            CREATE TABLE orders (id INTEGER PRIMARY KEY);
            CREATE TABLE wallet_transactions (id INTEGER PRIMARY KEY, amount INTEGER);
            INSERT INTO wallet_transactions VALUES (1, 100), (2, -20);
        """)

    def tearDown(self):
        self.db.close()

    def test_migration_is_idempotent_and_keeps_legacy_rows(self):
        self.assertTrue(migrate(self.db))
        self.assertFalse(migrate(self.db))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM wallet_transactions WHERE operation_key IS NULL").fetchone()[0], 2)
        self.assertEqual(self.db.execute("SELECT version FROM shopbot_schema_migrations").fetchone()[0], VERSION)
        self.db.execute("UPDATE wallet_transactions SET operation_key = 'same' WHERE id = 1")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE wallet_transactions SET operation_key = 'same' WHERE id = 2")

    def test_incompatible_existing_table_rolls_back_everything(self):
        self.db.execute("CREATE TABLE payment_receipts (incompatible INTEGER)")
        self.db.commit()
        with self.assertRaises(sqlite3.OperationalError):
            migrate(self.db)
        columns = [row[1] for row in self.db.execute("PRAGMA table_info(wallet_transactions)")]
        self.assertNotIn("operation_key", columns)
        self.assertIsNone(self.db.execute("SELECT name FROM sqlite_master WHERE name = 'shopbot_schema_migrations'").fetchone())

    def test_migration_refuses_caller_transaction(self):
        self.db.execute("INSERT INTO users VALUES (1)")
        with self.assertRaises(RuntimeError):
            migrate(self.db)
        self.db.rollback()
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
