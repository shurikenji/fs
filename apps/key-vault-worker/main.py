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
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

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
POLL_SECONDS = max(60, int(os.getenv("KEY_VAULT_POLL_SECONDS", "1800")))
SNAPSHOT_RETENTION_DAYS = max(1, int(os.getenv("KEY_VAULT_SNAPSHOT_RETENTION_DAYS", "7")))
MISSING_RETENTION_DAYS = max(1, int(os.getenv("KEY_VAULT_MISSING_RETENTION_DAYS", "90")))
LOOKUP_INITIAL_BATCH_SIZE = min(100, max(1, int(os.getenv("KEY_VAULT_LOOKUP_INITIAL_BATCH_SIZE", "20"))))
LOOKUP_MAX_BATCH_SIZE = min(100, max(LOOKUP_INITIAL_BATCH_SIZE, int(os.getenv("KEY_VAULT_LOOKUP_MAX_BATCH_SIZE", "50"))))
LOOKUP_CYCLE_LIMIT = max(1, int(os.getenv("KEY_VAULT_LOOKUP_CYCLE_LIMIT", "50")))
LOOKUP_FALLBACK_RETRY_SECONDS = max(30, int(os.getenv("KEY_VAULT_LOOKUP_FALLBACK_RETRY_SECONDS", "300")))
LOOKUP_MAX_RETRY_SECONDS = max(
    LOOKUP_FALLBACK_RETRY_SECONDS,
    int(os.getenv("KEY_VAULT_LOOKUP_MAX_RETRY_SECONDS", "3600")),
)
SENSITIVE_FIELDS = {"key", "api_key", "apikey", "token", "access_token", "secret", "secret_key"}


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


def _lookup_batch_size(value: Any) -> int:
    return min(LOOKUP_MAX_BATCH_SIZE, max(1, _int(value, LOOKUP_INITIAL_BATCH_SIZE)))


def _retry_after_seconds(value: Any) -> int:
    raw = str(value or "").strip()
    if raw.isdecimal():
        return min(LOOKUP_MAX_RETRY_SECONDS, max(1, int(raw)))
    return LOOKUP_FALLBACK_RETRY_SECONDS


def _network_backoff_seconds(failure_count: int) -> int:
    steps = (5, 15, 30, 60, 120, 300)
    return min(LOOKUP_MAX_RETRY_SECONDS, steps[min(max(failure_count - 1, 0), len(steps) - 1)])


async def _lookup_source_state(source_id: str) -> dict[str, int]:
    db = await _db(readonly=True)
    try:
        row = await (
            await db.execute(
                "SELECT batch_size, next_retry_at, failure_count FROM key_vault_lookup_state WHERE source_id = ?",
                (source_id,),
            )
        ).fetchone()
        if row is None:
            return {"batch_size": LOOKUP_INITIAL_BATCH_SIZE, "next_retry_at": 0, "failure_count": 0}
        return {
            "batch_size": _lookup_batch_size(row["batch_size"]),
            "next_retry_at": max(0, _int(row["next_retry_at"])),
            "failure_count": max(0, _int(row["failure_count"])),
        }
    finally:
        await db.close()


async def _save_lookup_source_state(
    source_id: str,
    *,
    batch_size: int,
    next_retry_at: int = 0,
    failure_count: int = 0,
) -> None:
    db = await _db()
    try:
        await db.execute(
            """INSERT INTO key_vault_lookup_state (source_id, batch_size, next_retry_at, failure_count, updated_at)
               VALUES (?, ?, NULLIF(?, 0), ?, datetime('now'))
               ON CONFLICT(source_id) DO UPDATE SET
                   batch_size=excluded.batch_size,
                   next_retry_at=excluded.next_retry_at,
                   failure_count=excluded.failure_count,
                   updated_at=datetime('now')""",
            (source_id, _lookup_batch_size(batch_size), max(0, next_retry_at), max(0, failure_count)),
        )
        await db.commit()
    finally:
        await db.close()


async def _checkpoint_lookup_keys(source_id: str, resolved: dict[int, str]) -> None:
    if not resolved:
        return
    db = await _db()
    try:
        await db.execute("BEGIN")
        for token_id, full_key in resolved.items():
            nonce, ciphertext = _encrypt(full_key)
            await db.execute(
                """INSERT INTO key_vault_lookup_cache
                   (source_id, token_id, key_fingerprint, key_nonce, key_ciphertext, updated_at)
                   VALUES (?, ?, ?, ?, ?, datetime('now'))
                   ON CONFLICT(source_id, token_id) DO UPDATE SET
                       key_fingerprint=excluded.key_fingerprint,
                       key_nonce=excluded.key_nonce,
                       key_ciphertext=excluded.key_ciphertext,
                       updated_at=datetime('now')""",
                (source_id, str(token_id), _fingerprint(full_key), nonce, ciphertext),
            )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


async def _resolve_token_keys_batch(
    client: httpx.AsyncClient,
    source: dict[str, Any],
    token_ids: list[int],
) -> tuple[dict[int, str], dict[int, str], set[int], int]:
    source_id = str(source.get("id") or "").strip()
    base_url = str(source.get("upstream_base_url") or "").rstrip("/")
    resolved: dict[int, str] = {}
    errors: dict[int, str] = {}
    attempted: set[int] = set()
    state = await _lookup_source_state(source_id)
    batch_size = _lookup_batch_size(state["batch_size"])
    failure_count = state["failure_count"]
    now = int(time.time())
    next_retry_at = state["next_retry_at"]
    if next_retry_at > now:
        return resolved, errors, attempted, next_retry_at

    selected = token_ids[:LOOKUP_CYCLE_LIMIT]
    offset = 0
    while offset < len(selected):
        batch = selected[offset : offset + batch_size]
        attempted.update(batch)
        try:
            response = await client.post(
                f"{base_url}/api/token/batch/keys",
                headers=_headers(source),
                json={"ids": batch},
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            retry_after = exc.response.headers.get("Retry-After", "")
            code = f"api_http_{status}" + (f"_retry_{retry_after}" if retry_after.isdecimal() else "")
            for token_id in batch:
                errors[token_id] = code
            batch_size = max(1, batch_size // 2)
            failure_count += 1
            if status == 429:
                next_retry_at = int(time.time()) + _retry_after_seconds(retry_after)
                await _save_lookup_source_state(
                    source_id,
                    batch_size=batch_size,
                    next_retry_at=next_retry_at,
                    failure_count=failure_count,
                )
                logger.warning(
                    "full-key lookup deferred for source %s (status=429 retry_after=%s remaining=%s)",
                    source_id,
                    retry_after or "NONE",
                    len(token_ids) - len(attempted),
                )
                break
            if status in {401, 403} or status >= 500:
                delay = LOOKUP_FALLBACK_RETRY_SECONDS if status in {401, 403} else _network_backoff_seconds(failure_count)
                next_retry_at = int(time.time()) + delay
                await _save_lookup_source_state(
                    source_id,
                    batch_size=batch_size,
                    next_retry_at=next_retry_at,
                    failure_count=failure_count,
                )
                break
            await _save_lookup_source_state(
                source_id,
                batch_size=batch_size,
                failure_count=failure_count,
            )
            offset += len(batch)
            continue
        except httpx.RequestError:
            for token_id in batch:
                errors[token_id] = "network_error"
            batch_size = max(1, batch_size // 2)
            failure_count += 1
            next_retry_at = int(time.time()) + _network_backoff_seconds(failure_count)
            await _save_lookup_source_state(
                source_id,
                batch_size=batch_size,
                next_retry_at=next_retry_at,
                failure_count=failure_count,
            )
            logger.warning(
                "full-key lookup deferred for source %s (network_error remaining=%s)",
                source_id,
                len(token_ids) - len(attempted),
            )
            break
        except (TypeError, ValueError, json.JSONDecodeError):
            for token_id in batch:
                errors[token_id] = "invalid_response"
            batch_size = max(1, batch_size // 2)
            failure_count += 1
            await _save_lookup_source_state(
                source_id,
                batch_size=batch_size,
                failure_count=failure_count,
            )
            offset += len(batch)
            continue
        data = payload.get("data") if isinstance(payload, dict) else None
        keys = data.get("keys") if isinstance(data, dict) else None
        if not isinstance(payload, dict) or payload.get("success") is False or not isinstance(keys, dict):
            for token_id in batch:
                errors[token_id] = "invalid_response"
            batch_size = max(1, batch_size // 2)
            failure_count += 1
            await _save_lookup_source_state(
                source_id,
                batch_size=batch_size,
                failure_count=failure_count,
            )
            offset += len(batch)
            continue
        batch_resolved: dict[int, str] = {}
        for token_id in batch:
            value = keys.get(str(token_id))
            key = value.strip() if isinstance(value, str) else ""
            if not key or any(mask in key for mask in ("*", "...", "\u2026")):
                errors[token_id] = "full_key_unavailable"
                continue
            batch_resolved[token_id] = key if key.startswith("sk-") else f"sk-{key}"
        resolved.update(batch_resolved)
        await _checkpoint_lookup_keys(source_id, batch_resolved)
        failure_count = 0
        batch_size = min(LOOKUP_MAX_BATCH_SIZE, batch_size + 10)
        next_retry_at = 0
        await _save_lookup_source_state(
            source_id,
            batch_size=batch_size,
            failure_count=0,
        )
        offset += len(batch)
    return resolved, errors, attempted, next_retry_at


def _token_item(raw: dict[str, Any], source_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    raw_key = str(raw.get("key") or "").strip()
    source_masked_key = str(raw.get("_vault_masked_key") or "").strip()
    full_key = raw_key if raw_key and not any(mask in raw_key for mask in ("*", "...", "\u2026")) else ""
    if full_key and not full_key.startswith("sk-"):
        full_key = f"sk-{full_key}"
    token_id = str(raw.get("id") or raw.get("token_id") or raw.get("tokenId") or "").strip()
    token_name = str(raw.get("name") or raw.get("token_name") or "").strip()
    fingerprint = _fingerprint(full_key) if full_key else ""
    token_ref = str(raw.get("_vault_token_ref") or "").strip() or token_id or ("key:" + fingerprint[:24] if fingerprint else "masked:" + hashlib.sha256((raw_key + token_name).encode()).hexdigest()[:24])
    remain = _int(raw.get("remain_quota", raw.get("remainQuota")))
    used = _int(raw.get("used_quota", raw.get("usedQuota")))
    total = _int(raw.get("total_quota", raw.get("totalQuota")), remain + used)
    lookup_next_retry_at = _int(raw.get("_vault_lookup_next_retry_at")) or None
    row = {
        "source_id": source_id,
        "token_ref": token_ref,
        "token_id": token_id or None,
        "token_name": token_name or None,
        "key_fingerprint": fingerprint or None,
        "key_masked": source_masked_key or (_mask(full_key) if full_key else (raw_key or None)),
        "recoverable": 1 if full_key else 0,
        "key_lookup_status": str(raw.get("_vault_lookup_status") or ("available" if full_key else "unverified")),
        "key_lookup_error": str(raw.get("_vault_lookup_error") or "").strip() or None,
        "key_lookup_attempted": 1 if raw.get("_vault_lookup_attempted") else 0,
        "key_lookup_next_retry_at": lookup_next_retry_at,
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
                lookup_error_count INTEGER NOT NULL DEFAULT 0,
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
                source_status TEXT NOT NULL DEFAULT 'active',
                removed_at TEXT,
                first_seen_at TEXT DEFAULT (datetime('now')),
                key_lookup_status TEXT NOT NULL DEFAULT 'unverified',
                key_lookup_error TEXT,
                key_lookup_last_attempt_at TEXT,
                key_lookup_attempts INTEGER NOT NULL DEFAULT 0,
                key_lookup_next_retry_at INTEGER,
                last_seen_at TEXT DEFAULT (datetime('now')),
                PRIMARY KEY(source_id, token_ref)
            );
            CREATE TABLE IF NOT EXISTS key_vault_item_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER REFERENCES key_vault_runs(id),
                source_id TEXT NOT NULL,
                token_ref TEXT NOT NULL,
                source_status TEXT NOT NULL,
                key_masked TEXT,
                key_lookup_status TEXT NOT NULL DEFAULT 'unverified',
                status INTEGER NOT NULL DEFAULT 1,
                remain_quota INTEGER NOT NULL DEFAULT 0,
                used_quota INTEGER NOT NULL DEFAULT 0,
                total_quota INTEGER NOT NULL DEFAULT 0,
                group_name TEXT,
                raw_json TEXT,
                observed_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS key_vault_status_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER REFERENCES key_vault_runs(id),
                source_id TEXT NOT NULL,
                token_ref TEXT NOT NULL,
                source_status TEXT NOT NULL,
                changed_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS key_vault_lookup_state (
                source_id TEXT PRIMARY KEY,
                batch_size INTEGER NOT NULL DEFAULT 20,
                next_retry_at INTEGER,
                failure_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS key_vault_lookup_cache (
                source_id TEXT NOT NULL,
                token_id TEXT NOT NULL,
                key_fingerprint TEXT NOT NULL,
                key_nonce BLOB NOT NULL,
                key_ciphertext BLOB NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                PRIMARY KEY(source_id, token_id)
            );
            CREATE INDEX IF NOT EXISTS idx_key_vault_fingerprint ON key_vault_items(source_id, key_fingerprint, active);
            CREATE INDEX IF NOT EXISTS idx_key_vault_token_id ON key_vault_items(source_id, token_id, active);
            CREATE INDEX IF NOT EXISTS idx_key_vault_history_item ON key_vault_item_history(source_id, token_ref, observed_at);
            CREATE INDEX IF NOT EXISTS idx_key_vault_status_item ON key_vault_status_history(source_id, token_ref, changed_at);
            """
        )
        run_columns = {row[1] for row in await (await db.execute("PRAGMA table_info(key_vault_runs)")).fetchall()}
        if "lookup_error_count" not in run_columns:
            await db.execute("ALTER TABLE key_vault_runs ADD COLUMN lookup_error_count INTEGER NOT NULL DEFAULT 0")

        item_columns = {row[1] for row in await (await db.execute("PRAGMA table_info(key_vault_items)")).fetchall()}
        source_status_added = "source_status" not in item_columns
        migrations = {
            "source_status": "ALTER TABLE key_vault_items ADD COLUMN source_status TEXT NOT NULL DEFAULT 'active'",
            "removed_at": "ALTER TABLE key_vault_items ADD COLUMN removed_at TEXT",
            "first_seen_at": "ALTER TABLE key_vault_items ADD COLUMN first_seen_at TEXT",
            "key_lookup_status": "ALTER TABLE key_vault_items ADD COLUMN key_lookup_status TEXT NOT NULL DEFAULT 'unverified'",
            "key_lookup_error": "ALTER TABLE key_vault_items ADD COLUMN key_lookup_error TEXT",
            "key_lookup_last_attempt_at": "ALTER TABLE key_vault_items ADD COLUMN key_lookup_last_attempt_at TEXT",
            "key_lookup_attempts": "ALTER TABLE key_vault_items ADD COLUMN key_lookup_attempts INTEGER NOT NULL DEFAULT 0",
            "key_lookup_next_retry_at": "ALTER TABLE key_vault_items ADD COLUMN key_lookup_next_retry_at INTEGER",
        }
        for column, sql in migrations.items():
            if column not in item_columns:
                await db.execute(sql)
        if source_status_added:
            await db.execute("UPDATE key_vault_items SET source_status = CASE WHEN active = 1 THEN 'active' ELSE 'removed' END")
        else:
            await db.execute("UPDATE key_vault_items SET source_status = CASE WHEN active = 1 THEN 'active' ELSE 'removed' END WHERE source_status IS NULL OR source_status = ''")
        await db.execute("UPDATE key_vault_items SET removed_at = COALESCE(removed_at, missing_since) WHERE source_status = 'removed'")
        await db.execute("UPDATE key_vault_items SET first_seen_at = COALESCE(first_seen_at, last_seen_at, datetime('now'))")
        await db.execute("UPDATE key_vault_items SET key_lookup_status = CASE WHEN recoverable = 1 THEN 'available' ELSE COALESCE(NULLIF(key_lookup_status, ''), 'unverified') END")

        backfill = await (await db.execute("SELECT value FROM vault_metadata WHERE key = 'item_history_backfill_v1'")).fetchone()
        if backfill is None:
            snapshots = await (await db.execute("SELECT id, source_id, nonce, ciphertext, created_at FROM key_vault_snapshots ORDER BY id")).fetchall()
            for saved in snapshots:
                try:
                    items = json.loads(AES.decrypt(saved["nonce"], saved["ciphertext"], None))
                except Exception:
                    logger.warning("Skipping unreadable historical vault snapshot id=%s", saved["id"])
                    continue
                if not isinstance(items, list):
                    continue
                for item in items:
                    if not isinstance(item, dict) or not str(item.get("token_ref") or "").strip():
                        continue
                    raw_json = item.get("raw_json")
                    if not isinstance(raw_json, str):
                        raw_json = json.dumps(_clean_raw(raw_json), ensure_ascii=True, default=str)
                    await db.execute(
                        """INSERT INTO key_vault_item_history
                           (run_id, source_id, token_ref, source_status, key_masked, key_lookup_status, status,
                            remain_quota, used_quota, total_quota, group_name, raw_json, observed_at)
                           VALUES (NULL, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            saved["source_id"], str(item["token_ref"]), item.get("key_masked"),
                            "available" if item.get("recoverable") else "unverified", _int(item.get("status"), 1),
                            _int(item.get("remain_quota")), _int(item.get("used_quota")), _int(item.get("total_quota")),
                            item.get("group_name"), raw_json, saved["created_at"],
                        ),
                    )
            await db.execute("INSERT INTO vault_metadata (key, value) VALUES ('item_history_backfill_v1', 'done')")
        await db.execute(
            """UPDATE key_vault_items
               SET first_seen_at = COALESCE(
                   (SELECT MIN(h.observed_at) FROM key_vault_item_history h
                     WHERE h.source_id = key_vault_items.source_id AND h.token_ref = key_vault_items.token_ref),
                   first_seen_at, last_seen_at, datetime('now'))"""
        )
        await db.execute(
            """INSERT INTO key_vault_status_history (source_id, token_ref, source_status, changed_at)
               SELECT i.source_id, i.token_ref, i.source_status, COALESCE(i.first_seen_at, i.last_seen_at, datetime('now'))
                 FROM key_vault_items i
                WHERE NOT EXISTS (
                    SELECT 1 FROM key_vault_status_history h
                     WHERE h.source_id = i.source_id AND h.token_ref = i.token_ref
                )"""
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
        if not {
            "vault_metadata", "key_vault_items", "key_vault_snapshots", "key_vault_runs",
            "key_vault_item_history", "key_vault_status_history", "key_vault_lookup_state",
            "key_vault_lookup_cache",
        } <= tables:
            raise RuntimeError("Vault database must be explicitly initialized before startup")
        required = {
            "vault_metadata": {"key", "value"},
            "key_vault_items": {"source_id", "token_ref", "token_id", "token_name", "key_fingerprint", "key_nonce", "key_ciphertext", "key_masked", "recoverable", "active", "missing_since", "source_status", "removed_at", "first_seen_at", "key_lookup_status", "key_lookup_error", "key_lookup_last_attempt_at", "key_lookup_attempts", "key_lookup_next_retry_at", "last_seen_at", "raw_json", "status", "remain_quota", "used_quota", "total_quota", "group_name"},
            "key_vault_snapshots": {"id", "source_id", "nonce", "ciphertext", "item_count", "created_at"},
            "key_vault_runs": {"id", "source_id", "status", "item_count", "lookup_error_count", "error_message", "created_at"},
            "key_vault_item_history": {"id", "run_id", "source_id", "token_ref", "source_status", "key_masked", "key_lookup_status", "status", "remain_quota", "used_quota", "total_quota", "group_name", "raw_json", "observed_at"},
            "key_vault_status_history": {"id", "run_id", "source_id", "token_ref", "source_status", "changed_at"},
            "key_vault_lookup_state": {"source_id", "batch_size", "next_retry_at", "failure_count", "updated_at"},
            "key_vault_lookup_cache": {"source_id", "token_id", "key_fingerprint", "key_nonce", "key_ciphertext", "created_at", "updated_at"},
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
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
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


async def _stored_key_state(source_id: str) -> list[dict[str, Any]]:
    db = await _db(readonly=True)
    try:
        cursor = await db.execute(
            "SELECT token_ref, token_id, key_masked, recoverable, key_nonce, key_ciphertext FROM key_vault_items WHERE source_id = ?",
            (source_id,),
        )
        result = []
        by_id: dict[str, dict[str, Any]] = {}
        for saved in await cursor.fetchall():
            row = dict(saved)
            row["full_key_valid"] = False
            if row.get("recoverable") and row.get("key_nonce") and row.get("key_ciphertext"):
                try:
                    value = json.loads(AES.decrypt(row["key_nonce"], row["key_ciphertext"], None))
                    row["full_key_valid"] = isinstance(value, str) and bool(value.strip())
                except Exception:
                    pass
            result.append(row)
            if str(row.get("token_id") or "").strip():
                by_id[str(row["token_id"])] = row

        cache = await db.execute(
            "SELECT token_id, key_nonce, key_ciphertext FROM key_vault_lookup_cache WHERE source_id = ?",
            (source_id,),
        )
        for saved in await cache.fetchall():
            token_id = str(saved["token_id"] or "").strip()
            if not token_id:
                continue
            existing = by_id.get(token_id)
            if existing and existing.get("full_key_valid"):
                continue
            try:
                value = json.loads(AES.decrypt(saved["key_nonce"], saved["key_ciphertext"], None))
            except Exception:
                continue
            if not isinstance(value, str) or not value.strip():
                continue
            if existing:
                existing["full_key_valid"] = True
                existing["cached_full_key"] = value
            else:
                row = {
                    "token_ref": token_id,
                    "token_id": token_id,
                    "key_masked": None,
                    "recoverable": 1,
                    "key_nonce": saved["key_nonce"],
                    "key_ciphertext": saved["key_ciphertext"],
                    "full_key_valid": True,
                    "cached_full_key": value,
                }
                result.append(row)
                by_id[token_id] = row
        return result
    finally:
        await db.close()


async def _fetch_tokens(source: dict[str, Any]) -> list[dict[str, Any]]:
    source_id = str(source.get("id") or "").strip()
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
            all_items.extend(items)
            if len(all_items) > total or (not items and len(all_items) < total):
                raise ValueError("upstream token pagination is incomplete")
            if len(all_items) == total:
                break
            page += 1
        else:
            raise ValueError("upstream token pagination exceeded the safety limit")

        stored = await _stored_key_state(source_id)
        by_id = {
            str(row["token_id"]): row
            for row in stored
            if str(row.get("token_id") or "").strip()
        }

        unresolved: list[tuple[dict[str, Any], int]] = []
        for item in all_items:
            raw_key = str(item.get("key") or "").strip()
            is_masked = not raw_key or any(mask in raw_key for mask in ("*", "...", "\u2026"))
            if is_masked and raw_key:
                item["_vault_masked_key"] = raw_key
            token_id = str(item.get("id") or item.get("token_id") or item.get("tokenId") or "").strip()
            existing = by_id.get(token_id) if token_id else None
            if existing:
                item["_vault_token_ref"] = existing["token_ref"]

            if not is_masked:
                item["_vault_lookup_status"] = "available"
                continue

            if existing and existing.get("full_key_valid"):
                cached_full_key = existing.get("cached_full_key")
                if isinstance(cached_full_key, str) and cached_full_key:
                    item["key"] = cached_full_key
                item["_vault_lookup_status"] = "available"
                continue

            if not token_id.isascii() or not token_id.isdecimal() or int(token_id) <= 0:
                item["_vault_lookup_status"] = "unverified"
                item["_vault_lookup_error"] = "missing_stable_id"
                continue

            if not source.get("supports_key_lookup_by_id"):
                item["_vault_lookup_status"] = "unverified"
                item["_vault_lookup_error"] = "lookup_not_supported"
                continue
            unresolved.append((item, int(token_id)))

        if unresolved:
            keys, errors, attempted, next_retry_at = await _resolve_token_keys_batch(
                client,
                source,
                [token_id for _, token_id in unresolved],
            )
            for item, token_id in unresolved:
                if token_id in attempted:
                    item["_vault_lookup_attempted"] = True
                if token_id in keys:
                    item["key"] = keys[token_id]
                    item["_vault_lookup_status"] = "available"
                    item.pop("_vault_lookup_error", None)
                    item.pop("_vault_lookup_next_retry_at", None)
                elif next_retry_at:
                    item["_vault_lookup_status"] = "retry_wait"
                    item["_vault_lookup_next_retry_at"] = next_retry_at
                    if token_id in errors:
                        item["_vault_lookup_error"] = errors[token_id]
                    else:
                        item.pop("_vault_lookup_error", None)
                elif token_id in attempted:
                    item["_vault_lookup_status"] = "error"
                    item["_vault_lookup_error"] = errors.get(token_id, "full_key_unavailable")
                else:
                    item["_vault_lookup_status"] = "pending"
                    item.pop("_vault_lookup_error", None)
        return all_items


async def _record_success(source: dict[str, Any], raw_items: list[dict[str, Any]]) -> None:
    source_id = str(source["id"])
    converted = [_token_item(item, source_id) for item in raw_items]
    rows = [item[0] for item in converted]
    snapshot = [item[1] for item in converted]
    lookup_error_count = sum(1 for row in rows if row["key_lookup_error"])
    run_status = "partial" if any(row["key_lookup_status"] != "available" for row in rows) else "success"
    db = await _db()
    try:
        await db.execute("BEGIN")
        existing_rows = [
            dict(row)
            for row in await (await db.execute("SELECT * FROM key_vault_items WHERE source_id = ?", (source_id,))).fetchall()
        ]
        if existing_rows and not rows:
            raise ValueError("empty upstream inventory requires manual review")
        existing = {str(row["token_ref"]): row for row in existing_rows}
        run_cursor = await db.execute(
            "INSERT INTO key_vault_runs (source_id, status, item_count, lookup_error_count) VALUES (?, ?, ?, ?)",
            (source_id, run_status, len(rows), lookup_error_count),
        )
        run_id = int(run_cursor.lastrowid)
        observed_refs = {str(row["token_ref"]) for row in rows}
        for previous in existing_rows:
            token_ref = str(previous["token_ref"])
            if token_ref in observed_refs or previous.get("source_status") == "removed":
                continue
            await db.execute(
                """UPDATE key_vault_items
                      SET active = 0, source_status = 'removed',
                          missing_since = COALESCE(missing_since, datetime('now')),
                          removed_at = COALESCE(removed_at, datetime('now'))
                    WHERE source_id = ? AND token_ref = ?""",
                (source_id, token_ref),
            )
            await db.execute(
                "INSERT INTO key_vault_status_history (run_id, source_id, token_ref, source_status) VALUES (?, ?, ?, 'removed')",
                (run_id, source_id, token_ref),
            )

        for index, row in enumerate(rows):
            key_nonce = key_ciphertext = None
            previous = existing.get(str(row["token_ref"]))
            same_identity = bool(
                previous
                and (
                    (row["token_id"] is not None and previous.get("token_id") == row["token_id"])
                    or (row["token_id"] is None and previous.get("token_ref") == row["token_ref"])
                )
            )
            key_fingerprint = row["key_fingerprint"]
            recoverable = int(row["recoverable"])
            lookup_status = row["key_lookup_status"]
            lookup_error = row["key_lookup_error"]
            if row["recoverable"]:
                raw_key = snapshot[index]["key"]
                key_nonce, key_ciphertext = _encrypt(raw_key)
                snapshot[index]["key_origin"] = "current_observation"
            elif same_identity and previous and previous.get("recoverable") and previous.get("key_nonce") and previous.get("key_ciphertext"):
                key_nonce = previous["key_nonce"]
                key_ciphertext = previous["key_ciphertext"]
                key_fingerprint = previous.get("key_fingerprint")
                recoverable = 1
                lookup_status = "available"
                lookup_error = None
                snapshot[index]["key"] = json.loads(AES.decrypt(key_nonce, key_ciphertext, None))
                snapshot[index]["key_fingerprint"] = key_fingerprint
                snapshot[index]["recoverable"] = 1
                snapshot[index]["key_lookup_status"] = "available"
                snapshot[index]["key_lookup_error"] = None
                snapshot[index]["key_origin"] = "previous_observation"
            await db.execute(
                """
                INSERT INTO key_vault_items (
                    source_id, token_ref, token_id, token_name, key_fingerprint, key_nonce, key_ciphertext,
                    key_masked, recoverable, status, remain_quota, used_quota, total_quota, group_name,
                    raw_json, active, missing_since, source_status, removed_at, first_seen_at,
                    key_lookup_status, key_lookup_error, key_lookup_next_retry_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, NULL, 'active', NULL, datetime('now'), ?, ?, ?, datetime('now'))
                ON CONFLICT(source_id, token_ref) DO UPDATE SET
                    token_id=excluded.token_id, token_name=excluded.token_name,
                    key_fingerprint=excluded.key_fingerprint,
                    key_nonce=excluded.key_nonce,
                    key_ciphertext=excluded.key_ciphertext,
                    key_masked=excluded.key_masked,
                    recoverable=excluded.recoverable, status=excluded.status,
                    remain_quota=excluded.remain_quota, used_quota=excluded.used_quota,
                    total_quota=excluded.total_quota, group_name=excluded.group_name,
                    raw_json=excluded.raw_json, active=1, missing_since=NULL, source_status='active', removed_at=NULL,
                    key_lookup_status=excluded.key_lookup_status, key_lookup_error=excluded.key_lookup_error,
                    key_lookup_next_retry_at=excluded.key_lookup_next_retry_at,
                    last_seen_at=datetime('now')
                """,
                (
                    row["source_id"], row["token_ref"], row["token_id"], row["token_name"],
                    key_fingerprint, key_nonce, key_ciphertext, row["key_masked"], recoverable,
                    row["status"], row["remain_quota"], row["used_quota"], row["total_quota"],
                    row["group_name"], row["raw_json"], lookup_status, lookup_error, row["key_lookup_next_retry_at"],
                ),
            )
            if row["key_lookup_attempted"]:
                await db.execute(
                    """UPDATE key_vault_items
                          SET key_lookup_last_attempt_at = datetime('now'),
                              key_lookup_attempts = key_lookup_attempts + 1
                        WHERE source_id = ? AND token_ref = ?""",
                    (source_id, row["token_ref"]),
                )
            if not previous or previous.get("source_status") != "active":
                await db.execute(
                    "INSERT INTO key_vault_status_history (run_id, source_id, token_ref, source_status) VALUES (?, ?, ?, 'active')",
                    (run_id, source_id, row["token_ref"]),
                )
            await db.execute(
                """INSERT INTO key_vault_item_history
                   (run_id, source_id, token_ref, source_status, key_masked, key_lookup_status, status,
                    remain_quota, used_quota, total_quota, group_name, raw_json)
                   VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id, source_id, row["token_ref"], row["key_masked"], lookup_status, row["status"],
                    row["remain_quota"], row["used_quota"], row["total_quota"], row["group_name"], row["raw_json"],
                ),
            )

        snapshot_nonce, snapshot_ciphertext = _encrypt(snapshot)
        await db.execute(
            "INSERT INTO key_vault_snapshots (source_id, nonce, ciphertext, item_count) VALUES (?, ?, ?, ?)",
            (source_id, snapshot_nonce, snapshot_ciphertext, len(rows)),
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


async def _record_failure(source_id: str, exc: Exception) -> None:
    db = await _db()
    try:
        await db.execute("BEGIN")
        cursor = await db.execute(
            "INSERT INTO key_vault_runs (source_id, status, error_message) VALUES (?, 'error', ?)",
            (source_id, type(exc).__name__),
        )
        run_id = int(cursor.lastrowid)
        active_rows = await (
            await db.execute(
                "SELECT token_ref FROM key_vault_items WHERE source_id = ? AND source_status = 'active'",
                (source_id,),
            )
        ).fetchall()
        if active_rows:
            await db.execute(
                "UPDATE key_vault_items SET source_status = 'unknown' WHERE source_id = ? AND source_status = 'active'",
                (source_id,),
            )
            for row in active_rows:
                await db.execute(
                    "INSERT INTO key_vault_status_history (run_id, source_id, token_ref, source_status) VALUES (?, ?, ?, 'unknown')",
                    (run_id, source_id, row["token_ref"]),
                )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
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
    try:
        sources = await _sources()
    except Exception as exc:
        db = await _db(readonly=True)
        try:
            known_sources = [
                str(row["source_id"])
                for row in await (
                    await db.execute(
                        "SELECT DISTINCT source_id FROM key_vault_items WHERE source_status = 'active'"
                    )
                ).fetchall()
            ]
        finally:
            await db.close()
        for source_id in known_sources:
            await _record_failure(source_id, exc)
        raise

    for source in sources:
        source_id = str(source["id"])
        try:
            await _record_success(source, await _fetch_tokens(source))
        except Exception as exc:
            if isinstance(exc, httpx.HTTPStatusError):
                path = exc.request.url.path
                endpoint = "batch-keys" if path.endswith("/api/token/batch/keys") else "token-list" if path.endswith("/api/token/") else "upstream"
                logger.warning(
                    "key-vault poll failed for %s (HTTPStatusError status=%s retry_after=%s endpoint=%s)",
                    source_id,
                    exc.response.status_code,
                    exc.response.headers.get("Retry-After", "NONE"),
                    endpoint,
                )
            else:
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
    await init_db()
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
                      COALESCE(r.lookup_error_count, 0) AS lookup_error_count,
                      (SELECT COUNT(*) FROM key_vault_items i WHERE i.source_id = sources.source_id) AS total_count,
                      (SELECT COUNT(*) FROM key_vault_items i WHERE i.source_id = sources.source_id AND i.source_status = 'active') AS active_count,
                      (SELECT COUNT(*) FROM key_vault_items i WHERE i.source_id = sources.source_id AND i.source_status = 'removed') AS removed_count,
                      (SELECT COUNT(*) FROM key_vault_items i WHERE i.source_id = sources.source_id AND i.source_status = 'unknown') AS unknown_count,
                      (SELECT COUNT(*) FROM key_vault_items i WHERE i.source_id = sources.source_id AND i.recoverable = 1) AS stored_key_count,
                      (SELECT COALESCE(SUM(i.remain_quota), 0) FROM key_vault_items i WHERE i.source_id = sources.source_id AND i.source_status = 'active') AS active_remain_quota
               FROM (SELECT source_id FROM key_vault_runs UNION SELECT source_id FROM key_vault_items) sources
               LEFT JOIN key_vault_runs r ON r.id = (SELECT id FROM key_vault_runs WHERE source_id = sources.source_id ORDER BY id DESC LIMIT 1)
               ORDER BY sources.source_id"""
        )
        return {"sources": [dict(row) for row in await cursor.fetchall()]}
    finally:
        await db.close()


def _admin_item(row: dict[str, Any], *, include_full_key: bool) -> dict[str, Any]:
    full_key = None
    if include_full_key and row.get("recoverable") and row.get("key_nonce") and row.get("key_ciphertext"):
        try:
            value = json.loads(AES.decrypt(row["key_nonce"], row["key_ciphertext"], None))
            full_key = value if isinstance(value, str) else None
        except Exception:
            full_key = None
    return {
        key: row.get(key)
        for key in (
            "source_id", "token_ref", "token_id", "token_name", "key_masked", "recoverable",
            "key_lookup_status", "key_lookup_error", "key_lookup_last_attempt_at", "source_status",
            "removed_at", "first_seen_at", "last_seen_at", "status", "remain_quota", "used_quota",
            "total_quota", "group_name",
        )
    } | {"key_value": full_key}


@app.get("/internal/key-vault/items/{source_id}")
async def inventory(request: Request, source_id: str) -> dict[str, Any]:
    _authorize(request)
    db = await _db(readonly=True)
    try:
        cursor = await db.execute(
            """SELECT * FROM key_vault_items WHERE source_id = ?
               ORDER BY CASE source_status WHEN 'active' THEN 0 WHEN 'unknown' THEN 1 ELSE 2 END,
                        token_name COLLATE NOCASE, token_ref""",
            (source_id,),
        )
        return {"items": [_admin_item(dict(row), include_full_key=True) for row in await cursor.fetchall()]}
    finally:
        await db.close()


@app.get("/internal/key-vault/runs/{source_id}")
async def runs(request: Request, source_id: str) -> dict[str, Any]:
    _authorize(request)
    db = await _db(readonly=True)
    try:
        cursor = await db.execute(
            """SELECT id, source_id, status, item_count, lookup_error_count,
                      CASE WHEN status = 'error' THEN error_message ELSE NULL END AS error_message, created_at
                 FROM key_vault_runs WHERE source_id = ? ORDER BY id DESC LIMIT 200""",
            (source_id,),
        )
        return {"runs": [dict(row) for row in await cursor.fetchall()]}
    finally:
        await db.close()


@app.get("/internal/key-vault/item")
async def item_detail(request: Request) -> dict[str, Any]:
    _authorize(request)
    source_id = str(request.query_params.get("source_id") or "").strip()
    token_ref = str(request.query_params.get("token_ref") or "").strip()
    if not source_id or not token_ref:
        raise HTTPException(status_code=422, detail="source_id and token_ref are required")
    db = await _db(readonly=True)
    try:
        current = await (
            await db.execute(
                "SELECT * FROM key_vault_items WHERE source_id = ? AND token_ref = ? LIMIT 1",
                (source_id, token_ref),
            )
        ).fetchone()
        if current is None:
            return {"item": None, "history": [], "status_history": []}
        history = await (
            await db.execute(
                """SELECT run_id, source_status, key_masked, key_lookup_status, status,
                          remain_quota, used_quota, total_quota, group_name, observed_at
                     FROM key_vault_item_history
                    WHERE source_id = ? AND token_ref = ? ORDER BY id DESC""",
                (source_id, token_ref),
            )
        ).fetchall()
        status_history = await (
            await db.execute(
                """SELECT run_id, source_status, changed_at FROM key_vault_status_history
                    WHERE source_id = ? AND token_ref = ? ORDER BY id DESC""",
                (source_id, token_ref),
            )
        ).fetchall()
        return {
            "item": _admin_item(dict(current), include_full_key=True),
            "history": [dict(row) for row in history],
            "status_history": [dict(row) for row in status_history],
        }
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
