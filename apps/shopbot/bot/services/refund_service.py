"""
bot/services/refund_service.py - Refund processing service.

Extracts refund logic from payment_poller.py for better modularity.
"""
from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot

from bot.services.admin_order_notifications import notify_admin_order_refunded
from bot.services.notifier import notify_user
from bot.services.spend_ledger import SpendLedgerService
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
    user_id = order["user_id"]
    new_balance = await refund_order_to_wallet(
        order["id"],
        reason=reason,
        tx_type="refund",
        description=refund_transaction_description(reason),
    )
    if new_balance is None:
        logger.warning("Order %s already refunded or missing, skipping", order["order_code"])
        return
    await SpendLedgerService.record_order_refund(order)

    await add_log(
        f"Refund {format_vnd(amount)} for order {order['order_code']}: {reason}",
        level="warning",
        module="poller",
    )

    await notify_user(
        user_id,
        refund_user_message(
            order_code=order["order_code"],
            amount=amount,
            new_balance=new_balance,
            reason=reason,
        ),
        bot=bot,
    )
    await notify_admin_order_refunded(order, bot=bot, reason=reason)


def refund_transaction_description(reason: str) -> str:
    """Generate transaction description for refund."""
    return f"Hoàn tiền - {reason}"


def refund_user_message(*, order_code: str, amount: int, new_balance: int, reason: str) -> str:
    """Generate refund notification message for user."""
    return (
        f"↩️ <b>Hoàn tiền đơn {order_code}</b>\n\n"
        f"💰 Số tiền hoàn: <b>{format_vnd(amount)}</b>\n"
        f"👛 Số dư mới: <b>{format_vnd(new_balance)}</b>\n"
        f"📝 Lý do: {reason}"
    )


def refund_admin_message(*, order_code: str, amount: int, reason: str) -> str:
    """Generate refund notification message for admin."""
    return (
        f"↩️ Refund order <b>{order_code}</b>\n"
        f"Amount: {format_vnd(amount)}\n"
        f"Reason: {reason}"
    )
