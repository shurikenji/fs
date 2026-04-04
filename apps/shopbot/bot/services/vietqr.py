"""
bot/services/vietqr.py — Tạo VietQR Quick Link URL + caption.
Dùng VietQR public API (không cần API key).
"""
from __future__ import annotations

import logging
from urllib.parse import quote

from db.queries.settings import get_setting
from bot.config import settings as env_settings
from bot.utils.formatting import format_vnd

logger = logging.getLogger(__name__)


async def build_qr_url(
    amount: int,
    order_code: str,
) -> str:
    """
    Tạo VietQR Quick Link URL.

    Format:
    https://img.vietqr.io/image/{BANK_ID}-{ACCOUNT_NO}-{TEMPLATE}.png
        ?amount={AMOUNT}&addInfo={DESCRIPTION}&accountName={ACCOUNT_NAME}

    addInfo: tối đa 50 ký tự, không dấu, không ký tự đặc biệt.
    """
    # Lấy config từ DB, fallback .env
    bank_id = await get_setting("mb_bank_id") or env_settings.mb_bank_id
    account_no = await get_setting("mb_account_no") or env_settings.mb_account_no
    account_name = await get_setting("mb_account_name") or env_settings.mb_account_name
    template = await get_setting("vietqr_template") or "compact2"

    # addInfo chỉ dùng mã đơn (đảm bảo không dấu, không ký tự đặc biệt)
    add_info = order_code

    url = (
        f"https://img.vietqr.io/image/{bank_id}-{account_no}-{template}.png"
        f"?amount={amount}"
        f"&addInfo={quote(add_info)}"
        f"&accountName={quote(account_name)}"
    )

    logger.debug("VietQR URL: %s", url)
    return url


async def build_qr_caption(
    amount: int,
    order_code: str,
    expire_minutes: int = 30,
) -> str:
    """
    Tạo caption cho QR image gửi trong Telegram.
    Bao gồm: số tiền, nội dung CK, STK, tên TK, thời gian hết hạn.
    """
    account_no = await get_setting("mb_account_no") or env_settings.mb_account_no
    account_name = await get_setting("mb_account_name") or env_settings.mb_account_name
    bank_id = await get_setting("mb_bank_id") or env_settings.mb_bank_id

    caption = (
        f"🏦 <b>THANH TOÁN CHUYỂN KHOẢN</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Số tiền: <b>{format_vnd(amount)}</b>\n"
        f"📝 Nội dung CK: <code>{order_code}</code>\n"
        f"🏧 Ngân hàng: <b>{bank_id}</b>\n"
        f"💳 STK: <code>{account_no}</code>\n"
        f"👤 Chủ TK: <b>{account_name}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ Đơn hết hạn sau <b>{expire_minutes} phút</b>\n"
        f"⚠️ Vui lòng chuyển <b>đúng số tiền</b> và <b>đúng nội dung</b>"
    )

    return caption
