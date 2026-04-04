"""
bot/services/mbbank.py — Client gọi MBBank v3 API (apicanhan.com).
Lấy danh sách giao dịch gần nhất để match với đơn hàng.
"""
from __future__ import annotations

import logging
from typing import Optional

import aiohttp

from db.queries.settings import get_setting
from bot.config import settings as env_settings

logger = logging.getLogger(__name__)


async def _get_mb_config() -> dict[str, str]:
    """
    Lấy cấu hình MBBank — ưu tiên DB settings, fallback về .env.
    """
    return {
        "api_url": await get_setting("mb_api_url") or env_settings.mb_api_url,
        "api_key": await get_setting("mb_api_key") or env_settings.mb_api_key,
        "username": await get_setting("mb_username") or env_settings.mb_username,
        "password": await get_setting("mb_password") or env_settings.mb_password,
        "account_no": await get_setting("mb_account_no") or env_settings.mb_account_no,
    }


async def fetch_transactions() -> list[dict]:
    """
    Gọi MBBank v3 API lấy giao dịch gần nhất.

    GET {api_url}?key={api_key}&username={username}&password={password}&accountNo={account_no}

    Returns: list các giao dịch loại "IN" với format chuẩn:
        [{"transactionID": str, "amount": int, "description": str, "transactionDate": str}]

    Trả về list rỗng nếu lỗi hoặc không có giao dịch.
    """
    config = await _get_mb_config()

    # Kiểm tra config đầy đủ
    if not config["api_key"] or not config["username"] or not config["account_no"]:
        logger.warning("MBBank config chưa đầy đủ — bỏ qua poll")
        return []

    params = {
        "key": config["api_key"],
        "username": config["username"],
        "password": config["password"],
        "accountNo": config["account_no"],
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                config["api_url"],
                params=params,
                headers={"Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                data = await resp.json()

                if data.get("status") != "success":
                    logger.error(
                        "MBBank API error: %s",
                        data.get("message", "Unknown error"),
                    )
                    return []

                transactions = data.get("transactions", [])
                # Chỉ lấy giao dịch "IN" (tiền vào) và chuẩn hóa
                result = []
                for tx in transactions:
                    if tx.get("type") != "IN":
                        continue
                    result.append({
                        "transactionID": tx.get("transactionID", ""),
                        # amount là STRING từ API → convert sang INT
                        "amount": _parse_amount(tx.get("amount", "0")),
                        "description": tx.get("description", ""),
                        "transactionDate": tx.get("transactionDate", ""),
                    })

                logger.debug("MBBank: fetched %d IN transactions", len(result))
                return result

    except aiohttp.ClientError as e:
        logger.error("MBBank HTTP error: %s", e)
        return []
    except Exception as e:
        logger.error("MBBank unexpected error: %s", e)
        return []


def _parse_amount(amount_str: str) -> int:
    """
    Parse amount từ string sang integer.
    MBBank API trả amount dạng string, có thể có dấu phẩy hoặc chấm.
    Ví dụ: "3000" → 3000, "1,000,000" → 1000000
    """
    try:
        # Loại bỏ dấu phẩy, chấm, khoảng trắng
        cleaned = amount_str.replace(",", "").replace(".", "").replace(" ", "")
        return int(cleaned)
    except (ValueError, TypeError):
        logger.warning("Cannot parse amount: %s", amount_str)
        return 0


def extract_order_code(description: str) -> Optional[str]:
    """
    Trích xuất mã đơn hàng (ORDxxxxxxxx) từ nội dung chuyển khoản.
    Tìm pattern 'ORD' + 8 ký tự alphanumeric trong description.

    LƯU Ý: MBBank thường chèn khoảng trắng ngẫu nhiên vào nội dung CK,
    ví dụ: "ORDMSPXOCP 9" thay vì "ORDMSPXOCP9".
    → Loại bỏ tất cả khoảng trắng trước khi tìm.
    """
    import re
    # Loại bỏ khoảng trắng trước khi tìm pattern
    cleaned = description.upper().replace(" ", "")
    pattern = r"(ORD[A-Z0-9]{8})"
    match = re.search(pattern, cleaned)
    if match:
        return match.group(1)
    return None
