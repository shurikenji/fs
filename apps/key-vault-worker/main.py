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
from urllib.parse import urljoin, urlsplit

import aiosqlite
import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import FastAPI, HTTPException, Request

logger = logging.getLogger("key_vault_worker")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

DB_PATH = Path(os.getenv("KEY_VAULT_DB_PATH", "data/key_vault.db"))
CONTROL_PLANE_URL = os.getenv("CONTROL_PLANE_URL", "").rstrip("/")
CONTROL_PLANE_TOKEN = os.getenv("CONTROL_PLANE_TOKEN", "")
API_TOKEN = os.getenv("KEY_VAULT_API_TOKEN", "")
LOOKUP_SECRET = os.getenv("KEY_VAULT_LOOKUP_SECRET", "")
POLL_SECONDS = max(60, int(os.getenv("KEY_VAULT_POLL_SECONDS", "600")))
SNAPSHOT_RETENTION_DAYS = max(1, int(os.getenv("KEY_VAULT_SNAPSHOT_RETENTION_DAYS", "7")))
MISSING_RETENTION_DAYS = max(1, int(os.getenv("KEY_VAULT_MISSING_RETENTION_DAYS", "90")))
SENSITIVE_FIELDS = {"key", "api_key", "apikey", "token", "access_token", "secret", "secret_key"}
KEY_FIELDS = ("key", "api_key", "apiKey", "token", "access_token", "accessToken", "secret", "secret_key")


def _master_key() -> bytes:
    raw = os.getenv("KEY_VAULT_MASTER_KEY", "")
    try:
        value = base64.b64decode(raw + "=" * (-len(raw) % 4), altchars=b"-_", validate=True)
    except Exception as exc:
        raise RuntimeError("KEY_VAULT_MASTER_KEY must be base64 encoded") from exc
    if len(value) != 32:
        raise RuntimeError("KEY_VAULT_MASTER_KEY must decode to exactly 32 bytes")
    return value


MASTER_KEY = _master_key()
AES = AESGCM(MASTER_KEY)


def _key_checks() -> dict[str, str]:
    if not LOOKUP_SECRET.strip():
        raise RuntimeError("KEY_VAULT_LOOKUP_SECRET is required")
    return {
        "master_key_check": hmac.new(MASTER_KEY, b"shupremium-vault-master-v1", hashlib.sha256).hexdigest(),
        "lookup_secret_check": hmac.new(LOOKUP_SECRET.encode(), b"shupremium-vault-lookup-v1", hashlib.sha256).hexdigest(),
    }


async def _verify_key_checks(db: aiosqlite.Connection) -> None:
    cursor = await db.execute("SELECT key, value FROM vault_metadata")
    stored = {row[0]: row[1] for row in await cursor.fetchall()}
    for key, expected in _key_checks().items():
        if not isinstance(stored.get(key), str) or not hmac.compare_digest(stored[key], expected):
            raise RuntimeError("Vault key configuration does not match this database")


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


def _extract_full_key(payload: Any) -> str:
    queue = [payload]
    while queue:
        current = queue.pop(0)
        if isinstance(current, dict):
            for field in KEY_FIELDS:
                value = current.get(field)
                if not isinstance(value, str):
                    continue
                key = value.strip()
                if key and not any(mask in key for mask in ("*", "...", "\u2026")):
                    return key if key.startswith("sk-") else f"sk-{key}"
            queue.extend(value for value in current.values() if isinstance(value, (dict, list, tuple)))
        elif isinstance(current, (list, tuple)):
            queue.extend(value for value in current if isinstance(value, (dict, list, tuple)))
    return ""


async def _resolve_token_key(client: httpx.AsyncClient, source: dict[str, Any], token_id: str) -> str:
    if not token_id.isascii() or not token_id.isdecimal() or int(token_id) <= 0:
        raise ValueError("masked token has no usable token ID")
    template = str(source.get("token_key_endpoint_template") or "/api/token/{id}/key").strip()
    endpoint = template.format(id=int(token_id))
    base_url = str(source.get("upstream_base_url") or "").rstrip("/") + "/"
    url = endpoint if endpoint.startswith(("http://", "https://")) else urljoin(base_url, endpoint.lstrip("/"))
    base = urlsplit(base_url)
    target = urlsplit(url)
    if (target.scheme, target.hostname, target.port) != (base.scheme, base.hostname, base.port):
        raise ValueError("token key endpoint must use the upstream origin")
    response = await client.post(url, headers=_headers(source))
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("success") is False:
        raise ValueError("token key endpoint returned an invalid payload")
    full_key = _extract_full_key(payload)
    if not full_key:
        raise ValueError("token key endpoint returned no full key")
    return full_key


def _token_item(raw: dict[str, Any], source_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    raw_key = str(raw.get("key") or "").strip()
    full_key = raw_key if raw_key and not any(mask in raw_key for mask in ("*", "...", "\u2026")) else ""
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


async def _db(*, readonly: bool = False) -> aiosqlite.Connection:
    mode = "ro" if readonly else "rw"
    db = await aiosqlite.connect(DB_PATH.resolve(strict=True).as_uri() + f"?mode={mode}", uri=True)
    try:
        db.row_factory = aiosqlite.Row
        return db
    except BaseException:
        await db.close()
        raise


async def init_db() -> None:
    db = await _db()
    try:
        cursor = await db.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")
        existing = {row[0] for row in await cursor.fetchall()}
        if existing:
            if "vault_metadata" not in existing:
                raise RuntimeError("Existing Vault requires explicit key verification before migration")
            await _verify_key_checks(db)
        await db.execute("PRAGMA journal_mode=WAL")
        await db.executescript(
            """
            BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS vault_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
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
        for key, value in _key_checks().items():
            await db.execute("INSERT OR IGNORE INTO vault_metadata (key, value) VALUES (?, ?)", (key, value))
        await _verify_key_checks(db)
        await db.commit()
    except BaseException:
        await db.rollback()
        raise
    finally:
        await db.close()


async def require_vault_schema(*, readonly: bool = False) -> None:
    db = await _db(readonly=readonly)
    try:
        cursor = await db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        tables = {row[0] for row in await cursor.fetchall()}
        if not {"vault_metadata", "key_vault_items", "key_vault_snapshots", "key_vault_runs"} <= tables:
            raise RuntimeError("Vault database must be explicitly initialized before startup")
        required = {
            "vault_metadata": {"key", "value"},
            "key_vault_items": {"source_id", "token_ref", "token_id", "token_name", "key_fingerprint", "key_nonce", "key_ciphertext", "key_masked", "recoverable", "active", "missing_since", "last_seen_at", "raw_json", "status", "remain_quota", "used_quota", "total_quota", "group_name"},
            "key_vault_snapshots": {"id", "source_id", "nonce", "ciphertext", "item_count", "created_at"},
            "key_vault_runs": {"id", "source_id", "status", "item_count", "error_message", "created_at"},
        }
        for table, columns in required.items():
            cursor = await db.execute(f"PRAGMA table_info({table})")
            info = await cursor.fetchall()
            if not columns <= {row[1] for row in info}:
                raise RuntimeError("Vault database schema is incomplete")
            if table == "key_vault_items" and {row[1]: row[5] for row in info if row[5]} != {"source_id": 1, "token_ref": 2}:
                raise RuntimeError("Vault database identity constraint is invalid")
        await _verify_key_checks(db)
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
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("invalid upstream_base_url")
    all_items: list[dict[str, Any]] = []
    seen: set[str] = set()
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
            items = data["items"]
            reported_total = data.get("total")
            if type(reported_total) is not int or reported_total < 0 or (total is not None and total != reported_total):
                raise ValueError("upstream token total is missing or inconsistent")
            total = reported_total
            if any(not isinstance(item, dict) for item in items):
                raise ValueError("upstream token page contains invalid items")
            for item in items:
                token_ref = _token_item(item, str(source.get("id") or ""))[0]["token_ref"]
                if token_ref in seen:
                    raise ValueError("upstream token pagination contains duplicate items")
                seen.add(token_ref)
            if source.get("supports_key_lookup_by_id"):
                for item in items:
                    raw_key = str(item.get("key") or "").strip()
                    if raw_key and not any(mask in raw_key for mask in ("*", "...", "\u2026")):
                        all_items.append(item)
                        continue
                    token_id = str(item.get("id") or item.get("token_id") or item.get("tokenId") or "").strip()
                    item = dict(item)
                    item["key"] = await _resolve_token_key(client, source, token_id)
                    all_items.append(item)
            else:
                all_items.extend(items)
            if len(all_items) > total or (not items and len(all_items) < total):
                raise ValueError("upstream token pagination is incomplete")
            if len(all_items) == total:
                return all_items
            page += 1
    raise ValueError("upstream token pagination exceeded the safety limit")


async def _record_success(source: dict[str, Any], raw_items: list[dict[str, Any]]) -> None:
    source_id = str(source["id"])
    rows, snapshot = zip(*(_token_item(item, source_id) for item in raw_items)) if raw_items else ([], [])
    db = await _db()
    try:
        await db.execute("BEGIN")
        if not raw_items:
            cursor = await db.execute("SELECT 1 FROM key_vault_items WHERE source_id = ? AND active = 1 LIMIT 1", (source_id,))
            if await cursor.fetchone():
                raise ValueError("empty inventory requires manual review")
        await db.execute("UPDATE key_vault_items SET active = 0 WHERE source_id = ?", (source_id,))
        for index, row in enumerate(rows):
            key_nonce = key_ciphertext = None
            if row["recoverable"]:
                raw_key = snapshot[index]["key"]
                key_nonce, key_ciphertext = _encrypt(raw_key)
                snapshot[index]["key_origin"] = "current_observation"
            elif row["token_id"] is not None:
                cursor = await db.execute(
                    "SELECT token_id, key_fingerprint, key_nonce, key_ciphertext, recoverable FROM key_vault_items WHERE source_id = ? AND token_ref = ?",
                    (source_id, row["token_ref"]),
                )
                previous = await cursor.fetchone()
                if previous and previous["token_id"] == row["token_id"] and previous["recoverable"] and previous["key_nonce"] and previous["key_ciphertext"]:
                    snapshot[index]["key"] = json.loads(AES.decrypt(previous["key_nonce"], previous["key_ciphertext"], None))
                    snapshot[index]["key_fingerprint"] = previous["key_fingerprint"]
                    snapshot[index]["recoverable"] = 1
                    snapshot[index]["key_origin"] = "previous_observation"
            await db.execute(
                """
                INSERT INTO key_vault_items (
                    source_id, token_ref, token_id, token_name, key_fingerprint, key_nonce, key_ciphertext,
                    key_masked, recoverable, status, remain_quota, used_quota, total_quota, group_name,
                    raw_json, active, missing_since, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, NULL, datetime('now'))
                ON CONFLICT(source_id, token_ref) DO UPDATE SET
                    token_id=excluded.token_id, token_name=excluded.token_name,
                    key_fingerprint=CASE WHEN excluded.recoverable = 0 AND excluded.token_id IS NOT NULL AND key_vault_items.token_id = excluded.token_id THEN key_vault_items.key_fingerprint ELSE excluded.key_fingerprint END,
                    key_nonce=CASE WHEN excluded.recoverable = 0 AND excluded.token_id IS NOT NULL AND key_vault_items.token_id = excluded.token_id THEN key_vault_items.key_nonce ELSE excluded.key_nonce END,
                    key_ciphertext=CASE WHEN excluded.recoverable = 0 AND excluded.token_id IS NOT NULL AND key_vault_items.token_id = excluded.token_id THEN key_vault_items.key_ciphertext ELSE excluded.key_ciphertext END,
                    key_masked=excluded.key_masked,
                    recoverable=CASE WHEN excluded.recoverable = 0 AND excluded.token_id IS NOT NULL AND key_vault_items.token_id = excluded.token_id THEN key_vault_items.recoverable ELSE excluded.recoverable END, status=excluded.status,
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
        snapshot_nonce, snapshot_ciphertext = _encrypt(list(snapshot))
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
            (source_id, type(exc).__name__),
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
            logger.warning("key-vault poll failed for %s (%s)", source_id, type(exc).__name__)
            await _record_failure(source_id, exc)


async def _poll_loop() -> None:
    while True:
        try:
            await poll_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("key-vault control-plane poll failed (%s)", type(exc).__name__)
        await asyncio.sleep(POLL_SECONDS)


def _authorize(request: Request) -> None:
    candidate = request.headers.get("authorization", "").removeprefix("Bearer ")
    if not API_TOKEN or not secrets.compare_digest(candidate, API_TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized")


def validate_runtime_settings() -> None:
    if not DB_PATH.is_absolute():
        raise RuntimeError("KEY_VAULT_DB_PATH must be absolute")
    if any(not value.strip() or value != value.strip() or value.lower().startswith("change-me") for value in (API_TOKEN, LOOKUP_SECRET, CONTROL_PLANE_URL, CONTROL_PLANE_TOKEN)):
        raise RuntimeError("Vault API, lookup, and control-plane configuration must be set")
    if any(len(value) < 32 for value in (API_TOKEN, LOOKUP_SECRET, CONTROL_PLANE_TOKEN)):
        raise RuntimeError("Vault service tokens must each be at least 32 characters")
    control = urlsplit(CONTROL_PLANE_URL)
    if control.scheme not in {"http", "https"} or not control.hostname or control.username or control.password or control.query or control.fragment:
        raise RuntimeError("Vault control-plane URL is invalid")


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_runtime_settings()
    await require_vault_schema()
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


@app.get("/internal/key-vault/summary")
async def summary(request: Request) -> dict[str, Any]:
    """Report historical inventory status without returning key material."""
    _authorize(request)
    db = await _db(readonly=True)
    try:
        cursor = await db.execute(
            """SELECT sources.source_id, r.status AS last_status, r.created_at AS last_run_at,
                      r.item_count AS last_run_count, CASE WHEN r.status = 'error' THEN 'backup failed' ELSE NULL END AS last_error,
                      (SELECT COUNT(*) FROM key_vault_items i WHERE i.source_id = sources.source_id AND i.active = 1) AS active_count,
                      (SELECT COUNT(*) FROM key_vault_items i WHERE i.source_id = sources.source_id AND i.active = 1 AND i.recoverable = 1) AS stored_key_count
               FROM (SELECT source_id FROM key_vault_runs UNION SELECT source_id FROM key_vault_items) sources
               LEFT JOIN key_vault_runs r ON r.id = (SELECT id FROM key_vault_runs WHERE source_id = sources.source_id ORDER BY id DESC LIMIT 1)
               ORDER BY sources.source_id"""
        )
        return {"sources": [dict(row) for row in await cursor.fetchall()]}
    finally:
        await db.close()


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
