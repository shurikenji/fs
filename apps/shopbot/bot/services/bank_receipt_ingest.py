"""Persist an observed bank feed before matching individual transactions."""
from __future__ import annotations

from collections import Counter
import re
from typing import Any

from bot.services.mbbank import extract_order_code
from db.database import get_db
from db.queries.payment_receipts import match_receipt, record_receipt


async def ingest_transactions(
    transactions: list[dict[str, Any]], *, account_identity: str, account_verified: bool = False,
) -> dict[str, int]:
    """Store each valid incoming receipt, including unmatched and late payments."""
    if not isinstance(account_identity, str) or not account_identity.strip():
        raise ValueError("bank account identity is required")
    counts: Counter[str] = Counter()
    for transaction in transactions:
        if not isinstance(transaction, dict):
            counts["invalid"] += 1
            continue
        description = transaction.get("description", "")
        if not isinstance(description, str):
            description = ""
        transaction_time = transaction.get("transactionDate")
        if not isinstance(transaction_time, str) or len(transaction_time) > 100:
            transaction_time = None
        codes = set(re.findall(r"ORD[A-Z0-9]{8}", description.upper().replace(" ", "")))
        order_code = extract_order_code(description) if len(codes) == 1 else None
        try:
            result, receipt_id = await record_receipt(
                provider="mbbank", account_identity=account_identity,
                transaction_id=transaction.get("transactionID"), amount=transaction.get("amount"),
                transaction_time=transaction_time,
                order_code=order_code, description=description[:2000],
            )
        except ValueError:
            counts["invalid"] += 1
            continue
        if result == "conflict":
            counts["conflict"] += 1
            continue
        counts[await match_receipt(receipt_id, account_verified=account_verified)] += 1
    return dict(counts)


async def reconcile_unmatched_receipts(*, account_identity: str, limit: int = 100) -> int:
    """Retry known order codes once the bank account and timezone are verified."""
    if not account_identity or type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("invalid receipt reconciliation parameters")
    db = await get_db()
    cursor = await db.execute(
        """SELECT r.id FROM payment_receipts r WHERE r.provider = 'mbbank' AND r.account_identity = ?
           AND r.status = 'unmatched' AND r.order_code IS NOT NULL
           AND EXISTS (SELECT 1 FROM orders o WHERE o.order_code = r.order_code)
           ORDER BY r.id LIMIT ?""",
        (account_identity.strip(), limit),
    )
    ids = [row[0] for row in await cursor.fetchall()]
    for receipt_id in ids:
        await match_receipt(receipt_id, account_verified=True)
    return len(ids)
