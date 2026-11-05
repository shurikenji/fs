"""
bot/services/payment_poller.py - Poll thanh toán và xử lý hoàn tất đơn hàng.
"""
from __future__ import annotations

import asyncio
import logging
import random
import string
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from aiogram import Bot

from bot.config import settings as env_settings
from bot.services.api_clients import get_api_client
from bot.services.admin_order_notifications import (
    notify_admin_order_completed,
    notify_admin_service_paid,
)
from bot.services.key_valuation import KeyValuationService, hash_api_key, normalize_api_key
from bot.services.mbbank import fetch_transactions
from bot.services.spend_ledger import SpendLedgerService
from bot.services.refund_service import refund_order
from bot.services.notifier import notify_user
from bot.utils.formatting import format_vnd, mask_api_key, quota_to_dollar
from bot.utils.time_utils import get_now_vn, to_gmt7
from db.queries.account_stocks import mark_account_sold
from db.queries.api_key_alerts import upsert_api_key_alert_state
from db.queries.logs import add_log
from db.queries.orders import (
    get_order_by_id,
    get_pending_qr_orders,
    expire_order,
    update_order_status,
)
from db.queries.products import get_product_by_id
from db.queries.servers import get_server_by_id
from db.queries.settings import get_setting, get_setting_int
from db.queries.user_keys import create_user_key
logger = logging.getLogger(__name__)

Order = dict[str, Any]
Processor = Callable[[Bot, Order], Awaitable[None]]
_CREATED_KEY_FIELDS = (
    "key",
    "api_key",
    "apiKey",
    "token",
    "access_token",
    "accessToken",
    "secret",
    "secret_key",
)


class _MaskedDeliveryDataError(RuntimeError):
    """Raised when upstream creates a token but only returns masked key data."""


def _quota_to_alert_dollar_value(quota: int, multiple: float) -> float:
    divisor = 500000 * (multiple if multiple > 0 else 1.0)
    return max(0.0, float(quota) / float(divisor))


async def _mark_key_alert_recovered_after_topup(
    *,
    order: Order,
    server: dict,
    api_key: str,
    remain_quota: int,
) -> None:
    normalized_key = normalize_api_key(api_key)
    multiple = float(server.get("quota_multiple") or 1.0)
    await upsert_api_key_alert_state(
        user_id=int(order["user_id"]),
        server_id=int(server["id"]),
        api_key_hash=hash_api_key(normalized_key),
        masked_key=mask_api_key(normalized_key),
        last_seen_remain_quota=int(remain_quota),
        last_seen_balance_dollar=_quota_to_alert_dollar_value(int(remain_quota), multiple),
        last_alert_threshold=None,
        last_error=None,
    )


async def start_payment_poller(bot: Bot) -> None:
    """Chạy vòng lặp poller thanh toán vô hạn."""
    logger.info("Payment poller started")
    await add_log("Payment poller started", module="poller")

    recovering = True
    while True:
        try:
            poll_interval = await get_setting_int("poll_interval", env_settings.poll_interval)
            succeeded = await _poll_cycle(bot, from_days=7 if recovering else None)
            recovering = not succeeded
            await asyncio.sleep(poll_interval)
        except asyncio.CancelledError:
            logger.info("Payment poller cancelled")
            break
        except Exception as exc:
            recovering = True
            logger.error("Poller error (%s)", type(exc).__name__)
            await add_log(f"Poller error ({type(exc).__name__})", level="error", module="poller")
            await asyncio.sleep(15)


async def _poll_cycle(bot: Bot, *, from_days: int | None = None) -> bool:
    """Chạy một chu kỳ poll: expire đơn, lấy giao dịch, xử lý match."""
    await _expire_old_orders(bot)
    from bot.services.bank_receipt_ingest import ingest_transactions, reconcile_unmatched_receipts

    account = str(await get_setting("mb_account_no") or env_settings.mb_account_no or "").strip()
    if not account or not account.isascii() or not account.isdecimal():
        logger.error("Bank account identity is missing or invalid; receipt ingest paused")
        return False
    verified = (
        account == env_settings.mb_verified_account_no.strip()
        and env_settings.mb_verified_feed_timezone == "Asia/Ho_Chi_Minh"
    )
    transactions = await _load_recent_transactions(from_days=from_days)
    if transactions is not None:
        await ingest_transactions(transactions, account_identity=account, account_verified=verified)
    if verified:
        await reconcile_unmatched_receipts(account_identity=account)
    return transactions is not None


async def _load_pending_qr_orders() -> list[Order]:
    """Tải danh sách đơn QR đang chờ thanh toán."""
    return await get_pending_qr_orders()


async def _load_recent_transactions(*, from_days: int | None = None) -> list[dict[str, Any]] | None:
    """Tải feed giao dịch mới nhất từ ngân hàng."""
    return await fetch_transactions(from_days=from_days)


async def _execute_order(bot: Bot, order: Order) -> None:
    """Run a previously claimed order using its selected processor."""
    order_code = order["order_code"]
    product_type = order["product_type"]

    processors: dict[str, Processor] = {
        "key_new": _process_key_new,
        "key_topup": _process_key_topup,
        "account_stocked": _process_account_stocked,
        "service_upgrade": _process_service_upgrade,
        "wallet_topup": _process_wallet_topup,
    }

    processor = processors.get(product_type)
    if processor is None:
        logger.error("Unknown product_type: %s for order %s", product_type, order_code)
        await _refund_order(bot, order, f"Loại sản phẩm không hợp lệ: {product_type}")
        return

    try:
        await processor(bot, order)
    except Exception as exc:
        logger.error("Process order %s failed (%s)", order_code, type(exc).__name__)
        await add_log(
            f"Process order {order_code} failed ({type(exc).__name__})",
            level="error",
            module="poller",
        )
        # shortcut: processing orders need manual reconciliation until durable fulfillment is implemented.
        logger.error("Order %s requires manual reconciliation; no automatic refund", order_code)


async def _process_service_upgrade(bot: Bot, order: Order) -> None:
    """Thông báo cho user và admin rằng đơn nâng cấp dịch vụ cần xử lý tay."""
    user_input = str(order.get("user_input_data") or "")
    if user_input:
        preview = user_input[:500]
        suffix = "…" if len(user_input) > 500 else ""
        input_line = f"\n📝 Thông tin KH: <code>{preview}{suffix}</code>"
    else:
        input_line = ""
    support_url = await get_setting("support_url", "https://t.me/admin")

    await notify_user(
        order["user_id"],
        (
            f"✅ Đơn <b>{order['order_code']}</b> đã thanh toán!\n"
            f"⏳ Admin đang xử lý đơn hàng của bạn.{input_line}\n\n"
            f"💬 Nếu cần hỗ trợ gấp hoặc trao đổi thông tin, vui lòng inbox Admin tại: {support_url}"
        ),
        bot=bot,
    )
    await notify_admin_service_paid(order, bot=bot)


def _order_quantity(order: Order) -> int:
    try:
        return max(1, int(order.get("quantity") or 1))
    except (TypeError, ValueError):
        return 1


async def _create_key_with_retry(
    client,
    *,
    server: dict,
    quota: int,
    group_name: str,
    base_token_name: str,
    sequence: int,
) -> tuple[str | None, int | None]:
    token_name = f"{base_token_name}_{sequence}"
    # shortcut: upstream failures are ambiguous; retry only after durable operation reconciliation exists.
    result = await client.create_token(
        server=server,
        quota=quota,
        group=group_name,
        name=token_name,
    )
    if result:
        api_key = _extract_created_key(result)
        token_id = client.extract_created_token_id(result)
        supports_lookup_by_id = client.supports_key_lookup_by_id(server)

        if not api_key:
            if token_id and supports_lookup_by_id:
                api_key = await client.resolve_token_key_by_id(server, token_id)

            if not api_key:
                if supports_lookup_by_id and not token_id:
                    logger.warning(
                        "Token %s created on %s without token_id in create response; falling back to search by name",
                        token_name,
                        server["name"],
                    )
                await asyncio.sleep(1)
                found = await client.search_token_by_name(server, token_name)
                if found:
                    api_key = _extract_created_key(found)
                    token_id = token_id or client.extract_created_token_id(found)
                    if not api_key and token_id and supports_lookup_by_id:
                        logger.info(
                            "Recovered token_id=%s for %s on %s from search results; retrying full key lookup by id",
                            token_id,
                            token_name,
                            server["name"],
                        )
                        api_key = await client.resolve_token_key_by_id(server, token_id)
        if api_key:
            return api_key, token_id
        logger.warning(
            "Token %s created on %s but upstream returned only masked/incomplete key data",
            token_name,
            server["name"],
        )
        raise _MaskedDeliveryDataError(token_name)
    return None, None

async def _process_key_new(bot: Bot, order: Order) -> None:
    """Tạo API key mới trên server được chọn."""
    server, product = await _load_key_order_context(order)
    if not server:
        await _refund_order(bot, order, "Server không tồn tại")
        return
    if not product and not order.get("custom_quota"):
        await _refund_order(bot, order, "Sản phẩm không tồn tại")
        return

    quantity = _order_quantity(order)
    token_batch_name = "key_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    quota = order.get("custom_quota") or (product["quota_amount"] if product else 0)
    if order.get("_fulfillment_claim") and (type(quota) is not int or not 0 < quota <= 2**63 - 1):
        raise ValueError("Invalid quota for key creation")
    group_name = (
        order.get("group_name")
        or (product.get("group_name") if product else "")
        or server.get("default_group")
        or ""
    )

    client = get_api_client(server)
    created_keys: list[str] = []
    created_token_ids: list[int | None] = []
    created_token_names: list[str] = []
    claim = order.get("_fulfillment_claim")
    for sequence in range(1, quantity + 1):
        current_token_name = f"{token_batch_name}_{sequence}"
        delivery = {
            "api_key": created_keys[0] if created_keys else None,
            "api_token_id": created_token_ids[0] if created_token_ids else None,
            "api_token_name": created_token_names[0] if created_token_names else current_token_name,
            "quota_after": quota,
            "delivery_info": "\n".join(created_keys) if created_keys else None,
            "delivery_token_names": "\n".join([*created_token_names, current_token_name]) if created_token_names else None,
        }
        operation_id = None
        if claim:
            from db.queries.fulfillment import begin_operation

            operation_id = await begin_operation(claim["id"], claim["lease_token"], sequence - 1, delivery=delivery)
            if operation_id is None:
                raise RuntimeError("Fulfillment operation already attempted or lease is invalid")
        else:
            await update_order_status(order["id"], "processing", **delivery)
        try:
            full_key, token_id = await _create_key_with_retry(
                client,
                server=server,
                quota=quota,
                group_name=group_name,
                base_token_name=token_batch_name,
                sequence=sequence,
            )
        except _MaskedDeliveryDataError as exc:
            failed_token_name = str(exc) if exc.args else current_token_name
            partial_token_names = [*created_token_names, failed_token_name]
            partial_delivery = "\n".join(created_keys) if created_keys else None
            if not claim:
                await update_order_status(
                    order["id"], "processing",
                    api_key=created_keys[0] if created_keys else None,
                    api_token_id=created_token_ids[0] if created_token_ids else None,
                    api_token_name=created_token_names[0] if created_token_names else failed_token_name,
                    quota_after=quota, delivery_info=partial_delivery,
                    delivery_token_names="\n".join(partial_token_names) if len(partial_token_names) > 1 else None,
                )
            await add_log(
                (
                    f"Order {order['order_code']} created token on {server['name']} "
                    "but upstream only returned masked key data; manual delivery required"
                ),
                level="error",
                module="poller",
            )
            if claim:
                return
            support_url = await get_setting("support_url", "https://t.me/admin")
            await notify_user(
                order["user_id"],
                (
                    f"⚠️ Đơn <b>{order['order_code']}</b> đã thanh toán nhưng hệ thống chưa lấy được "
                    "API key đầy đủ từ server để giao tự động.\n"
                    "Admin sẽ kiểm tra và bàn giao thủ công sớm nhất có thể.\n\n"
                    f"💬 Hỗ trợ: {support_url}"
                ),
                bot=bot,
            )
            return
        if not full_key:
            partial_delivery = "\n".join(created_keys)
            if not claim:
                await update_order_status(
                    order["id"], "processing",
                    api_key=created_keys[0] if created_keys else None,
                    api_token_id=created_token_ids[0] if created_token_ids else None,
                    api_token_name=created_token_names[0] if created_token_names else current_token_name,
                    quota_after=quota, delivery_info=partial_delivery,
                    delivery_token_names="\n".join([*created_token_names, current_token_name]) if created_token_names else None,
                )
            await add_log(
                f"Partial key batch for order {order['order_code']}: delivered {len(created_keys)}/{quantity}",
                level="error",
                module="poller",
            )
            if claim:
                return
            support_url = await get_setting("support_url", "https://t.me/admin")
            await notify_user(
                order["user_id"],
                (
                    f"⚠️ Đơn <b>{order['order_code']}</b> đã thanh toán nhưng hệ thống mới tạo được "
                    f"<b>{len(created_keys)}/{quantity}</b> key.\n"
                    f"Admin sẽ hoàn tất phần còn lại sớm nhất có thể.\n\n"
                    f"💬 Hỗ trợ: {support_url}"
                ),
                bot=bot,
            )
            return

        created_keys.append(full_key)
        created_token_names.append(current_token_name)
        created_token_ids.append(token_id)
        if claim:
            from db.queries.fulfillment import confirm_created_key

            if not await confirm_created_key(claim["id"], claim["lease_token"], operation_id, full_key, token_id, quota):
                raise RuntimeError("Fulfillment lease expired before operation confirmation")
        else:
            await create_user_key(
                user_id=order["user_id"],
                server_id=server["id"],
                api_key=full_key,
                api_token_id=token_id,
                label=mask_api_key(full_key),
            )
            try:
                await KeyValuationService.record_platform_quota_offset(
                    user_id=order["user_id"], server=server, api_key=full_key, quota_delta=quota,
                    resulting_total_quota=quota, source="platform_key_new",
                    source_ref=f"order:{order['id']}:seq:{sequence}",
                )
            except Exception as exc:
                logger.error("Platform key-new baseline sync failed for order %s: %s", order["order_code"], exc, exc_info=True)
                await add_log(f"Platform key-new baseline sync failed for order {order['order_code']}: {exc}", level="error", module="poller")

    delivery_info = "\n".join(created_keys) if quantity > 1 else None
    delivery = {
        "api_key": created_keys[0],
        "api_token_id": created_token_ids[0] if created_token_ids else None,
        "api_token_name": created_token_names[0] if created_token_names else None,
        "quota_after": quota,
        "delivery_info": delivery_info,
        "delivery_token_names": "\n".join(created_token_names) if len(created_token_names) > 1 else None,
    }
    if claim:
        from db.queries.fulfillment import complete_key_order

        if not await complete_key_order(claim["id"], claim["lease_token"], delivery):
            raise RuntimeError("Fulfillment lease or operation state is invalid for delivery")
    else:
        await update_order_status(order["id"], "completed", **delivery)
    if not claim:
        await SpendLedgerService.record_order_completion(order)
    await add_log(
        f"Key mới tạo cho order {order['order_code']}: {len(created_keys)} key(s)",
        module="poller",
    )
    if claim:
        return

    mult = server.get("quota_multiple", 1.0)
    dollar_str = quota_to_dollar(quota, mult)
    if quantity == 1:
        template = await get_setting(
            "msg_key_new",
            (
                "✅ Đơn {order_code} hoàn thành!\n\n"
                "🔑 API Key của bạn:\n{api_key}\n\n"
                "💵 Số dư: {dollar}\n"
                "🖥 Server: {server}\n\n"
                "⚠️ Vui lòng lưu key cẩn thận!"
            ),
        )
        message = template.format(
            order_code=f"<b>{order['order_code']}</b>",
            api_key=f"<code>{created_keys[0]}</code>",
            dollar=f"<b>{dollar_str}</b>",
            server=f"<b>{server['name']}</b>",
        )
    else:
        key_lines = [f"{index}. <code>{key}</code>" for index, key in enumerate(created_keys, start=1)]
        message = "\n".join(
            [
                f"✅ Đơn <b>{order['order_code']}</b> hoàn thành!",
                "",
                f"🔢 Số lượng key: <b>{quantity}</b>",
                f"💵 Mỗi key: <b>{dollar_str}</b>",
                f"🖥 Server: <b>{server['name']}</b>",
                "",
                "🔑 Danh sách API Key:",
                *key_lines,
                "",
                "⚠️ Vui lòng lưu key cẩn thận!",
            ]
        )
    await notify_user(order["user_id"], message, bot=bot)
    fresh_order = await get_order_by_id(order["id"])
    if fresh_order:
        await notify_admin_order_completed(fresh_order, bot=bot)


async def _process_key_topup(bot: Bot, order: Order) -> None:
    """Nạp thêm quota cho một API key hiện có."""
    if order.get("_fulfillment_claim"):
        # shortcut: upstream absolute quota updates are not safe with concurrent usage; reconcile manually until atomic delta exists.
        await add_log(
            f"Order {order['order_code']}: key topup requires manual reconciliation",
            level="warning",
            module="poller",
        )
        return
    server, product = await _load_key_order_context(order)
    if not server:
        await _refund_order(bot, order, "Server không tồn tại")
        return
    if not product and not order.get("custom_quota"):
        await _refund_order(bot, order, "Sản phẩm không tồn tại")
        return

    existing_key = order.get("existing_key", "")
    if not existing_key:
        await _refund_order(bot, order, "Không có key để nạp")
        return

    client = get_api_client(server)
    token_data = await client.search_token(server, existing_key)
    if not token_data:
        await _refund_order(bot, order, "Không tìm thấy key trên server")
        return

    token_id = token_data["id"]
    current_quota = token_data.get("remain_quota", 0)
    add_quota = order.get("custom_quota") or (product["quota_amount"] if product else 0)
    new_quota = current_quota + add_quota

    result = await client.update_token(
        server=server,
        token_id=token_id,
        new_quota=new_quota,
        current_data=token_data,
    )
    if not result:
        await add_log(
            f"Order {order['order_code']}: quota update result unknown; manual reconciliation required",
            level="error",
            module="poller",
        )
        return

    from db.queries.user_keys import upsert_user_key

    await upsert_user_key(
        user_id=order["user_id"],
        server_id=server["id"],
        api_key=existing_key,
        api_token_id=token_id,
        label=mask_api_key(existing_key),
    )
    try:
        await KeyValuationService.record_platform_quota_offset(
            user_id=order["user_id"],
            server=server,
            api_key=existing_key,
            quota_delta=add_quota,
            resulting_total_quota=new_quota,
            source="platform_key_topup",
            source_ref=f"order:{order['id']}",
        )
    except Exception as exc:
        logger.error(
            "Platform key-topup baseline sync failed for order %s: %s",
            order["order_code"],
            exc,
            exc_info=True,
        )
        await add_log(
            f"Platform key-topup baseline sync failed for order {order['order_code']}: {exc}",
            level="error",
            module="poller",
        )
    await update_order_status(
        order["id"],
        "completed",
        api_key=existing_key,
        api_token_id=token_id,
        quota_before=current_quota,
        quota_after=new_quota,
    )
    try:
        await _mark_key_alert_recovered_after_topup(
            order=order,
            server=server,
            api_key=existing_key,
            remain_quota=new_quota,
        )
    except Exception as exc:
        logger.error(
            "Key alert recovery sync failed for order %s: %s",
            order["order_code"],
            exc,
            exc_info=True,
        )
        await add_log(
            f"Key alert recovery sync failed for order {order['order_code']}: {exc}",
            level="error",
            module="poller",
        )
    await SpendLedgerService.record_order_completion(order)
    await add_log(
        (
            f"Topup key cho order {order['order_code']}: "
            f"{mask_api_key(existing_key)} quota {current_quota:,} -> {new_quota:,}"
        ),
        module="poller",
    )

    mult = server.get("quota_multiple", 1.0)
    template = await get_setting(
        "msg_key_topup",
        (
            "✅ Đơn {order_code} hoàn thành!\n\n"
            "🔑 Key: {api_key}\n"
            "💵 Số dư trước: {dollar_before}\n"
            "💵 Nạp thêm: +{dollar_added}\n"
            "💵 Số dư sau: {dollar_after}"
        ),
    )
    message = template.format(
        order_code=f"<b>{order['order_code']}</b>",
        api_key=f"<code>{mask_api_key(existing_key)}</code>",
        dollar_before=f"<b>{quota_to_dollar(current_quota, mult)}</b>",
        dollar_added=f"<b>{quota_to_dollar(add_quota, mult)}</b>",
        dollar_after=f"<b>{quota_to_dollar(new_quota, mult)}</b>",
    )
    await notify_user(order["user_id"], message, bot=bot)
    fresh_order = await get_order_by_id(order["id"])
    if fresh_order:
        await notify_admin_order_completed(fresh_order, bot=bot)


async def _process_account_stocked(bot: Bot, order: Order) -> None:
    """Giao một tài khoản đã được giữ chỗ cho người mua."""
    product_id = order.get("product_id")
    if not product_id:
        await _refund_order(bot, order, "Sản phẩm không hợp lệ")
        return

    from db.queries.account_stocks import get_reserved_accounts

    product = await get_product_by_id(product_id)
    quantity = _order_quantity(order)
    claim = order.get("_fulfillment_claim")
    if claim:
        from db.queries.fulfillment import complete_stock_order

        accounts = await complete_stock_order(claim["id"], claim["lease_token"])
    else:
        accounts = await get_reserved_accounts(order["id"])
    if accounts is None:
        logger.warning("Stock order %s requires reconciliation", order["order_code"])
        return
    if len(accounts) < quantity:
        await _refund_order(bot, order, "Tài khoản giữ chỗ không tồn tại (lỗi kho)")
        return

    raw_blocks: list[str] = []
    formatted_blocks: list[str] = []
    for index, account in enumerate(accounts[:quantity], start=1):
        if not claim:
            await mark_account_sold(
                account["id"], order["user_id"], order["id"], product_id=product_id,
            )
        raw_data = account["account_data"]
        formatted_data = _format_account_delivery(
            raw_data,
            product.get("format_template") if product else None,
        )
        raw_blocks.append(raw_data)
        if quantity > 1:
            formatted_blocks.append(f"#{index}\n{formatted_data}")
        else:
            formatted_blocks.append(formatted_data)

    delivery_info = "\n\n──────────\n\n".join(raw_blocks)
    if not claim:
        await update_order_status(order["id"], "completed", delivery_info=delivery_info)
    await add_log(f"Account delivered for order {order['order_code']} x{quantity}", module="poller")
    if claim:
        return

    delivery_text = "\n\n━━━━━━━━━━━━\n\n".join(formatted_blocks)
    if quantity > 1:
        message = (
            f"✅ Đơn <b>{order['order_code']}</b> hoàn thành!\n\n"
            f"🔢 Số lượng: <b>x{quantity}</b>\n\n"
            f"📦 Thông tin tài khoản:\n{delivery_text}\n\n"
            "⚠️ Vui lòng lưu thông tin cẩn thận!"
        )
    else:
        message = (
            f"✅ Đơn <b>{order['order_code']}</b> hoàn thành!\n\n"
            f"📦 Thông tin tài khoản:\n{delivery_text}\n\n"
            "⚠️ Vui lòng lưu thông tin cẩn thận!"
        )
    await notify_user(order["user_id"], message, bot=bot)
    fresh_order = await get_order_by_id(order["id"])
    if fresh_order:
        await notify_admin_order_completed(fresh_order, bot=bot)


async def _process_wallet_topup(bot: Bot, order: Order) -> None:
    """Nạp tiền vào ví nội bộ cho người dùng."""
    from db.queries.wallets import complete_wallet_topup_order

    amount = order["amount"]
    new_balance = await complete_wallet_topup_order(order["id"], claim=order.get("_fulfillment_claim"))
    if new_balance is None:
        raise RuntimeError("Không thể hoàn tất đơn nạp ví")

    await add_log(
        f"Wallet topup {format_vnd(amount)} for order {order['order_code']}",
        module="poller",
    )
    if order.get("_fulfillment_claim"):
        return

    template = await get_setting(
        "msg_wallet_topup",
        (
            "✅ Nạp ví thành công!\n\n"
            "💰 Số tiền: {amount}\n"
            "👛 Số dư mới: {balance}\n"
            "📋 Mã đơn: {order_code}"
        ),
    )
    message = template.format(
        order_code=f"<b>{order['order_code']}</b>",
        amount=f"<b>{format_vnd(amount)}</b>",
        balance=f"<b>{format_vnd(new_balance)}</b>",
    )
    await notify_user(order["user_id"], message, bot=bot)
    fresh_order = await get_order_by_id(order["id"])
    if fresh_order:
        await notify_admin_order_completed(fresh_order, bot=bot)


async def _refund_order(bot: Bot, order: Order, reason: str) -> None:
    """Hoàn tiền cho đơn một lần duy nhất rồi thông báo cho user và admin."""
    await refund_order(bot, order, reason)


def _expired_order_message(order_code: str) -> str:
    return f"⌛ Đơn <b>{order_code}</b> đã hết hạn.\nVui lòng tạo đơn mới nếu cần."


def _wallet_payment_error_message(exc: Exception) -> str:
    return f"❌ {exc}"


async def _expire_old_orders(bot: Bot) -> None:
    """Đánh dấu hết hạn cho các đơn QR đã quá thời gian chờ."""
    expire_minutes = await get_setting_int("order_expire_min", env_settings.order_expire_minutes)
    pending_orders = await _load_pending_qr_orders()
    now = get_now_vn()

    for order in pending_orders:
        created_str = order.get("created_at", "")
        if not created_str:
            continue

        created_at = to_gmt7(created_str)
        if created_at is None:
            continue

        if now - created_at <= timedelta(minutes=expire_minutes):
            continue

        if not await expire_order(order["id"]):
            continue
        await add_log(
            f"Order {order['order_code']} expired after {expire_minutes}min",
            module="poller",
        )
        await notify_user(
            order["user_id"],
            _expired_order_message(order["order_code"]),
            bot=bot,
        )


async def process_wallet_payment(bot: Bot, order_id: int) -> bool:
    """Thanh toán một đơn đang chờ bằng số dư ví của user."""
    from db.queries.wallets import charge_pending_order_from_wallet

    try:
        order = await charge_pending_order_from_wallet(order_id)
    except ValueError as exc:
        order = await get_order_by_id(order_id)
        if order:
            await notify_user(order["user_id"], _wallet_payment_error_message(exc), bot=bot)
        return False

    if not order:
        return False

    return True


async def _load_key_order_context(order: Order) -> tuple[Order | None, Order | None]:
    """Tải dữ liệu server và product cần cho các đơn liên quan đến key."""
    server = await get_server_by_id(order["server_id"]) if order.get("server_id") else None
    product = await get_product_by_id(order["product_id"]) if order.get("product_id") else None
    return server, product


def _extract_created_key(result: dict[str, Any]) -> str:
    """Lấy API key chưa bị mask từ response trực tiếp hoặc nested."""
    queue: list[Any] = [result]
    seen: set[int] = set()

    while queue:
        current = queue.pop(0)
        marker = id(current)
        if marker in seen:
            continue
        seen.add(marker)

        if isinstance(current, dict):
            for field in _CREATED_KEY_FIELDS:
                normalized = _normalize_created_key(current.get(field))
                if normalized:
                    return normalized
            for value in current.values():
                if isinstance(value, (dict, list, tuple)):
                    queue.append(value)
        elif isinstance(current, (list, tuple)):
            for item in current:
                if isinstance(item, (dict, list, tuple)):
                    queue.append(item)
    return ""


def _normalize_created_key(value: Any) -> str:
    """Normalize created-key payloads and reject masked/truncated variants."""
    if not isinstance(value, str):
        return ""

    normalized = value.strip()
    if not normalized or "*" in normalized or "..." in normalized:
        return ""
    if normalized.startswith("sk-"):
        return normalized
    return f"sk-{normalized}"


def _format_account_delivery(raw_data: str, format_template: str | None) -> str:
    """Định dạng dữ liệu tài khoản bằng template phân tách bằng dấu `|`."""
    if not format_template or "|" not in raw_data:
        return f"<code>{raw_data}</code>"

    labels = [label.strip() for label in format_template.split("|")]
    values = [value.strip() for value in raw_data.split("|")]
    lines = []
    for index, label in enumerate(labels):
        value = values[index] if index < len(values) else "-"
        lines.append(f"  {label}: <code>{value}</code>")
    return "\n".join(lines)


