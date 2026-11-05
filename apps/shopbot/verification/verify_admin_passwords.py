"""Verify legacy admin passwords upgrade and stored hashes cannot be used as passwords."""
import hashlib
import re
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from admin.app import create_admin_app
from admin.passwords import hash_password, verify_password
from admin.routers import auth
from bot.config import settings
from db.bootstrap import init_db
from db.database import close_db
from db.queries.settings import get_setting, set_setting


class PasswordTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.original = settings.db_path
        await close_db()
        object.__setattr__(settings, "db_path", str(Path(self.temp.name) / "password.sqlite"))
        await init_db()
        auth._login_attempts.clear()

    async def asyncTearDown(self):
        auth._login_attempts.clear()
        await close_db()
        object.__setattr__(settings, "db_path", self.original)
        self.temp.cleanup()

    async def test_legacy_hash_cannot_be_used_as_password_and_upgrades(self):
        password = "test-password-long"
        legacy = hashlib.sha256(password.encode()).hexdigest()
        await set_setting("admin_password", legacy)
        app = create_admin_app()
        with TestClient(app, base_url="https://testserver") as client:
            login_page = client.get(settings.admin_login_path)
            token = re.search(r'name="csrf_token" value="([^"]+)"', login_page.text).group(1)
            self.assertEqual(client.post(settings.admin_login_path, data={"password": password}, follow_redirects=False).status_code, 403)
            failed = client.post(settings.admin_login_path, data={"password": legacy, "csrf_token": token}, follow_redirects=False)
            self.assertEqual(failed.status_code, 200)
            self.assertNotIn("admin", client.cookies)
            success = client.post(settings.admin_login_path, data={"password": password, "csrf_token": token}, follow_redirects=False)
            self.assertEqual(success.status_code, 303)
            stored = await get_setting("admin_password")
            self.assertTrue(stored.startswith("pbkdf2_sha256$"))
            self.assertTrue(verify_password(password, stored)[0])
            page = client.get("/settings")
            self.assertEqual(page.status_code, 200)
            self.assertNotIn(stored, page.text)
            token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
            self.assertEqual(client.post("/settings/save", data={"admin_password": ""}, follow_redirects=False).status_code, 403)
            self.assertEqual(client.post("/settings/save", data={"admin_password": "", "csrf_token": token}, follow_redirects=False).status_code, 303)
            self.assertEqual(await get_setting("admin_password"), stored)
            self.assertEqual(client.post("/settings/save", data={"admin_password": "short", "csrf_token": token}, follow_redirects=False).status_code, 400)
            self.assertEqual(await get_setting("admin_password"), stored)
            self.assertEqual(client.post("/settings/save", data={"admin_password": "replacement password", "csrf_token": token}, follow_redirects=False).status_code, 303)
            replacement = await get_setting("admin_password")
            self.assertNotEqual(replacement, "replacement password")
            self.assertTrue(verify_password("replacement password", replacement)[0])

    async def test_plaintext_legacy_upgrades_and_default_is_rejected(self):
        self.assertFalse(verify_password("admin123", "admin123")[0])
        self.assertFalse(verify_password("admin123", hashlib.sha256(b"admin123").hexdigest())[0])
        await set_setting("admin_password", "legacy secret")
        with TestClient(create_admin_app(), base_url="https://testserver") as client:
            page = client.get(settings.admin_login_path)
            token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
            self.assertEqual(client.post(settings.admin_login_path, data={"password": "legacy secret", "csrf_token": token}, follow_redirects=False).status_code, 303)
        self.assertTrue((await get_setting("admin_password")).startswith("pbkdf2_sha256$"))

    def test_hashes_are_salted_and_malformed_values_fail(self):
        first, second = hash_password("test-password-long"), hash_password("test-password-long")
        self.assertNotEqual(first, second)
        self.assertFalse(verify_password(first, first)[0])
        self.assertFalse(verify_password("test", "pbkdf2_sha256$999999999$00$00")[0])


if __name__ == "__main__":
    unittest.main()
