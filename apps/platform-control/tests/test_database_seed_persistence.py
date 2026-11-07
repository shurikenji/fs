"""Admin deletions must survive platform-control restarts."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from db.database import close_db, get_db, init_db


class DatabaseSeedPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_deleted_default_rows_are_not_restored_on_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "platform-control.db"
            settings = SimpleNamespace(db_path=str(db_path))

            with patch("db.database.get_settings", return_value=settings):
                await init_db()
                db = await get_db()
                for table, row_id in (
                    ("proxy_endpoints", "gpt1"),
                    ("service_sources", "gpt1"),
                    ("portal_modules", "docs"),
                ):
                    row = await (await db.execute(
                        f"SELECT 1 FROM {table} WHERE id = ?",
                        (row_id,),
                    )).fetchone()
                    self.assertIsNotNone(row, f"{table}.{row_id} was not initially seeded")
                await db.execute("DELETE FROM proxy_endpoints WHERE id = 'gpt1'")
                await db.execute("DELETE FROM service_sources WHERE id = 'gpt1'")
                await db.execute("DELETE FROM portal_modules WHERE id = 'docs'")
                await db.commit()
                await close_db()

                await init_db()
                db = await get_db()
                try:
                    for table, row_id in (
                        ("proxy_endpoints", "gpt1"),
                        ("service_sources", "gpt1"),
                        ("portal_modules", "docs"),
                    ):
                        row = await (await db.execute(
                            f"SELECT 1 FROM {table} WHERE id = ?",
                            (row_id,),
                        )).fetchone()
                        self.assertIsNone(row, f"{table}.{row_id} was restored")
                finally:
                    await close_db()


if __name__ == "__main__":
    unittest.main()
