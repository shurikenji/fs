"""
db/queries/admin_notifications.py - Outbox helpers for admin Telegram notifications.
"""
from __future__ import annotations

from db.queries._helpers import execute_commit, fetch_all_dicts, fetch_one_dict


async def create_admin_notification_event(
    *,
    order_id: int,
    event_type: str,
    target_chat_id: int,
    message_text: str,
) -> bool:
    """Create or refresh an outbox record. Return False when this notification was already sent."""
    existing = await fetch_one_dict(
        """SELECT status FROM admin_notification_events
           WHERE order_id = ? AND event_type = ? AND target_chat_id = ?""",
        (order_id, event_type, target_chat_id),
    )
    if existing and existing.get("status") == "sent":
        return False

    if existing:
        await execute_commit(
            """UPDATE admin_notification_events
               SET status = 'pending',
                   message_text = ?,
                   error_message = NULL,
                   updated_at = datetime('now', '+7 hours')
               WHERE order_id = ? AND event_type = ? AND target_chat_id = ?""",
            (message_text, order_id, event_type, target_chat_id),
        )
        return True

    cursor = await execute_commit(
        """INSERT INTO admin_notification_events
           (order_id, event_type, target_chat_id, status, message_text, updated_at)
           VALUES (?, ?, ?, 'pending', ?, datetime('now', '+7 hours'))""",
        (order_id, event_type, target_chat_id, message_text),
    )
    return bool(cursor.rowcount)


async def mark_admin_notification_sent(
    *,
    order_id: int,
    event_type: str,
    target_chat_id: int,
) -> None:
    """Mark an outbox record as sent."""
    await execute_commit(
        """UPDATE admin_notification_events
           SET status = 'sent',
               sent_at = datetime('now', '+7 hours'),
               error_message = NULL,
               updated_at = datetime('now', '+7 hours')
           WHERE order_id = ? AND event_type = ? AND target_chat_id = ?""",
        (order_id, event_type, target_chat_id),
    )


async def mark_admin_notification_failed(
    *,
    order_id: int,
    event_type: str,
    target_chat_id: int,
    error_message: str,
) -> None:
    """Mark an outbox record as failed."""
    await execute_commit(
        """UPDATE admin_notification_events
           SET status = 'failed',
               error_message = ?,
               updated_at = datetime('now', '+7 hours')
           WHERE order_id = ? AND event_type = ? AND target_chat_id = ?""",
        (error_message, order_id, event_type, target_chat_id),
    )


async def get_admin_notification_events(*, order_id: int) -> list[dict]:
    """List admin notification outbox rows for an order."""
    return await fetch_all_dicts(
        """SELECT * FROM admin_notification_events
           WHERE order_id = ?
           ORDER BY id ASC""",
        (order_id,),
    )

