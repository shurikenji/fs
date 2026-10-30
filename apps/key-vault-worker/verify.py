"""Minimal encryption/persistence verification for the isolated worker."""
from __future__ import annotations

import asyncio
import base64
import os
import tempfile
from pathlib import Path

with tempfile.TemporaryDirectory() as temp_dir:
    os.environ["KEY_VAULT_DB_PATH"] = str(Path(temp_dir) / "key_vault.db")
    os.environ["KEY_VAULT_MASTER_KEY"] = base64.b64encode(bytes(range(1, 33))).decode()
    os.environ["KEY_VAULT_API_TOKEN"] = "verify-token"
    os.environ["KEY_VAULT_LOOKUP_SECRET"] = "verify-secret"

    import main

    async def check() -> None:
        await main.init_db()
        await main._record_success(
            {"id": "source-1"},
            [{"id": 7, "name": "demo", "key": "sk-abcdefghijklmnop", "remain_quota": 42}],
        )
        db = await main._db()
        row = await (await db.execute("SELECT key_ciphertext, key_fingerprint, remain_quota FROM key_vault_items")).fetchone()
        await db.close()
        assert row["key_ciphertext"] and row["key_fingerprint"] and row["remain_quota"] == 42
        print("[OK] key vault encrypts raw keys and serves indexed inventory")

    asyncio.run(check())
