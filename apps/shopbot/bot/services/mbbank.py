"""
bot/services/mbbank.py - Client goi MBBank transaction API (apicanhan.com).
Lay danh sach giao dich gan nhat de match voi don hang.
"""
from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import quote

import aiohttp

from bot.config import settings as env_settings
from db.queries.settings import get_setting

logger = logging.getLogger(__name__)


async def _get_mb_config() -> dict[str, str]:
    """
    Lay cau hinh scanner MBBank, uu tien DB settings roi fallback ve .env.
    """
    return {
        "api_url": await get_setting("mb_api_url") or env_settings.mb_api_url,
        "api_key": await get_setting("mb_api_key") or env_settings.mb_api_key,
    }


def _build_transactions_url(api_url: str, api_key: str) -> str:
    """Build the v3 transaction feed URL from base endpoint + API key."""
    base_url = api_url.rstrip("/")
    encoded_api_key = quote(api_key, safe="")
    return f"{base_url}/{encoded_api_key}/?version=3"


async def fetch_transactions() -> list[dict]:
    """
    Goi MBBank v3 transaction API lay giao dich gan nhat.

    GET {api_url}/{api_key}/?version=3

    Returns: list cac giao dich loai "IN" voi format chuan:
        [{"transactionID": str, "amount": int, "description": str, "transactionDate": str}]

    Tra ve list rong neu loi hoac khong co giao dich.
    """
    config = await _get_mb_config()

    if not config["api_url"] or not config["api_key"]:
        logger.warning("MBBank scanner config chua day du; bo qua poll")
        return []

    request_url = _build_transactions_url(config["api_url"], config["api_key"])

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                request_url,
                headers={"Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                data = await resp.json()

                if not isinstance(data, dict):
                    logger.error("MBBank API returned non-object payload: %r", data)
                    return []

                if data.get("status") != "success":
                    logger.error(
                        "MBBank API error: %s",
                        data.get("message", "Unknown error"),
                    )
                    return []

                transactions = data.get("transactions", [])
                if not isinstance(transactions, list):
                    logger.error("MBBank API returned invalid transactions payload: %r", transactions)
                    return []

                result = []
                for tx in transactions:
                    if not isinstance(tx, dict):
                        logger.warning("Skipping malformed MBBank transaction entry: %r", tx)
                        continue
                    if tx.get("type") != "IN":
                        continue
                    result.append(
                        {
                            "transactionID": tx.get("transactionID", ""),
                            "amount": _parse_amount(tx.get("amount", "0")),
                            "description": tx.get("description", ""),
                            "transactionDate": tx.get("transactionDate", ""),
                        }
                    )

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
    Parse amount tu string sang integer.
    MBBank API tra amount dang string, co the co dau phay hoac cham.
    Vi du: "3000" -> 3000, "1,000,000" -> 1000000
    """
    try:
        cleaned = amount_str.replace(",", "").replace(".", "").replace(" ", "")
        return int(cleaned)
    except (ValueError, TypeError):
        logger.warning("Cannot parse amount: %s", amount_str)
        return 0


def extract_order_code(description: str) -> Optional[str]:
    """
    Trich xuat ma don hang (ORDxxxxxxxx) tu noi dung chuyen khoan.
    Tim pattern 'ORD' + 8 ky tu alphanumeric trong description.

    LUU Y: MBBank thuong chen khoang trang ngau nhien vao noi dung CK,
    vi du: "ORDMSPXOCP 9" thay vi "ORDMSPXOCP9".
    -> Loai bo tat ca khoang trang truoc khi tim.
    """
    import re

    cleaned = description.upper().replace(" ", "")
    pattern = r"(ORD[A-Z0-9]{8})"
    match = re.search(pattern, cleaned)
    if match:
        return match.group(1)
    return None
