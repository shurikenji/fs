"""
bot/services/admin_order_notifications.py - Admin Telegram notifications for order events.
"""
from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any

from aiogram import Bot
from aiogram.types import BufferedInputFile

from bot.services.notifier import _resolve_bot, resolve_admin_chat_ids, send_text
from bot.utils.formatting import format_vnd, mask_api_key
from db.queries.admin_notifications import (
    create_admin_notification_event,
    mark_admin_notification_failed,
    mark_admin_notification_sent,
)
from db.queries.servers import get_server_by_id
from db.queries.settings import get_setting
from db.queries.users import get_user_by_id


Order = dict[str, Any]

EVENT_ORDER_COMPLETED = "order_completed"
EVENT_SERVICE_PAID = "service_paid"
EVENT_SERVICE_COMPLETED = "service_completed"
EVENT_ORDER_REFUNDED = "order_refunded"
_ADMIN_USER_INPUT_INLINE_LIMIT = 1200
_ADMIN_USER_INPUT_FILE_THRESHOLD = 1500

_EVENT_SETTING_KEYS = {
    EVENT_ORDER_COMPLETED: "admin_notify_order_completed",
    EVENT_SERVICE_PAID: "admin_notify_service_paid",
    EVENT_SERVICE_COMPLETED: "admin_notify_service_completed",
    EVENT_ORDER_REFUNDED: "admin_notify_order_refunded",
}

_PRODUCT_TYPE_LABELS = {
    "key_new": "Mua key mới",
    "key_topup": "Nạp key",
    "service_upgrade": "Đơn dịch vụ",
    "wallet_topup": "Nạp ví",
    "account_stocked": "Tài khoản có sẵn",
}


def _is_truthy(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _safe_text(value: Any) -> str:
    return escape(str(value or ""))


def _needs_user_input_file(value: Any) -> bool:
    return len(str(value or "")) > _ADMIN_USER_INPUT_FILE_THRESHOLD


def _user_input_summary_line(value: Any) -> str:
    raw_text = str(value or "")
    if not raw_text:
        return ""
    if _needs_user_input_file(raw_text):
        return "📝 Thông tin KH: <b>Quá dài, xem file TXT đính kèm</b>"
    preview = _safe_text(raw_text[:_ADMIN_USER_INPUT_INLINE_LIMIT])
    return f"📝 Thông tin KH: <code>{preview}</code>"


def _build_user_input_file_caption(order: Order) -> str:
    order_code = _safe_text(order.get("order_code") or "UNKNOWN")
    product_name = _safe_text(order.get("product_name") or "Dịch vụ")
    return f"📝 File thông tin khách hàng cho đơn <b>{order_code}</b>\n🛍️ <b>{product_name}</b>"


def _build_user_input_file(order: Order) -> BufferedInputFile | None:
    raw_text = str(order.get("user_input_data") or "")
    if not _needs_user_input_file(raw_text):
        return None

    order_code = str(order.get("order_code") or "order").strip() or "order"
    safe_code = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in order_code)
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    filename = f"{safe_code[:48]}-{timestamp}.txt"
    return BufferedInputFile(raw_text.encode("utf-8"), filename=filename)


async def _send_user_input_file(bot: Bot, chat_id: int, order: Order) -> bool:
    document = _build_user_input_file(order)
    if document is None:
        return True

    try:
        await bot.send_document(
            chat_id=chat_id,
            document=document,
            caption=_build_user_input_file_caption(order),
        )
        return True
    except Exception:
        return False


def _product_type_label(product_type: str | None) -> str:
    normalized = str(product_type or "").strip()
    return _PRODUCT_TYPE_LABELS.get(normalized, normalized or "Không rõ")


def _build_user_lines(user: dict | None) -> list[str]:
    if not user:
        return []

    display_name = (
        user.get("full_name")
        or user.get("username")
        or f"User #{user.get('id')}"
    )
    lines = [f"👤 Khách hàng: <b>{_safe_text(display_name)}</b>"]
    if user.get("username"):
        lines.append(f"🆔 Username: @{_safe_text(user['username'])}")
    if user.get("telegram_id"):
        lines.append(f"💬 <a href='tg://user?id={int(user['telegram_id'])}'>Nhắn khách hàng</a>")
    return lines


def _build_order_lines(order: Order, *, server_name: str | None, reason: str | None) -> list[str]:
    lines = [
        f"🧾 Mã đơn: <b>{_safe_text(order.get('order_code'))}</b>",
        f"📦 Loại: <b>{_safe_text(_product_type_label(order.get('product_type')))}</b>",
    ]

    if order.get("product_name"):
        lines.append(f"🛍️ Sản phẩm: <b>{_safe_text(order['product_name'])}</b>")
    if order.get("amount") is not None:
        lines.append(f"💰 Giá trị: <b>{format_vnd(int(order['amount'] or 0))}</b>")
    if order.get("payment_method"):
        lines.append(f"💳 Thanh toán: <b>{_safe_text(order['payment_method'])}</b>")
    if server_name:
        lines.append(f"🖥️ Server: <b>{_safe_text(server_name)}</b>")
    if order.get("api_key"):
        lines.append(f"🔑 Key: <code>{_safe_text(mask_api_key(str(order['api_key'])))}</code>")
    elif order.get("existing_key"):
        lines.append(f"🔑 Key: <code>{_safe_text(mask_api_key(str(order['existing_key'])))}</code>")
    if order.get("quota_before") is not None and order.get("quota_after") is not None:
        lines.append(
            f"📈 Quota: <b>{int(order['quota_before'] or 0):,}</b> → <b>{int(order['quota_after'] or 0):,}</b>"
        )
    if order.get("user_input_data"):
        lines.append(_user_input_summary_line(order["user_input_data"]))
    if reason:
        lines.append(f"📌 Lý do: {_safe_text(reason)}")
    return lines


def _build_message(
    *,
    order: Order,
    event_type: str,
    user: dict | None,
    server_name: str | None,
    reason: str | None,
) -> str:
    title_map = {
        EVENT_ORDER_COMPLETED: "✅ <b>Đơn hàng hoàn thành</b>",
        EVENT_SERVICE_PAID: "⏳ <b>Đơn dịch vụ cần xử lý</b>",
        EVENT_SERVICE_COMPLETED: "✅ <b>Đơn dịch vụ đã hoàn tất</b>",
        EVENT_ORDER_REFUNDED: "↩️ <b>Đơn hàng đã hoàn tiền</b>",
    }
    lines = [title_map.get(event_type, "🔔 <b>Cập nhật đơn hàng</b>")]
    lines.extend(_build_order_lines(order, server_name=server_name, reason=reason))
    lines.extend(_build_user_lines(user))
    return "\n".join(lines)


async def _is_event_enabled(event_type: str) -> bool:
    if not _is_truthy(await get_setting("admin_notify_enabled", "true"), default=True):
        return False
    setting_key = _EVENT_SETTING_KEYS.get(event_type)
    if not setting_key:
        return True
    return _is_truthy(await get_setting(setting_key, "true"), default=True)


async def notify_admin_order_event(
    *,
    order: Order,
    event_type: str,
    bot: Bot | None = None,
    reason: str | None = None,
) -> tuple[int, int, int]:
    """Send a deduplicated order-event notification to configured admins."""
    if not order.get("id"):
        return 0, 0, 0
    if not await _is_event_enabled(event_type):
        return 0, 0, 0

    admin_chat_ids = await resolve_admin_chat_ids()
    if not admin_chat_ids:
        return 0, 0, 0

    user = await get_user_by_id(int(order["user_id"])) if order.get("user_id") else None
    server = await get_server_by_id(int(order["server_id"])) if order.get("server_id") else None
    message = _build_message(
        order=order,
        event_type=event_type,
        user=user,
        server_name=server.get("name") if server else None,
        reason=reason,
    )

    sent = 0
    failed = 0
    skipped = 0
    async with _resolve_bot(bot) as active_bot:
        for chat_id in admin_chat_ids:
            queued = await create_admin_notification_event(
                order_id=int(order["id"]),
                event_type=event_type,
                target_chat_id=chat_id,
                message_text=message,
            )
            if not queued:
                skipped += 1
                continue

            if active_bot is None:
                failed += 1
                await mark_admin_notification_failed(
                    order_id=int(order["id"]),
                    event_type=event_type,
                    target_chat_id=chat_id,
                    error_message="bot_unavailable",
                )
                continue

            if await send_text(active_bot, chat_id, message):
                file_sent = await _send_user_input_file(active_bot, chat_id, order)
                if not file_sent:
                    failed += 1
                    await mark_admin_notification_failed(
                        order_id=int(order["id"]),
                        event_type=event_type,
                        target_chat_id=chat_id,
                        error_message="user_input_file_failed",
                    )
                    continue

                sent += 1
                await mark_admin_notification_sent(
                    order_id=int(order["id"]),
                    event_type=event_type,
                    target_chat_id=chat_id,
                )
                continue

            failed += 1
            await mark_admin_notification_failed(
                order_id=int(order["id"]),
                event_type=event_type,
                target_chat_id=chat_id,
                error_message="send_failed",
            )

    return sent, failed, skipped


async def notify_admin_order_completed(order: Order, *, bot: Bot | None = None) -> tuple[int, int, int]:
    if str(order.get("product_type") or "") == "service_upgrade":
        return 0, 0, 0
    return await notify_admin_order_event(order=order, event_type=EVENT_ORDER_COMPLETED, bot=bot)


async def notify_admin_service_paid(order: Order, *, bot: Bot | None = None) -> tuple[int, int, int]:
    return await notify_admin_order_event(order=order, event_type=EVENT_SERVICE_PAID, bot=bot)


async def notify_admin_service_completed(order: Order, *, bot: Bot | None = None) -> tuple[int, int, int]:
    return await notify_admin_order_event(order=order, event_type=EVENT_SERVICE_COMPLETED, bot=bot)


async def notify_admin_order_refunded(
    order: Order,
    *,
    bot: Bot | None = None,
    reason: str | None = None,
) -> tuple[int, int, int]:
    return await notify_admin_order_event(
        order=order,
        event_type=EVENT_ORDER_REFUNDED,
        bot=bot,
        reason=reason,
    )
