"""
bot/services/mbbank.py - Client goi MBBank transaction API (apicanhan.com).
Lay danh sach giao dich gan nhat de match voi don hang.
"""
from __future__ import annotations

import logging
import re
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


def _build_transactions_url(api_url: str, api_key: str, *, from_days: int | None = None) -> str:
    """Build the v3 transaction feed URL from base endpoint + API key."""
    base_url = api_url.rstrip("/")
    encoded_api_key = quote(api_key, safe="")
    suffix = "version=3" if from_days is None else f"fromDate={from_days}&version=3"
    return f"{base_url}/{encoded_api_key}/?{suffix}"


async def fetch_transactions(*, from_days: int | None = None) -> Optional[list[dict]]:
    """
    Goi MBBank v3 transaction API lay giao dich gan nhat.

    GET {api_url}/{api_key}/?version=3

    Returns: list cac giao dich loai "IN" voi format chuan:
        [{"transactionID": str, "amount": int, "description": str, "transactionDate": str}]

    Tra ve list rong neu khong co giao dich, None neu khong lay duoc feed.
    """
    if from_days is not None and (type(from_days) is not int or not 1 <= from_days <= 7):
        raise ValueError("invalid bank feed history window")
    config = await _get_mb_config()

    if not config["api_url"] or not config["api_key"]:
        logger.warning("MBBank scanner config chua day du; bo qua poll")
        return None

    request_url = _build_transactions_url(config["api_url"], config["api_key"], from_days=from_days)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                request_url,
                headers={"Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()

                if not isinstance(data, dict):
                    logger.error("MBBank API returned non-object payload")
                    return None

                if data.get("status") != "success":
                    logger.error("MBBank API reported an error")
                    return None

                transactions = data.get("transactions")
                if not isinstance(transactions, list):
                    logger.error("MBBank API returned invalid transactions payload")
                    return None

                result = []
                for tx in transactions:
                    if not isinstance(tx, dict):
                        logger.warning("Skipping malformed MBBank transaction entry")
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
        logger.error("MBBank HTTP error (%s)", type(e).__name__)
        return None
    except Exception as e:
        logger.error("MBBank unexpected error (%s)", type(e).__name__)
        return None


def _parse_amount(amount_str: str | int) -> int:
    """
    Parse amount tu string sang integer.
    MBBank API tra amount dang string, co the co dau phay hoac cham.
    Vi du: "3000" -> 3000, "1,000,000" -> 1000000
    """
    if type(amount_str) is int:
        return amount_str if 0 < amount_str <= 2**63 - 1 else 0
    if not isinstance(amount_str, str):
        logger.warning("Cannot parse bank amount")
        return 0
    cleaned = amount_str.replace(" ", "")
    if not re.fullmatch(r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+|[0-9]{1,3}(?:\.[0-9]{3})+)", cleaned):
        logger.warning("Cannot parse bank amount")
        return 0
    try:
        amount = int(cleaned.replace(",", "").replace(".", ""))
    except ValueError:
        return 0
    return amount if 0 < amount <= 2**63 - 1 else 0


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
