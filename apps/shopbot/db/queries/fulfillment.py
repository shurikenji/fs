"""Durable fulfillment queue primitives; callers own external side effects."""
from __future__ import annotations

import json
import secrets

from db.database import get_db, open_write_transaction
from db.financial_migration import REQUIRED_COLUMNS, REQUIRED_TABLES, REQUIRED_UNIQUE_INDEX, VERSION


async def require_financial_schema() -> None:
    """Fail closed until the explicit financial migration has been applied."""
    db = await get_db()
    cursor = await db.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'shopbot_schema_migrations'")
    if await cursor.fetchone() is None:
        raise RuntimeError("Financial migration is required before starting the bot")
    cursor = await db.execute("SELECT 1 FROM shopbot_schema_migrations WHERE version = ?", (VERSION,))
    if await cursor.fetchone() is None:
        raise RuntimeError("Financial migration is required before starting the bot")
    cursor = await db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    tables = {row[0] for row in await cursor.fetchall()}
    if not REQUIRED_TABLES <= tables:
        raise RuntimeError("Financial schema is incomplete")
    for table, columns in REQUIRED_COLUMNS.items():
        cursor = await db.execute(f"PRAGMA table_info({table})")
        if not columns <= {row[1] for row in await cursor.fetchall()}:
            raise RuntimeError("Financial schema is incomplete")
    cursor = await db.execute("PRAGMA index_list(wallet_transactions)")
    if not any(row[1] == REQUIRED_UNIQUE_INDEX and row[2] == 1 for row in await cursor.fetchall()):
        raise RuntimeError("Financial schema is incomplete")


async def enqueue_paid_order(db, order_id: int) -> None:
    """Enqueue inside the caller's transaction, together with payment."""
    cursor = await db.execute(
        """INSERT OR IGNORE INTO fulfillment_jobs (order_id, job_type, status)
           SELECT id, 'fulfill', 'pending' FROM orders
           WHERE id = ? AND status = 'paid' AND is_refunded = 0""",
        (order_id,),
    )
    if cursor.rowcount != 1:
        cursor = await db.execute(
            """SELECT 1 FROM fulfillment_jobs j JOIN orders o ON o.id = j.order_id
               WHERE j.order_id = ? AND j.job_type = 'fulfill' AND o.status = 'paid' AND o.is_refunded = 0""",
            (order_id,),
        )
        if not await cursor.fetchone():
            raise ValueError("order is not eligible for a fulfillment job")


async def claim_next(owner: str, lease_seconds: int = 300) -> dict | None:
    """Atomically claim a paid order; expired claims require reconciliation."""
    if not owner or type(lease_seconds) is not int or lease_seconds <= 0:
        raise ValueError("invalid lease")
    db = await open_write_transaction()
    try:
        await db.execute(
            """UPDATE fulfillment_jobs SET status = 'needs_review', last_error = 'lease expired',
               lease_owner = NULL, lease_token = NULL, lease_until = NULL, updated_at = CURRENT_TIMESTAMP
               WHERE status = 'processing' AND lease_until <= CURRENT_TIMESTAMP"""
        )
        from db.queries.notification_outbox import enqueue_order_review

        cursor = await db.execute(
            """SELECT o.id, o.user_id, j.id AS job_id FROM orders o JOIN fulfillment_jobs j ON j.order_id = o.id
               WHERE j.status = 'needs_review' AND j.last_error = 'lease expired' AND o.user_id IS NOT NULL
                 AND NOT EXISTS (SELECT 1 FROM notification_outbox n WHERE n.event_key = 'admin_order_review:job:' || j.id)
               LIMIT 100"""
        )
        for order in await cursor.fetchall():
            if order["user_id"] is not None:
                await enqueue_order_review(db, order["id"], order["user_id"], reference=f"job:{order['job_id']}")
        cursor = await db.execute(
            """SELECT j.id, j.order_id FROM fulfillment_jobs j JOIN orders o ON o.id = j.order_id
               WHERE j.status = 'pending' AND (j.next_attempt_at IS NULL OR j.next_attempt_at <= CURRENT_TIMESTAMP)
                 AND o.status = 'paid' AND o.is_refunded = 0 ORDER BY j.id LIMIT 1"""
        )
        job = await cursor.fetchone()
        if not job:
            await db.commit()
            return None
        token = secrets.token_urlsafe(24)
        await db.execute(
            """UPDATE fulfillment_jobs SET status = 'processing', attempts = attempts + 1,
               lease_owner = ?, lease_token = ?, lease_until = datetime('now', ?), updated_at = CURRENT_TIMESTAMP
               WHERE id = ? AND status = 'pending'""",
            (owner, token, f"+{lease_seconds} seconds", job["id"]),
        )
        await db.execute(
            "UPDATE orders SET status = 'processing', updated_at = datetime('now', '+7 hours') WHERE id = ? AND status = 'paid' AND is_refunded = 0",
            (job["order_id"],),
        )
        await db.commit()
        return {"id": job["id"], "order_id": job["order_id"], "lease_token": token}
    except BaseException:
        await db.rollback()
        raise
    finally:
        await db.close()


async def finish_claim(job_id: int, token: str, *, succeeded: bool) -> bool:
    """Finish only the current, unexpired lease; incomplete orders need review."""
    db = await open_write_transaction()
    try:
        cursor = await db.execute(
            """UPDATE fulfillment_jobs SET status = CASE
                   WHEN ? AND EXISTS (SELECT 1 FROM orders o WHERE o.id = fulfillment_jobs.order_id AND o.status = 'completed'
                       AND (o.product_type NOT IN ('key_new', 'key_topup') OR
                           (SELECT COUNT(*) FROM fulfillment_operations p WHERE p.job_id = fulfillment_jobs.id AND p.status = 'succeeded') >=
                           CASE WHEN o.product_type = 'key_new' THEN MAX(1, COALESCE(o.quantity, 1)) ELSE 1 END))
                     AND NOT EXISTS (SELECT 1 FROM fulfillment_operations f WHERE f.job_id = fulfillment_jobs.id AND f.status != 'succeeded')
                   THEN 'completed' ELSE 'needs_review' END,
               lease_owner = NULL, lease_token = NULL, lease_until = NULL, updated_at = CURRENT_TIMESTAMP
               WHERE id = ? AND status = 'processing' AND lease_token = ? AND lease_until > CURRENT_TIMESTAMP""",
            (succeeded, job_id, token),
        )
        updated = cursor.rowcount == 1
        if updated:
            cursor = await db.execute(
                """SELECT j.status, o.id, o.user_id, o.product_type FROM fulfillment_jobs j
                   JOIN orders o ON o.id = j.order_id WHERE j.id = ?""", (job_id,)
            )
            order = await cursor.fetchone()
            if order["status"] == "needs_review" and order["product_type"] != "service_upgrade" and order["user_id"] is not None:
                from db.queries.notification_outbox import enqueue_order_review

                await db.execute("UPDATE fulfillment_jobs SET last_error = 'fulfillment requires review' WHERE id = ?", (job_id,))
                await enqueue_order_review(db, order["id"], order["user_id"], reference=f"job:{job_id}")
        await db.commit()
        return updated
    except BaseException:
        await db.rollback()
        raise
    finally:
        await db.close()


async def begin_operation(job_id: int, token: str, item_index: int, *, delivery: dict | None = None) -> int | None:
    """Persist the send boundary once; an existing attempt must be reconciled."""
    if type(item_index) is not int or item_index < 0:
        raise ValueError("invalid item index")
    db = await open_write_transaction()
    try:
        cursor = await db.execute(
            """SELECT j.order_id, o.product_type, o.quantity FROM fulfillment_jobs j
               JOIN orders o ON o.id = j.order_id WHERE j.id = ? AND j.status = 'processing' AND o.status = 'processing'
               AND j.lease_token = ? AND j.lease_until > CURRENT_TIMESTAMP""",
            (job_id, token),
        )
        job = await cursor.fetchone()
        if not job:
            await db.rollback()
            return None
        limit = max(1, job["quantity"] or 1) if job["product_type"] == "key_new" else 1
        if item_index >= limit:
            raise ValueError("item index exceeds the order quantity")
        operation_key = f"order:{job['order_id']}:item:{item_index}"
        cursor = await db.execute(
            """INSERT OR IGNORE INTO fulfillment_operations
               (job_id, item_index, operation_key, status, sent_at)
               VALUES (?, ?, ?, 'sending', CURRENT_TIMESTAMP)""",
            (job_id, item_index, operation_key),
        )
        result = cursor.lastrowid if cursor.rowcount == 1 else None
        if result is not None and delivery is not None:
            await db.execute(
                """UPDATE orders SET api_key = ?, api_token_id = ?, api_token_name = ?, quota_after = ?,
                   delivery_info = ?, delivery_token_names = ?, updated_at = datetime('now', '+7 hours')
                   WHERE id = ? AND status = 'processing'""",
                (delivery.get("api_key"), delivery.get("api_token_id"), delivery.get("api_token_name"),
                 delivery.get("quota_after"), delivery.get("delivery_info"), delivery.get("delivery_token_names"),
                 job["order_id"]),
            )
        await db.commit()
        return result
    except BaseException:
        await db.rollback()
        raise
    finally:
        await db.close()


async def confirm_operation(job_id: int, token: str, operation_id: int, remote_id: str | None = None) -> bool:
    """Record a confirmed remote response only while the job lease is valid."""
    db = await open_write_transaction()
    try:
        cursor = await db.execute(
            """UPDATE fulfillment_operations SET status = 'succeeded', remote_id = ?
               WHERE id = ? AND job_id = ? AND status = 'sending'
                 AND EXISTS (SELECT 1 FROM fulfillment_jobs j WHERE j.id = ?
                     AND j.status = 'processing' AND j.lease_token = ? AND j.lease_until > CURRENT_TIMESTAMP
                     AND EXISTS (SELECT 1 FROM orders o WHERE o.id = j.order_id AND o.status = 'processing'))""",
            (remote_id, operation_id, job_id, job_id, token),
        )
        await db.commit()
        return cursor.rowcount == 1
    except BaseException:
        await db.rollback()
        raise
    finally:
        await db.close()


async def confirm_created_key(job_id: int, token: str, operation_id: int, api_key: str, token_id: int | None, quota: int) -> bool:
    """Persist a created key, its valuation baseline and its operation together."""
    if not isinstance(api_key, str) or not api_key.strip() or api_key != api_key.strip() or len(api_key) > 4096 or any(mask in api_key for mask in ("*", "...", "…")):
        raise ValueError("created key is missing or masked")
    if token_id is not None and (type(token_id) is not int or token_id <= 0):
        raise ValueError("created token identity is invalid")
    if type(quota) is not int or not 0 < quota <= 2**63 - 1:
        raise ValueError("created quota is invalid")
    db = await open_write_transaction()
    try:
        cursor = await db.execute(
            """SELECT o.*, f.item_index FROM orders o JOIN fulfillment_jobs j ON j.order_id = o.id
               JOIN fulfillment_operations f ON f.job_id = j.id
               WHERE j.id = ? AND f.id = ? AND f.status = 'sending' AND j.status = 'processing'
                 AND j.lease_token = ? AND j.lease_until > CURRENT_TIMESTAMP
                 AND o.status = 'processing' AND o.product_type = 'key_new' AND o.is_refunded = 0""",
            (job_id, operation_id, token),
        )
        row = await cursor.fetchone()
        if row is None:
            await db.rollback()
            return False
        order = dict(row)
        cursor = await db.execute("SELECT * FROM api_servers WHERE id = ?", (order["server_id"],))
        server = await cursor.fetchone()
        if server is None:
            raise ValueError("created key server is unavailable")
        from bot.services.key_valuation import KeyValuationService, hash_api_key
        from bot.utils.formatting import mask_api_key

        cursor = await db.execute("SELECT 1 FROM api_key_registry WHERE server_id = ? AND api_key_hash = ?", (order["server_id"], hash_api_key(api_key)))
        if await cursor.fetchone():
            raise ValueError("created key is already registered")
        cursor = await db.execute("SELECT 1 FROM user_keys WHERE server_id = ? AND api_key IN (?, ?)",
                                  (order["server_id"], api_key, api_key[3:] if api_key.startswith("sk-") else f"sk-{api_key}"))
        if await cursor.fetchone():
            raise ValueError("created key is already assigned")
        cursor = await db.execute(
            "INSERT INTO user_keys (user_id, server_id, api_key, api_token_id, label) VALUES (?, ?, ?, ?, ?)",
            (order["user_id"], order["server_id"], api_key, token_id, mask_api_key(api_key)),
        )
        user_key_id = cursor.lastrowid
        await KeyValuationService.record_platform_quota_offset(
            user_id=order["user_id"], server=dict(server), api_key=api_key, quota_delta=quota,
            resulting_total_quota=quota, source="platform_key_new",
            source_ref=f"order:{order['id']}:seq:{order['item_index'] + 1}",
            _db=db, _pricing_version={"id": order.get("pricing_version_id")},
        )
        cursor = await db.execute(
            """UPDATE fulfillment_operations SET status = 'succeeded', remote_id = ?, result_summary = ?
               WHERE id = ? AND job_id = ? AND status = 'sending'
                 AND EXISTS (SELECT 1 FROM fulfillment_jobs j WHERE j.id = ? AND j.status = 'processing'
                             AND j.lease_token = ? AND j.lease_until > CURRENT_TIMESTAMP)""",
            (str(token_id) if token_id is not None else None, json.dumps({"user_key_id": user_key_id}),
             operation_id, job_id, job_id, token),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("Fulfillment lease expired before key confirmation")
        await db.commit()
        return True
    except BaseException:
        await db.rollback()
        raise
    finally:
        await db.close()


async def complete_key_order(job_id: int, token: str, delivery: dict) -> bool:
    """Commit key delivery only when every item is confirmed under the lease."""
    db = await open_write_transaction()
    try:
        cursor = await db.execute(
            """SELECT o.id, o.user_id, o.server_id, o.quantity FROM orders o
               JOIN fulfillment_jobs j ON j.order_id = o.id
               WHERE j.id = ? AND j.status = 'processing' AND j.lease_token = ?
                 AND j.lease_until > CURRENT_TIMESTAMP AND o.status = 'processing'
                 AND o.product_type = 'key_new' AND o.is_refunded = 0""", (job_id, token),
        )
        order = await cursor.fetchone()
        cursor = await db.execute(
            "SELECT item_index, status, result_summary FROM fulfillment_operations WHERE job_id = ? ORDER BY item_index", (job_id,)
        )
        operations = await cursor.fetchall()
        if not order or len(operations) != max(1, order['quantity'] or 1):
            await db.rollback()
            return False
        key_ids = []
        for index, operation in enumerate(operations):
            try:
                key_id = json.loads(operation['result_summary'])['user_key_id']
            except (TypeError, ValueError, KeyError):
                await db.rollback()
                return False
            if operation['item_index'] != index or operation['status'] != 'succeeded' or type(key_id) is not int or key_id <= 0 or key_id in key_ids:
                await db.rollback()
                return False
            key_ids.append(key_id)
        keys = []
        from bot.services.key_valuation import hash_api_key

        for index, key_id in enumerate(key_ids):
            cursor = await db.execute(
                "SELECT api_key, api_token_id FROM user_keys WHERE id = ? AND user_id = ? AND server_id = ?",
                (key_id, order['user_id'], order['server_id']),
            )
            key = await cursor.fetchone()
            if not key or not key['api_key']:
                await db.rollback()
                return False
            cursor = await db.execute(
                """SELECT 1 FROM api_key_valuation_events e JOIN api_key_registry r ON r.id = e.api_key_registry_id
                   WHERE r.server_id = ? AND r.api_key_hash = ? AND e.user_id = ?
                     AND e.source = 'platform_key_new' AND e.source_ref = ? AND e.status = 'platform_offset'""",
                (order['server_id'], hash_api_key(key['api_key']), order['user_id'], f"order:{order['id']}:seq:{index + 1}"),
            )
            if await cursor.fetchone() is None:
                await db.rollback()
                return False
            keys.append(key)
        if (delivery.get('api_key') != keys[0]['api_key'] or delivery.get('api_token_id') != keys[0]['api_token_id']
                or delivery.get('delivery_info') != ('\n'.join(key['api_key'] for key in keys) if len(keys) > 1 else None)):
            await db.rollback()
            return False
        cursor = await db.execute(
            """UPDATE orders SET status = 'completed', completed_at = datetime('now', '+7 hours'),
               updated_at = datetime('now', '+7 hours'), api_key = ?, api_token_id = ?, api_token_name = ?,
               quota_after = ?, delivery_info = ?, delivery_token_names = ?
               WHERE status = 'processing' AND product_type = 'key_new' AND EXISTS (
                   SELECT 1 FROM fulfillment_jobs j WHERE j.id = ? AND j.order_id = orders.id
                   AND j.status = 'processing' AND j.lease_token = ? AND j.lease_until > CURRENT_TIMESTAMP
                   AND (SELECT COUNT(*) FROM fulfillment_operations f WHERE f.job_id = j.id AND f.status = 'succeeded')
                       = MAX(1, COALESCE(orders.quantity, 1))
                   AND NOT EXISTS (SELECT 1 FROM fulfillment_operations f WHERE f.job_id = j.id AND f.status != 'succeeded')
               )""",
            (delivery.get("api_key"), delivery.get("api_token_id"), delivery.get("api_token_name"),
             delivery.get("quota_after"), delivery.get("delivery_info"), delivery.get("delivery_token_names"),
             job_id, token),
        )
        if cursor.rowcount == 1:
            cursor = await db.execute("SELECT o.* FROM orders o JOIN fulfillment_jobs j ON j.order_id = o.id WHERE j.id = ?", (job_id,))
            order = dict(await cursor.fetchone())
            from bot.services.spend_ledger import SpendLedgerService
            from db.queries.notification_outbox import enqueue_order_completion

            await SpendLedgerService.record_order_completion(order, _db=db)
            await enqueue_order_completion(db, order["id"], order.get("user_id"))
            completed = True
        else:
            completed = False
        await db.commit()
        return completed
    except BaseException:
        await db.rollback()
        raise
    finally:
        await db.close()


async def complete_stock_order(job_id: int, token: str) -> list[dict] | None:
    """Sell all reserved stock and persist delivery in one fenced transaction."""
    db = await open_write_transaction()
    try:
        cursor = await db.execute(
            """SELECT o.id, o.user_id, o.product_id, o.quantity FROM orders o
               JOIN fulfillment_jobs j ON j.order_id = o.id
               WHERE j.id = ? AND j.status = 'processing' AND j.lease_token = ?
                 AND j.lease_until > CURRENT_TIMESTAMP AND o.status = 'processing'
                 AND o.product_type = 'account_stocked' AND o.is_refunded = 0""",
            (job_id, token),
        )
        order = await cursor.fetchone()
        if not order or type(order["quantity"]) is not int or order["quantity"] <= 0:
            await db.rollback()
            return None
        cursor = await db.execute(
            "SELECT * FROM account_stocks WHERE sold_order_id = ? AND is_sold = 0 ORDER BY id",
            (order["id"],),
        )
        accounts = await cursor.fetchall()
        if len(accounts) != order["quantity"] or any(row["product_id"] != order["product_id"] for row in accounts):
            await db.rollback()
            return None
        await db.execute(
            """UPDATE account_stocks SET is_sold = 1, sold_to_user = ?, sold_at = datetime('now', '+7 hours')
               WHERE sold_order_id = ? AND is_sold = 0""",
            (order["user_id"], order["id"]),
        )
        delivery = "\n\n──────────\n\n".join(row["account_data"] for row in accounts)
        await db.execute(
            """UPDATE orders SET status = 'completed', completed_at = datetime('now', '+7 hours'),
               updated_at = datetime('now', '+7 hours'), delivery_info = ? WHERE id = ? AND status = 'processing'""",
            (delivery, order["id"]),
        )
        from db.queries.notification_outbox import enqueue_order_completion

        await enqueue_order_completion(db, order["id"], order["user_id"])
        await db.commit()
        return [dict(row) for row in accounts]
    except BaseException:
        await db.rollback()
        raise
    finally:
        await db.close()


async def prepare_service_order(job_id: int, token: str) -> bool:
    """Request manual service fulfillment and persist both notifications."""
    db = await open_write_transaction()
    try:
        cursor = await db.execute(
            """SELECT o.id, o.user_id FROM orders o JOIN fulfillment_jobs j ON j.order_id = o.id
               WHERE j.id = ? AND j.status = 'processing' AND j.lease_token = ? AND j.lease_until > CURRENT_TIMESTAMP
                 AND o.status = 'processing' AND o.product_type = 'service_upgrade' AND o.is_refunded = 0""",
            (job_id, token),
        )
        order = await cursor.fetchone()
        if order is None:
            await db.rollback()
            return False
        from db.queries.notification_outbox import enqueue_service_paid

        await enqueue_service_paid(db, order["id"], order["user_id"])
        await db.commit()
        return True
    except BaseException:
        await db.rollback()
        raise
    finally:
        await db.close()


async def complete_manual_service(order_id: int) -> bool:
    """Complete a manual service only after active work has stopped."""
    db = await open_write_transaction()
    try:
        cursor = await db.execute(
            """UPDATE orders SET status = 'completed', completed_at = datetime('now', '+7 hours'),
               updated_at = datetime('now', '+7 hours') WHERE id = ? AND status = 'processing'
               AND product_type = 'service_upgrade' AND is_refunded = 0
               AND NOT EXISTS (SELECT 1 FROM fulfillment_jobs j WHERE j.order_id = orders.id AND j.status != 'needs_review')""",
            (order_id,),
        )
        if cursor.rowcount != 1:
            await db.rollback()
            return False
        cursor = await db.execute("SELECT user_id FROM orders WHERE id = ?", (order_id,))
        user_id = (await cursor.fetchone())["user_id"]
        await db.execute(
            "UPDATE fulfillment_jobs SET status = 'completed', updated_at = CURRENT_TIMESTAMP WHERE order_id = ? AND status = 'needs_review'",
            (order_id,),
        )
        from db.queries.notification_outbox import enqueue_service_completed

        await enqueue_service_completed(db, order_id, user_id)
        await db.commit()
        return True
    except BaseException:
        await db.rollback()
        raise
    finally:
        await db.close()
