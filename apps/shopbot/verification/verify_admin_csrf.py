"""Exercise admin CSRF checks and read-only GET semantics."""
import re
import sys
import time
import unittest
from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from itsdangerous import URLSafeTimedSerializer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from admin.app import create_admin_app
from bot.config import settings
from db.bootstrap import init_db
from db.database import close_db
from db.queries.settings import set_setting


class _FormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.current = {"method": attrs.get("method", "get").lower(), "csrf": False}
            self.forms.append(self.current)
        elif tag == "input" and self.current is not None and attrs.get("name") == "csrf_token":
            self.current["csrf"] = bool(attrs.get("value"))

    def handle_endtag(self, tag):
        if tag == "form":
            self.current = None


class AdminCsrfTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.original = settings.db_path
        await close_db()
        object.__setattr__(settings, "db_path", str(Path(self.temp.name) / "csrf.sqlite"))
        await init_db()
        await set_setting("admin_password", "a legacy test password")

    async def asyncTearDown(self):
        await close_db()
        object.__setattr__(settings, "db_path", self.original)
        self.temp.cleanup()

    async def test_csrf_and_get_mutation_guards(self):
        with TestClient(create_admin_app(), base_url="https://testserver") as client:
            page = client.get(settings.admin_login_path)
            self.assertIn("secure", page.headers["set-cookie"].lower())
            token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
            self.assertEqual(client.post(settings.admin_login_path, data={"password": "a legacy test password", "csrf_token": token}, follow_redirects=False).status_code, 303)
            page = client.get("/orders")
            self.assertEqual(page.status_code, 200)
            token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
            parser = _FormParser()
            parser.feed(page.text)
            self.assertTrue(all(form["csrf"] for form in parser.forms if form["method"] == "post"))
            self.assertEqual(client.post("/orders/1/refund", follow_redirects=False).status_code, 403)
            self.assertEqual(client.post("/orders/1/refund", headers={"X-CSRF-Token": "wrong"}, follow_redirects=False).status_code, 403)
            self.assertEqual(client.post("/orders/1/refund", headers={"X-CSRF-Token": token}, follow_redirects=False).status_code, 303)
            for url in ("/orders/1/refund", "/orders/1/cancel", "/users/1/toggle-admin", "/servers/1/delete", "/logout"):
                self.assertEqual(client.get(url, follow_redirects=False).status_code, 405)
            self.assertEqual(client.post("/logout", data={"csrf_token": token}, follow_redirects=False).status_code, 303)

    async def test_signed_launch_establishes_https_session(self):
        original = settings.admin_launch_secret
        object.__setattr__(settings, "admin_launch_secret", "test-launch-secret")
        try:
            token = URLSafeTimedSerializer("test-launch-secret", salt="shopbot-admin-launch").dumps({
                "issuer": settings.platform_admin_url, "sub": "admin", "nonce": "test-nonce",
                "expires_at": int(time.time()) + 60,
            })
            with TestClient(create_admin_app(), base_url="https://testserver") as client:
                self.assertEqual(client.post("/sso/consume", data={"token": "bad"}).status_code, 401)
                response = client.post("/sso/consume", data={"token": token}, follow_redirects=False)
                self.assertEqual(response.status_code, 303)
                self.assertIn("secure", response.headers["set-cookie"].lower())
                self.assertEqual(client.get("/orders").status_code, 200)
        finally:
            object.__setattr__(settings, "admin_launch_secret", original)


if __name__ == "__main__":
    unittest.main()
