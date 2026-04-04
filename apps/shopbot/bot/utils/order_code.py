"""
bot/utils/order_code.py — Tạo mã đơn hàng unique.
Format: ORD + 8 ký tự chữ hoa + số (vd: ORD1A2B3C4D).
"""
from __future__ import annotations

import random
import string


def generate_order_code() -> str:
    """Tạo mã đơn hàng ORD + 8 ký tự ngẫu nhiên (uppercase + digits)."""
    chars = string.ascii_uppercase + string.digits
    suffix = "".join(random.choices(chars, k=8))
    return f"ORD{suffix}"
