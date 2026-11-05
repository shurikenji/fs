"""Record a manually verified upstream top-up without issuing remote requests."""
import json
import re

from db.database import open_write_transaction


async def complete_manual_topup(order_id: int, token_id: int, before: int, after: int, delta: int, evidence: str, actor: str) -> bool:
    values = (order_id, token_id, before, after, delta)
    if (any(type(value) is not int or value < 0 or value > 2**63 - 1 for value in values)
            or not order_id or not token_id or not delta or before + delta != after
            or not re.fullmatch(r"[A-Za-z0-9._:/-]{4,80}", evidence)
            or actor not in {"password", "platform-control"}):
        raise ValueError("invalid reconciliation evidence")
    db = await open_write_transaction()
    try:
        cursor = await db.execute(
            """SELECT o.*, j.id AS job_id FROM orders o JOIN fulfillment_jobs j ON j.order_id = o.id
               WHERE o.id = ? AND o.product_type = 'key_topup' AND o.status = 'processing'
                 AND o.is_refunded = 0 AND o.quantity = 1 AND j.status = 'needs_review'
                 AND NOT EXISTS (SELECT 1 FROM fulfillment_operations f WHERE f.job_id = j.id)""", (order_id,),
        )
        row = await cursor.fetchone()
        if not row:
            await db.rollback()
            return False
        order = dict(row)
        key = order['existing_key']
        if (not isinstance(key, str) or not key.strip() or key != key.strip()
                or any(mask in key for mask in ('*', '...', '\u2026'))
                or (order['custom_quota'] is not None and order['custom_quota'] != delta)):
            raise ValueError("order key or quota requires further review")
        from bot.services.key_valuation import KeyValuationService, hash_api_key
        from bot.services.spend_ledger import SpendLedgerService
        from bot.utils.formatting import mask_api_key
        from db.queries.notification_outbox import enqueue_order_completion

        cursor = await db.execute("SELECT * FROM api_servers WHERE id = ?", (order['server_id'],))
        server = await cursor.fetchone()
        if server is None:
            raise ValueError("order server is unavailable")
        cursor = await db.execute("SELECT owner_user_id, last_observed_total_quota FROM api_key_registry WHERE server_id = ? AND api_key_hash = ?",
                                  (order['server_id'], hash_api_key(key)))
        registry = await cursor.fetchone()
        if registry and (registry['owner_user_id'] != order['user_id'] or (registry['last_observed_total_quota'] or 0) > before):
            raise ValueError("key ownership or prior baseline requires further review")
        alternate = key[3:] if key.startswith('sk-') else f'sk-{key}'
        cursor = await db.execute("SELECT * FROM user_keys WHERE server_id = ? AND api_key IN (?, ?)", (order['server_id'], key, alternate))
        keys = await cursor.fetchall()
        if len(keys) > 1 or (keys and (keys[0]['user_id'] != order['user_id'] or keys[0]['api_token_id'] not in (None, token_id))):
            raise ValueError("key association requires further review")
        if keys:
            await db.execute("UPDATE user_keys SET api_token_id = ? WHERE id = ?", (token_id, keys[0]['id']))
        else:
            await db.execute("INSERT INTO user_keys (user_id, server_id, api_key, api_token_id, label) VALUES (?, ?, ?, ?, ?)",
                             (order['user_id'], order['server_id'], key, token_id, mask_api_key(key)))
        await KeyValuationService.record_platform_quota_offset(
            user_id=order['user_id'], server=dict(server), api_key=key, quota_delta=delta,
            resulting_total_quota=after, source='platform_key_topup', source_ref=f'order:{order_id}',
            _db=db, _pricing_version={'id': order['pricing_version_id']},
        )
        summary = json.dumps({'method': 'manual', 'actor': actor, 'evidence': evidence,
                              'total_before': before, 'total_after': after, 'quota_added': delta})
        await db.execute("""INSERT INTO fulfillment_operations (job_id, item_index, operation_key, status, remote_id, result_summary)
                            VALUES (?, 0, ?, 'succeeded', ?, ?)""",
                         (order['job_id'], f'order:{order_id}:item:0', str(token_id), summary))
        await db.execute("""UPDATE orders SET status = 'completed', api_key = ?, api_token_id = ?,
                            quota_before = ?, quota_after = ?, completed_at = datetime('now', '+7 hours'),
                            updated_at = datetime('now', '+7 hours') WHERE id = ? AND status = 'processing'""",
                         (key, token_id, before, after, order_id))
        await SpendLedgerService.record_order_completion(order, _db=db)
        await enqueue_order_completion(db, order_id, order['user_id'])
        await db.execute("UPDATE fulfillment_jobs SET status = 'completed', last_error = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'needs_review'", (order['job_id'],))
        await db.commit()
        return True
    except BaseException:
        await db.rollback()
        raise
    finally:
        await db.close()
