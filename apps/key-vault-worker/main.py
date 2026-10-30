"""Isolated, encrypted upstream key-inventory worker.

Run behind internal HTTPS on the ARM control-plane VPS. It never shares SQLite
files with Shopbot and only exposes sanitized lookup fields to that consumer.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite
import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import FastAPI, HTTPException, Request

logger = logging.getLogger("key_vault_worker")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())

DB_PATH = Path(os.getenv("KEY_VAULT_DB_PATH", "data/key_vault.db"))
CONTROL_PLANE_URL = os.getenv("CONTROL_PLANE_URL", "").rstrip("/")
CONTROL_PLANE_TOKEN = os.getenv("CONTROL_PLANE_TOKEN", "")
API_TOKEN = os.getenv("KEY_VAULT_API_TOKEN", "")
LOOKUP_SECRET = os.getenv("KEY_VAULT_LOOKUP_SECRET", "")
POLL_SECONDS = max(60, int(os.getenv("KEY_VAULT_POLL_SECONDS", "600")))
SNAPSHOT_RETENTION_DAYS = max(1, int(os.getenv("KEY_VAULT_SNAPSHOT_RETENTION_DAYS", "7")))
MISSING_RETENTION_DAYS = max(1, int(os.getenv("KEY_VAULT_MISSING_RETENTION_DAYS", "90")))
SENSITIVE_FIELDS = {"key", "api_key", "apikey", "token", "access_token", "secret", "secret_key"}


def _master_key() -> bytes:
    raw = os.getenv("KEY_VAULT_MASTER_KEY", "")
    try:
        value = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except Exception as exc:
        raise RuntimeError("KEY_VAULT_MASTER_KEY must be base64 encoded") from exc
    if len(value) != 32:
        raise RuntimeError("KEY_VAULT_MASTER_KEY must decode to exactly 32 bytes")
    return value


AES = AESGCM(_master_key())


def _fingerprint(value: str) -> str:
    normalized = value.strip()
    if normalized and not normalized.startswith("sk-"):
        normalized = f"sk-{normalized}"
    return hmac.new(LOOKUP_SECRET.encode(), normalized.encode(), hashlib.sha256).hexdigest()


def _mask(value: str) -> str:
    return value[:6] + "..." + value[-4:] if len(value) > 12 else "***"


def _encrypt(value: Any) -> tuple[bytes, bytes]:
    nonce = os.urandom(12)
    return nonce, AES.encrypt(nonce, json.dumps(value, ensure_ascii=True).encode(), None)


def _clean_raw(value: Any) -> Any:
    if isinstance(value, list):
        return [_clean_raw(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {
        key: _clean_raw(item)
        for key, item in value.items()
        if str(key).lower() not in SENSITIVE_FIELDS
    }


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _token_item(raw: dict[str, Any], source_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    raw_key = str(raw.get("key") or "").strip()
    full_key = raw_key if raw_key and "*" not in raw_key and "..." not in raw_key else ""
    if full_key and not full_key.startswith("sk-"):
        full_key = f"sk-{full_key}"
    token_id = str(raw.get("id") or raw.get("token_id") or raw.get("tokenId") or "").strip()
    token_name = str(raw.get("name") or raw.get("token_name") or "").strip()
    fingerprint = _fingerprint(full_key) if full_key else ""
    token_ref = token_id or ("key:" + fingerprint[:24] if fingerprint else "masked:" + hashlib.sha256((raw_key + token_name).encode()).hexdigest()[:24])
    remain = _int(raw.get("remain_quota", raw.get("remainQuota")))
    used = _int(raw.get("used_quota", raw.get("usedQuota")))
    total = _int(raw.get("total_quota", raw.get("totalQuota")), remain + used)
    row = {
        "source_id": source_id,
        "token_ref": token_ref,
        "token_id": token_id or None,
        "token_name": token_name or None,
        "key_fingerprint": fingerprint or None,
        "key_masked": _mask(full_key) if full_key else (raw_key or None),
        "recoverable": 1 if full_key else 0,
        "status": _int(raw.get("status"), 1),
        "remain_quota": remain,
        "used_quota": used,
        "total_quota": total,
        "group_name": str(raw.get("group") or raw.get("group_name") or "").strip() or None,
        "raw_json": json.dumps(_clean_raw(raw), ensure_ascii=True, default=str),
    }
    snapshot_item = {**row, "key": full_key or None}
    return row, snapshot_item


async def _db() -> aiosqlite.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(str(DB_PATH))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    return db


async def init_db() -> None:
    db = await _db()
    try:
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS key_vault_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT NOT NULL,
                status TEXT NOT NULL,
                item_count INTEGER NOT NULL DEFAULT 0,
                error_message TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS key_vault_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT NOT NULL,
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL,
                item_count INTEGER NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS key_vault_items (
                source_id TEXT NOT NULL,
                token_ref TEXT NOT NULL,
                token_id TEXT,
                token_name TEXT,
                key_fingerprint TEXT,
                key_nonce BLOB,
                key_ciphertext BLOB,
                key_masked TEXT,
                recoverable INTEGER NOT NULL DEFAULT 0,
                status INTEGER NOT NULL DEFAULT 1,
                remain_quota INTEGER NOT NULL DEFAULT 0,
                used_quota INTEGER NOT NULL DEFAULT 0,
                total_quota INTEGER NOT NULL DEFAULT 0,
                group_name TEXT,
                raw_json TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                missing_since TEXT,
                last_seen_at TEXT DEFAULT (datetime('now')),
                PRIMARY KEY(source_id, token_ref)
            );
            CREATE INDEX IF NOT EXISTS idx_key_vault_fingerprint ON key_vault_items(source_id, key_fingerprint, active);
            CREATE INDEX IF NOT EXISTS idx_key_vault_token_id ON key_vault_items(source_id, token_id, active);
            """
        )
        await db.commit()
    finally:
        await db.close()


def _headers(source: dict[str, Any]) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    user_value = str(source.get("auth_user_value") or "").strip()
    user_header = str(source.get("auth_user_header") or "").strip()
    if user_value:
        headers[user_header or ("Rix-Api-User" if source.get("source_type") == "rixapi" else "New-Api-User")] = user_value
    token = str(source.get("auth_token") or "").strip()
    if token:
        headers["Authorization"] = token if token.lower().startswith("bearer ") else f"Bearer {token}"
    cookie = str(source.get("auth_cookie") or "").strip()
    if cookie:
        headers["Cookie"] = cookie
    return headers


async def _fetch_tokens(source: dict[str, Any]) -> list[dict[str, Any]]:
    base_url = str(source.get("upstream_base_url") or "").rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        raise ValueError("invalid upstream_base_url")
    all_items: list[dict[str, Any]] = []
    page, total = 1, None
    async with httpx.AsyncClient(timeout=30.0) as client:
        while page <= 10_000:
            response = await client.get(f"{base_url}/api/token/", params={"p": page, "page_size": 100}, headers=_headers(source))
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("success") is False:
                raise ValueError("upstream token list returned an invalid payload")
            data = payload.get("data")
            if not isinstance(data, dict) or not isinstance(data.get("items"), list):
                raise ValueError("upstream token list has no data.items array")
            items = [item for item in data["items"] if isinstance(item, dict)]
            all_items.extend(items)
            total = _int(data.get("total"), len(all_items)) if total is None else total
            if not items or len(all_items) >= total:
                return all_items
            page += 1
    raise ValueError("upstream token pagination exceeded the safety limit")


async def _record_success(source: dict[str, Any], raw_items: list[dict[str, Any]]) -> None:
    source_id = str(source["id"])
    rows, snapshot = zip(*(_token_item(item, source_id) for item in raw_items)) if raw_items else ([], [])
    snapshot_nonce, snapshot_ciphertext = _encrypt(list(snapshot))
    db = await _db()
    try:
        await db.execute("BEGIN")
        await db.execute("UPDATE key_vault_items SET active = 0 WHERE source_id = ?", (source_id,))
        for row in rows:
            key_nonce = key_ciphertext = None
            if row["recoverable"]:
                raw_key = next(item["key"] for item in snapshot if item["token_ref"] == row["token_ref"])
                key_nonce, key_ciphertext = _encrypt(raw_key)
            await db.execute(
                """
                INSERT INTO key_vault_items (
                    source_id, token_ref, token_id, token_name, key_fingerprint, key_nonce, key_ciphertext,
                    key_masked, recoverable, status, remain_quota, used_quota, total_quota, group_name,
                    raw_json, active, missing_since, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, NULL, datetime('now'))
                ON CONFLICT(source_id, token_ref) DO UPDATE SET
                    token_id=excluded.token_id, token_name=excluded.token_name,
                    key_fingerprint=excluded.key_fingerprint, key_nonce=excluded.key_nonce,
                    key_ciphertext=excluded.key_ciphertext, key_masked=excluded.key_masked,
                    recoverable=excluded.recoverable, status=excluded.status,
                    remain_quota=excluded.remain_quota, used_quota=excluded.used_quota,
                    total_quota=excluded.total_quota, group_name=excluded.group_name,
                    raw_json=excluded.raw_json, active=1, missing_since=NULL,
                    last_seen_at=datetime('now')
                """,
                (
                    row["source_id"], row["token_ref"], row["token_id"], row["token_name"],
                    row["key_fingerprint"], key_nonce, key_ciphertext, row["key_masked"], row["recoverable"],
                    row["status"], row["remain_quota"], row["used_quota"], row["total_quota"],
                    row["group_name"], row["raw_json"],
                ),
            )
        await db.execute(
            "UPDATE key_vault_items SET missing_since = COALESCE(missing_since, datetime('now')) WHERE source_id = ? AND active = 0",
            (source_id,),
        )
        await db.execute(
            "INSERT INTO key_vault_snapshots (source_id, nonce, ciphertext, item_count) VALUES (?, ?, ?, ?)",
            (source_id, snapshot_nonce, snapshot_ciphertext, len(rows)),
        )
        await db.execute("INSERT INTO key_vault_runs (source_id, status, item_count) VALUES (?, 'success', ?)", (source_id, len(rows)))
        await db.execute("DELETE FROM key_vault_snapshots WHERE created_at < datetime('now', ?)", (f"-{SNAPSHOT_RETENTION_DAYS} days",))
        await db.execute("DELETE FROM key_vault_items WHERE active = 0 AND missing_since < datetime('now', ?)", (f"-{MISSING_RETENTION_DAYS} days",))
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


async def _record_failure(source_id: str, exc: Exception) -> None:
    db = await _db()
    try:
        await db.execute(
            "INSERT INTO key_vault_runs (source_id, status, error_message) VALUES (?, 'error', ?)",
            (source_id, str(exc)[:1000]),
        )
        await db.commit()
    finally:
        await db.close()


async def _sources() -> list[dict[str, Any]]:
    if not CONTROL_PLANE_URL or not CONTROL_PLANE_TOKEN:
        raise RuntimeError("CONTROL_PLANE_URL and CONTROL_PLANE_TOKEN are required")
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            f"{CONTROL_PLANE_URL}/api/internal/config/key-vault",
            headers={"X-Control-Plane-Token": CONTROL_PLANE_TOKEN},
        )
        response.raise_for_status()
    payload = response.json()
    sources = payload.get("sources") if isinstance(payload, dict) else None
    if not isinstance(sources, list):
        raise ValueError("control plane did not return a sources array")
    return [source for source in sources if isinstance(source, dict) and source.get("id")]


async def poll_once() -> None:
    for source in await _sources():
        source_id = str(source["id"])
        try:
            await _record_success(source, await _fetch_tokens(source))
        except Exception as exc:
            logger.warning("key-vault poll failed for %s: %s", source_id, exc)
            await _record_failure(source_id, exc)


async def _poll_loop() -> None:
    while True:
        try:
            await poll_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("key-vault control-plane poll failed")
        await asyncio.sleep(POLL_SECONDS)


def _authorize(request: Request) -> None:
    candidate = request.headers.get("authorization", "").removeprefix("Bearer ")
    if not API_TOKEN or not secrets.compare_digest(candidate, API_TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized")


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not API_TOKEN or not LOOKUP_SECRET:
        raise RuntimeError("KEY_VAULT_API_TOKEN and KEY_VAULT_LOOKUP_SECRET are required")
    await init_db()
    task = asyncio.create_task(_poll_loop())
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


app = FastAPI(title="Key Vault Worker", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy"}


@app.post("/internal/key-vault/lookup")
async def lookup(request: Request) -> dict[str, Any]:
    _authorize(request)
    payload = await request.json()
    source_id = str(payload.get("source_id") or "").strip()
    fingerprint = str(payload.get("key_fingerprint") or "").strip()
    token_id = str(payload.get("token_id") or "").strip()
    token_name = str(payload.get("token_name") or "").strip()
    if not source_id or not any((fingerprint, token_id, token_name)):
        raise HTTPException(status_code=422, detail="source_id and one key selector are required")
    db = await _db()
    try:
        row = None
        if fingerprint:
            cursor = await db.execute("SELECT * FROM key_vault_items WHERE source_id = ? AND key_fingerprint = ? AND active = 1 LIMIT 1", (source_id, fingerprint))
            row = await cursor.fetchone()
        if row is None and token_id:
            cursor = await db.execute("SELECT * FROM key_vault_items WHERE source_id = ? AND token_id = ? AND active = 1 LIMIT 1", (source_id, token_id))
            row = await cursor.fetchone()
        if row is None and token_name:
            cursor = await db.execute("SELECT * FROM key_vault_items WHERE source_id = ? AND token_name = ? AND active = 1 LIMIT 1", (source_id, token_name))
            row = await cursor.fetchone()
        if row is None:
            return {"item": None}
        item = dict(row)
        return {"item": {key: item.get(key) for key in ("token_id", "token_name", "key_masked", "status", "remain_quota", "used_quota", "total_quota", "group_name", "recoverable", "last_seen_at")}}
    finally:
        await db.close()
