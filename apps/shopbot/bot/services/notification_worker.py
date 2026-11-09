"""Deliver persisted order notifications separately from financial operations."""
from __future__ import annotations

import logging
import asyncio
from html import escape

from bot.services.admin_order_notifications import notify_admin_order_completed, notify_admin_order_refunded, notify_admin_service_completed, notify_admin_service_paid
from bot.services.notifier import notify_admins, notify_user
from bot.utils.formatting import format_vnd
from db.queries.notification_outbox import claim_notification, finish_notification
from db.queries.orders import get_order_by_id

logger = logging.getLogger(__name__)


async def run_one_notification(bot) -> bool:
    event = await claim_notification()
    if event is None:
        return False
    succeeded = False
    try:
        order = await get_order_by_id(event["order_id"])
        if not order:
            raise ValueError("order unavailable")
        if event["event_type"] in {"user_order_refunded", "admin_order_refunded"}:
            if order["status"] != "refunded" or order.get("is_refunded") != 1:
                raise ValueError("refunded order unavailable")
            if event["event_type"] == "user_order_refunded":
                if order["user_id"] != event["user_id"]:
                    raise ValueError("notification user mismatch")
                succeeded = await notify_user(
                    order["user_id"],
                    f"↩️ Đơn <b>{escape(order['order_code'])}</b> đã được hoàn <b>{format_vnd(order['amount'])}</b> vào ví.",
                    bot=bot,
                )
            else:
                _, failed, _ = await notify_admin_order_refunded(order, bot=bot, reason=order.get("refund_reason"))
                succeeded = failed == 0
        elif event["event_type"] in {"user_order_review", "admin_order_review"}:
            if order["status"] in {"completed", "refunded"}:
                succeeded = True
            elif event["event_type"] == "user_order_review":
                if order["user_id"] != event["user_id"]:
                    raise ValueError("notification user mismatch")
                succeeded = await notify_user(
                    order["user_id"],
                    f"⏳ Đơn <b>{escape(order['order_code'])}</b> đang được kiểm tra. Admin sẽ liên hệ khi có kết quả.",
                    bot=bot,
                )
            else:
                sent, failed = await notify_admins(
                    f"⚠️ Đơn <b>{escape(order['order_code'])}</b> cần đối soát trước khi tiếp tục xử lý.", bot=bot,
                )
                succeeded = sent > 0 and failed == 0
        elif event["event_type"] in {"user_service_paid", "admin_service_paid"}:
            if order["product_type"] != "service_upgrade":
                raise ValueError("notification order type mismatch")
            if order["status"] == "completed":
                succeeded = True
            elif order["status"] != "processing":
                raise ValueError("service order is not processing")
            elif event["event_type"] == "user_service_paid":
                if order["user_id"] != event["user_id"]:
                    raise ValueError("notification user mismatch")
                succeeded = await notify_user(
                    order["user_id"],
                    f"✅ Đơn <b>{escape(order['order_code'])}</b> đã thanh toán. Admin đang xử lý đơn hàng của bạn.",
                    bot=bot,
                )
            else:
                _, failed, _ = await notify_admin_service_paid(order, bot=bot)
                succeeded = failed == 0
        elif event["event_type"] in {"user_service_completed", "admin_service_completed"}:
            if order["status"] != "completed" or order["product_type"] != "service_upgrade":
                raise ValueError("completed service order unavailable")
            if event["event_type"] == "user_service_completed":
                if order["user_id"] != event["user_id"]:
                    raise ValueError("notification user mismatch")
                succeeded = await notify_user(
                    order["user_id"],
                    f"✅ Đơn dịch vụ <b>{escape(order['order_code'])}</b> đã được admin xử lý hoàn tất.",
                    bot=bot,
                )
            else:
                _, failed, _ = await notify_admin_service_completed(order, bot=bot)
                succeeded = failed == 0
        elif order["status"] != "completed":
            raise ValueError("completed order unavailable")
        elif event["event_type"] == "user_order_completed":
            if order["user_id"] != event["user_id"]:
                raise ValueError("notification user mismatch")
            message = f"✅ Đơn <b>{escape(order['order_code'])}</b> đã hoàn tất."
            if order["product_type"] in {"key_new", "account_stocked"}:
                delivery = order.get("delivery_info") or order.get("api_key")
                if not delivery:
                    raise ValueError("delivery is unavailable")
                message += f"\n\n📦 Thông tin giao hàng:\n{escape(str(delivery))}"
            elif order["product_type"] == "wallet_topup":
                message += f"\n💰 Đã nạp: <b>{format_vnd(order['amount'])}</b>"
            elif order["product_type"] == "key_topup":
                message += "\n🔑 Key của bạn đã được nạp quota."
            else:
                raise ValueError("unsupported notification type")
            succeeded = await notify_user(order["user_id"], message, bot=bot)
        elif event["event_type"] == "admin_order_completed":
            _, failed, _ = await notify_admin_order_completed(order, bot=bot)
            succeeded = failed == 0
        else:
            raise ValueError("unsupported notification event")
    except Exception as exc:
        logger.error("Notification event %s failed (%s)", event["id"], type(exc).__name__)
    await finish_notification(event["id"], event["lease_token"], succeeded=succeeded)
    return True


async def start_notification_worker(bot) -> None:
    while True:
        try:
            worked = await run_one_notification(bot)
            if not worked:
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Notification worker failure (%s)", type(exc).__name__)
            await asyncio.sleep(5)
