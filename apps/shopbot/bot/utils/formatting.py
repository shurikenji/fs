"""
Display helpers for bot and admin messages.
"""
from __future__ import annotations

from bot.utils.time_utils import to_gmt7


def format_vnd(amount: int) -> str:
    """Format VND values with dot separators."""
    sign = "-" if amount < 0 else ""
    formatted = f"{abs(amount):,}".replace(",", ".")
    return f"{sign}{formatted}₫"


def format_quota(quota: int) -> str:
    """Format quota values for display."""
    return f"{quota:,}"


def format_dollar(amount: float) -> str:
    """Format dollar amount."""
    return f"${amount:,.2f}"


def quota_to_dollar(quota: int, multiple: float = 1.0) -> str:
    """Convert quota to a dollar string."""
    if multiple <= 0:
        multiple = 1.0
    dollar = quota / 500000 / multiple
    return f"${dollar:,.2f}"


def mask_api_key(key: str) -> str:
    """Mask API key while keeping a small visible prefix/suffix."""
    if len(key) <= 12:
        return key
    return f"{key[:8]}...{key[-4:]}"


def status_emoji(status: str) -> str:
    """Return an emoji for order status."""
    mapping = {
        "pending": "⏳",
        "paid": "💰",
        "processing": "⚙️",
        "completed": "✅",
        "failed": "❌",
        "expired": "⌛",
        "refunded": "↩️",
        "cancelled": "🚫",
    }
    return mapping.get(status, "❓")


def status_text_vi(status: str) -> str:
    """Return the Vietnamese label for order status."""
    mapping = {
        "pending": "Chờ thanh toán",
        "paid": "Đã thanh toán",
        "processing": "Đang xử lý",
        "completed": "Hoàn thành",
        "failed": "Thất bại",
        "expired": "Hết hạn",
        "refunded": "Đã hoàn tiền",
        "cancelled": "Đã hủy",
    }
    return mapping.get(status, status)


def payment_method_text(method: str) -> str:
    """Return the Vietnamese label for payment methods."""
    mapping = {
        "qr": "🏦 Chuyển khoản QR",
        "wallet": "👛 Ví nội bộ",
    }
    return mapping.get(method, method)


def truncate_text(text: str, max_len: int = 50) -> str:
    """Truncate long text."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def format_time_vn(time_value: str) -> str:
    """Normalize legacy UTC/local timestamps and render them in GMT+7."""
    if not time_value:
        return ""

    normalized = to_gmt7(time_value)
    if normalized is None:
        return str(time_value)[:19]
    return normalized.strftime("%Y-%m-%d %H:%M:%S")
