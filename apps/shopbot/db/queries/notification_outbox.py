"""Persist completion notifications inside the transaction that completed an order."""
import secrets

from db.database import open_write_transaction


async def enqueue_order_completion(db, order_id: int, user_id: int | None) -> None:
    for event_type in ("user_order_completed", "admin_order_completed"):
        await db.execute(
            """INSERT OR IGNORE INTO notification_outbox (event_key, event_type, order_id, user_id, status)
               VALUES (?, ?, ?, ?, 'pending')""",
            (f"{event_type}:{order_id}", event_type, order_id, user_id),
        )


async def enqueue_service_paid(db, order_id: int, user_id: int) -> None:
    for event_type in ("user_service_paid", "admin_service_paid"):
        await db.execute(
            """INSERT OR IGNORE INTO notification_outbox (event_key, event_type, order_id, user_id, status)
               VALUES (?, ?, ?, ?, 'pending')""",
            (f"{event_type}:{order_id}", event_type, order_id, user_id),
        )


async def enqueue_service_completed(db, order_id: int, user_id: int) -> None:
    for event_type in ("user_service_completed", "admin_service_completed"):
        await db.execute(
            """INSERT OR IGNORE INTO notification_outbox (event_key, event_type, order_id, user_id, status)
               VALUES (?, ?, ?, ?, 'pending')""",
            (f"{event_type}:{order_id}", event_type, order_id, user_id),
        )


async def enqueue_order_review(db, order_id: int, user_id: int, *, reference: str) -> None:
    for event_type in ("user_order_review", "admin_order_review"):
        await db.execute(
            """INSERT OR IGNORE INTO notification_outbox (event_key, event_type, order_id, user_id, status)
               VALUES (?, ?, ?, ?, 'pending')""",
            (f"{event_type}:{reference}", event_type, order_id, user_id),
        )


async def enqueue_order_refund(db, order_id: int, user_id: int) -> None:
    for event_type in ("user_order_refunded", "admin_order_refunded"):
        await db.execute(
            """INSERT OR IGNORE INTO notification_outbox (event_key, event_type, order_id, user_id, status)
               VALUES (?, ?, ?, ?, 'pending')""",
            (f"{event_type}:{order_id}", event_type, order_id, user_id),
        )


async def claim_notification(lease_seconds: int = 120) -> dict | None:
    if type(lease_seconds) is not int or lease_seconds <= 0:
        raise ValueError("invalid notification lease")
    db = await open_write_transaction()
    try:
        await db.execute(
            """UPDATE notification_outbox SET status = CASE WHEN attempts >= 3 THEN 'failed' ELSE 'pending' END,
               lease_token = NULL, lease_until = NULL, last_error = 'notification delivery outcome unknown'
               WHERE status = 'sending' AND lease_until <= CURRENT_TIMESTAMP"""
        )
        cursor = await db.execute(
            """SELECT * FROM notification_outbox WHERE status = 'pending'
               AND (next_attempt_at IS NULL OR next_attempt_at <= CURRENT_TIMESTAMP) ORDER BY id LIMIT 1"""
        )
        row = await cursor.fetchone()
        if row is None:
            await db.commit()
            return None
        token = secrets.token_urlsafe(24)
        await db.execute(
            """UPDATE notification_outbox SET status = 'sending', attempts = attempts + 1,
               lease_token = ?, lease_until = datetime('now', ?) WHERE id = ? AND status = 'pending'""",
            (token, f"+{lease_seconds} seconds", row["id"]),
        )
        await db.commit()
        return {**dict(row), "lease_token": token, "attempts": row["attempts"] + 1}
    except BaseException:
        await db.rollback()
        raise
    finally:
        await db.close()


async def finish_notification(event_id: int, token: str, *, succeeded: bool) -> bool:
    db = await open_write_transaction()
    try:
        cursor = await db.execute(
            """SELECT attempts FROM notification_outbox WHERE id = ? AND status = 'sending'
               AND lease_token = ? AND lease_until > CURRENT_TIMESTAMP""",
            (event_id, token),
        )
        row = await cursor.fetchone()
        if row is None:
            await db.rollback()
            return False
        attempts = row["attempts"]
        status = "sent" if succeeded else ("failed" if attempts >= 3 else "pending")
        delay = (5, 30, 120)[min(attempts - 1, 2)]
        await db.execute(
            """UPDATE notification_outbox SET status = ?, lease_token = NULL, lease_until = NULL,
               next_attempt_at = CASE WHEN ? = 'pending' THEN datetime('now', ?) ELSE NULL END,
               last_error = CASE WHEN ? = 'sent' THEN NULL ELSE 'notification failed' END WHERE id = ?""",
            (status, status, f"+{delay} seconds", status, event_id),
        )
        await db.commit()
        return True
    except BaseException:
        await db.rollback()
        raise
    finally:
        await db.close()
