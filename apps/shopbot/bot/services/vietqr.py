"""Tạo ảnh VietQR offline bằng vietqr-node + caption thanh toán."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram.types import BufferedInputFile

from db.queries.settings import get_setting
from bot.config import settings as env_settings
from bot.utils.formatting import format_vnd

logger = logging.getLogger(__name__)
NODE_HELPER = Path(__file__).with_name("vietqr_node.cjs")


async def build_qr_photo(
    amount: int,
    order_code: str,
) -> BufferedInputFile:
    """Render VietQR PNG locally through the bundled Node helper."""
    bank_id = await get_setting("mb_bank_id") or env_settings.mb_bank_id
    account_no = await get_setting("mb_account_no") or env_settings.mb_account_no
    account_name = await get_setting("mb_account_name") or env_settings.mb_account_name
    template = await get_setting("vietqr_template") or "compact"

    process = await asyncio.create_subprocess_exec(
        "node",
        str(NODE_HELPER),
        str(bank_id),
        str(account_no),
        str(account_name),
        str(int(amount)),
        str(order_code),
        str(template),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        png, stderr = await asyncio.wait_for(process.communicate(), timeout=20)
    except TimeoutError:
        process.kill()
        await process.communicate()
        raise RuntimeError("VietQR render timed out") from None

    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"VietQR render failed: {detail or 'unknown error'}")
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError("VietQR renderer did not return a PNG image")
    if len(png) > 5 * 1024 * 1024:
        raise RuntimeError("VietQR image is larger than 5 MiB")

    return BufferedInputFile(png, filename="payment-qr.png")


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
