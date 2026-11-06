"""Exercise masked keys and incomplete upstream pagination without real credentials."""
import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from cryptography.exceptions import InvalidTag

os.environ["KEY_VAULT_MASTER_KEY"] = base64.urlsafe_b64encode(bytes(range(32))).decode()
os.environ["KEY_VAULT_LOOKUP_SECRET"] = "test-only-lookup-secret-32-characters"
import main
from scripts.initialize_vault import initialize


class VaultSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        main.DB_PATH = Path(self.temp.name) / "vault.sqlite"
        main.DB_PATH.touch(mode=0o600, exist_ok=False)
        await main.init_db()

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def test_unicode_mask_does_not_count_as_recoverable(self):
        await main._record_success({"id": "one"}, [{"id": 7, "key": "sk-example\u20261234"}])
        db = await main._db()
        try:
            row = await (await db.execute("SELECT recoverable, key_ciphertext FROM key_vault_items")).fetchone()
        finally:
            await db.close()
        self.assertEqual(tuple(row), (0, None))

    async def test_summary_is_authorized_and_contains_no_key_material(self):
        secret = "sk-secret-abcdefghijklmnop"
        await main._record_success({"id": "one"}, [{"id": 7, "name": "private-name", "key": secret}])
        await main._record_failure("one", RuntimeError("private-error"))
        db = await main._db()
        await db.execute("UPDATE key_vault_runs SET error_message = 'private-error' WHERE status = 'error'")
        await db.commit()
        await db.close()
        with patch.object(main, "API_TOKEN", "test-token"):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
                self.assertEqual((await client.get("/internal/key-vault/summary")).status_code, 401)
                response = await client.get("/internal/key-vault/summary", headers={"Authorization": "Bearer test-token"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sources"][0]["last_status"], "error")
        self.assertEqual(response.json()["sources"][0]["stored_key_count"], 1)
        for private in (secret, "private-name", "private-error"):
            self.assertNotIn(private, response.text)

    async def test_masked_key_preserves_ciphertext_only_for_same_source_and_id(self):
        await main._record_success({"id": "one"}, [{"id": 7, "name": "test", "key": "sk-abcdefghijklmnop"}])
        await main._record_success({"id": "one"}, [{"id": 7, "name": "test", "key": "sk-***"}])
        await main._record_success({"id": "two"}, [{"id": 7, "name": "test", "key": "sk-***"}])
        db = await main._db()
        try:
            rows = await (await db.execute("SELECT source_id, key_nonce, key_ciphertext, recoverable FROM key_vault_items ORDER BY source_id")).fetchall()
            latest = await (await db.execute("SELECT nonce, ciphertext FROM key_vault_snapshots WHERE source_id = 'one' ORDER BY id DESC LIMIT 1")).fetchone()
        finally:
            await db.close()
        self.assertEqual(rows[0]["recoverable"], 1)
        self.assertEqual(json.loads(main.AES.decrypt(rows[0]["key_nonce"], rows[0]["key_ciphertext"], None)), "sk-abcdefghijklmnop")
        self.assertEqual(rows[1]["recoverable"], 0)
        self.assertIsNone(rows[1]["key_ciphertext"])
        saved = json.loads(main.AES.decrypt(latest["nonce"], latest["ciphertext"], None))
        self.assertEqual(saved[0]["key"], "sk-abcdefghijklmnop")
        self.assertEqual(saved[0]["key_origin"], "previous_observation")

    async def test_pagination_rejects_missing_changed_duplicate_and_truncated_data(self):
        source = {"id": "one", "upstream_base_url": "https://example.test"}
        cases = [
            [{"items": [{"id": 1}]}],
            [{"total": 2, "items": [{"id": 1}]}, {"total": 3, "items": [{"id": 2}]}],
            [{"total": 2, "items": [{"id": 1}]}, {"total": 2, "items": [{"id": 1}]}],
            [{"total": 2, "items": [{"id": 1}]}, {"total": 2, "items": []}],
        ]
        client_class = httpx.AsyncClient
        for pages in cases:
            def handler(request):
                page = int(request.url.params["p"])
                return httpx.Response(200, json={"success": True, "data": pages[page - 1]})
            transport = httpx.MockTransport(handler)
            with self.subTest(pages=pages), patch.object(main.httpx, "AsyncClient", side_effect=lambda **kw: client_class(transport=transport, **kw)):
                with self.assertRaises(ValueError):
                    await main._fetch_tokens(source)
        def handler(request):
            page = int(request.url.params["p"])
            return httpx.Response(200, json={"success": True, "data": {"total": 2, "items": [{"id": page}]}})
        transport = httpx.MockTransport(handler)
        with patch.object(main.httpx, "AsyncClient", side_effect=lambda **kw: client_class(transport=transport, **kw)):
            self.assertEqual(len(await main._fetch_tokens(source)), 2)

    async def test_masked_token_is_resolved_by_id_when_enabled(self):
        def handler(request):
            if request.method == "POST":
                self.assertEqual(request.url.path, "/api/token/7/key")
                return httpx.Response(200, json={"success": True, "data": {"key": "secret-value"}})
            return httpx.Response(200, json={"success": True, "data": {"total": 1, "items": [{"id": 7, "key": "sk-***"}]}})

        transport = httpx.MockTransport(handler)
        client_class = httpx.AsyncClient
        source = {
            "id": "one",
            "upstream_base_url": "https://example.test",
            "supports_key_lookup_by_id": 1,
            "token_key_endpoint_template": "/api/token/{id}/key",
        }
        with patch.object(main.httpx, "AsyncClient", side_effect=lambda **kw: client_class(transport=transport, **kw)):
            items = await main._fetch_tokens(source)
        self.assertEqual(items[0]["key"], "sk-secret-value")

    async def test_error_storage_and_urls_do_not_expose_credentials(self):
        secret = "sensitive-test-credential"
        await main._record_failure("one", RuntimeError(secret))
        db = await main._db()
        try:
            row = await (await db.execute("SELECT error_message FROM key_vault_runs")).fetchone()
        finally:
            await db.close()
        self.assertEqual(row["error_message"], "RuntimeError")
        for url in (f"https://user:{secret}@example.test", f"https://example.test/?token={secret}"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                await main._fetch_tokens({"id": "one", "upstream_base_url": url})

    async def test_masked_update_rolls_back_if_previous_ciphertext_is_unreadable(self):
        await main._record_success({"id": "one"}, [{"id": 7, "key": "sk-abcdefghijklmnop"}])
        db = await main._db()
        await db.execute("UPDATE key_vault_items SET key_ciphertext = ?", (b"corrupt",))
        await db.commit()
        await db.close()
        with self.assertRaises(InvalidTag):
            await main._record_success({"id": "one"}, [{"id": 7, "key": "sk-***"}])
        db = await main._db()
        try:
            item = await (await db.execute("SELECT key_ciphertext, active, recoverable FROM key_vault_items")).fetchone()
            count = (await (await db.execute("SELECT COUNT(*) FROM key_vault_snapshots")).fetchone())[0]
        finally:
            await db.close()
        self.assertEqual(tuple(item), (b"corrupt", 1, 1))
        self.assertEqual(count, 1)

    async def test_empty_feed_does_not_deactivate_existing_inventory(self):
        await main._record_success({"id": "one"}, [{"id": 7, "key": "sk-abcdefghijklmnop"}])
        with self.assertRaisesRegex(ValueError, "manual review"):
            await main._record_success({"id": "one"}, [])
        db = await main._db()
        try:
            item = await (await db.execute("SELECT active, recoverable FROM key_vault_items")).fetchone()
        finally:
            await db.close()
        self.assertEqual(tuple(item), (1, 1))


class VaultInitializationTests(unittest.IsolatedAsyncioTestCase):
    def test_runtime_rejects_weak_or_missing_service_configuration(self):
        valid = {
            "API_TOKEN": "a" * 32,
            "LOOKUP_SECRET": "b" * 32,
            "CONTROL_PLANE_TOKEN": "c" * 32,
            "CONTROL_PLANE_URL": "http://127.0.0.1:8090",
            "DB_PATH": Path(tempfile.gettempdir()) / "vault-test.sqlite",
        }
        with patch.multiple(main, **valid):
            main.validate_runtime_settings()
            for field, value in (("API_TOKEN", "change-me"), ("LOOKUP_SECRET", "short"),
                                 ("CONTROL_PLANE_TOKEN", ""), ("CONTROL_PLANE_URL", "https://u:p@example.test"),
                                 ("DB_PATH", Path("relative.sqlite"))):
                with self.subTest(field=field), patch.object(main, field, value), self.assertRaises(RuntimeError):
                    main.validate_runtime_settings()

    def test_master_key_rejects_invalid_base64(self):
        with patch.dict(os.environ, {"KEY_VAULT_MASTER_KEY": base64.b64encode(bytes(range(32))).decode() + "!"}):
            with self.assertRaisesRegex(RuntimeError, "base64 encoded"):
                main._master_key()

    async def test_explicit_create_refuses_missing_implicit_and_existing_database(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "new.sqlite"
            with patch.object(main, "DB_PATH", path):
                with self.assertRaises(FileNotFoundError):
                    await main.require_vault_schema()
                self.assertFalse(path.exists())
                await initialize(directory)
                await main.require_vault_schema()
                before = path.read_bytes()
                await main.require_vault_schema(readonly=True)
                self.assertEqual(path.read_bytes(), before)
                with self.assertRaises(FileExistsError):
                    await initialize(directory)
                self.assertEqual(path.read_bytes(), before)

    async def test_uninitialized_file_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.sqlite"
            path.touch()
            with patch.object(main, "DB_PATH", path), self.assertRaisesRegex(RuntimeError, "explicitly initialized"):
                await main.require_vault_schema()

    async def test_wrong_master_or_lookup_secret_does_not_open_existing_vault(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vault.sqlite"
            with patch.object(main, "DB_PATH", path):
                await initialize(directory)
                for field, wrong in (("MASTER_KEY", bytes(reversed(range(32)))), ("LOOKUP_SECRET", "other-test-secret")):
                    with self.subTest(field=field), patch.object(main, field, wrong):
                        with self.assertRaisesRegex(RuntimeError, "does not match"):
                            await main.require_vault_schema()
                        with self.assertRaisesRegex(RuntimeError, "does not match"):
                            await main.init_db()
                await main.require_vault_schema()

    async def test_existing_vault_without_metadata_is_not_reinitialized(self):
        import sqlite3
        from contextlib import closing
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.sqlite"
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("CREATE TABLE legacy_data (id INTEGER)")
                db.execute("INSERT INTO legacy_data VALUES (1)")
            with patch.object(main, "DB_PATH", path), self.assertRaisesRegex(RuntimeError, "explicit key verification"):
                await main.init_db()
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("SELECT id FROM legacy_data").fetchone()[0], 1)

    async def test_incomplete_schema_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vault.sqlite"
            with patch.object(main, "DB_PATH", path):
                await initialize(directory)
                db = await main._db()
                try:
                    await db.execute("ALTER TABLE key_vault_items RENAME COLUMN key_ciphertext TO missing_ciphertext")
                    await db.commit()
                finally:
                    await db.close()
                with self.assertRaisesRegex(RuntimeError, "schema is incomplete"):
                    await main.require_vault_schema(readonly=True)


if __name__ == "__main__":
    unittest.main()
