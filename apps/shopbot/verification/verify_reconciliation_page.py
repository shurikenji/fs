"""Verify the reconciliation page is protected and does not expose receipt details."""
import sqlite3
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from admin.app import create_admin_app
from admin.deps import require_admin
from bot.config import settings
from db.bootstrap import init_db
from db.database import close_db
from db.financial_migration import migrate
from db.queries.payment_receipts import record_receipt


class ReconciliationPageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.original = settings.db_path
        await close_db()
        object.__setattr__(settings, "db_path", str(Path(self.temp.name) / "test.sqlite"))
        await init_db()
        connection = sqlite3.connect(settings.db_path)
        try:
            migrate(connection)
        finally:
            connection.close()

    async def asyncTearDown(self):
        await close_db()
        object.__setattr__(settings, "db_path", self.original)
        self.temp.cleanup()

    async def test_page_requires_admin_and_escapes_untrusted_data(self):
        await record_receipt(provider="MB", account_identity="private-account", transaction_id="<script>bad</script>",
                             amount=100, description="private-bank-memo")
        app = create_admin_app()
        with TestClient(app) as client:
            self.assertEqual(client.get("/orders/reconciliation", follow_redirects=False).status_code, 303)
            app.dependency_overrides[require_admin] = lambda: {"admin": True}
            response = client.get("/orders/reconciliation")
        self.assertEqual(response.status_code, 200)
        self.assertIn("&lt;script&gt;bad&lt;/script&gt;", response.text)
        self.assertNotIn("<script>bad</script>", response.text)
        self.assertNotIn("private-account", response.text)
        self.assertNotIn("private-bank-memo", response.text)


if __name__ == "__main__":
    unittest.main()
