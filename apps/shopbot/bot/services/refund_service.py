"""
bot/services/refund_service.py - Refund processing service.

Extracts refund logic from payment_poller.py for better modularity.
"""
from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot

from bot.utils.formatting import format_vnd
from db.queries.logs import add_log

logger = logging.getLogger(__name__)

Order = dict[str, Any]


async def refund_order(
    bot: Bot,
    order: Order,
    reason: str,
) -> None:
    """
    Hoàn tiền cho đơn một lần duy nhất rồi thông báo cho user và admin.
    
    Args:
        bot: Telegram bot instance
        order: Order dict with keys: id, order_code, amount, user_id
        reason: Reason for the refund
    """
    from db.queries.wallets import refund_order_to_wallet

    amount = order["amount"]
    new_balance = await refund_order_to_wallet(
        order["id"],
        reason=reason,
        tx_type="refund",
        description=refund_transaction_description(reason),
    )
    if new_balance is None:
        logger.warning("Order %s cannot be refunded automatically; reconciliation required", order["order_code"])
        await add_log(
            f"Order {order['order_code']} requires manual refund reconciliation",
            level="warning",
            module="poller",
        )
        return
    await add_log(
        f"Refund {format_vnd(amount)} for order {order['order_code']}: {reason}",
        level="warning",
        module="poller",
    )



def refund_transaction_description(reason: str) -> str:
    """Generate transaction description for refund."""
    return f"Hoàn tiền - {reason}"
