"""Run one durable fulfillment job without replaying uncertain side effects."""
from __future__ import annotations

import logging
import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from db.queries.fulfillment import claim_next, finish_claim

logger = logging.getLogger(__name__)
Handler = Callable[[dict[str, Any]], Awaitable[None]]


async def run_one(handler: Handler, *, owner: str, lease_seconds: int = 300) -> bool:
    """Claim one job; failures are reviewed, never retried automatically."""
    claim = await claim_next(owner, lease_seconds)
    if claim is None:
        return False
    try:
        await handler(claim)
    except Exception as exc:
        logger.error("Fulfillment job %s failed (%s); review required", claim["id"], type(exc).__name__)
        await finish_claim(claim["id"], claim["lease_token"], succeeded=False)
    else:
        await finish_claim(claim["id"], claim["lease_token"], succeeded=True)
    return True


async def process_shopbot_claim(bot, claim: dict[str, Any]) -> None:
    """Process only order types that have a conservative worker implementation."""
    from bot.services.payment_poller import _execute_order
    from db.queries.orders import get_order_by_id

    order = await get_order_by_id(claim["order_id"])
    if not order or order["status"] != "processing":
        raise RuntimeError("claimed order is missing or no longer processing")
    if order["product_type"] == "service_upgrade":
        from db.queries.fulfillment import prepare_service_order

        if not await prepare_service_order(claim["id"], claim["lease_token"]):
            raise RuntimeError("service order lease is invalid")
        return
    if order["product_type"] not in {"key_new", "key_topup", "wallet_topup", "account_stocked"}:
        # shortcut: other order types need fenced handlers before automatic worker dispatch.
        logger.warning("Fulfillment job %s requires a supported handler", claim["id"])
        return
    order["_fulfillment_claim"] = claim
    await _execute_order(bot, order)


async def start_fulfillment_worker(bot) -> None:
    owner = uuid.uuid4().hex
    while True:
        try:
            worked = await run_one(lambda claim: process_shopbot_claim(bot, claim), owner=owner)
            if not worked:
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Fulfillment worker failure (%s)", type(exc).__name__)
            await asyncio.sleep(5)
