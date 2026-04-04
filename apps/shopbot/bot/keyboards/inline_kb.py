"""
bot/keyboards/inline_kb.py — Tất cả inline keyboard builders.
Mỗi hàm trả về InlineKeyboardMarkup sẵn sàng gửi.
"""
from __future__ import annotations

import math
from typing import Sequence

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.callback_data.factories import (
    CategoryPageCB,
    CategorySelectCB,
    KeyActionCB,
    ServerSelectCB,
    ProductPageCB,
    ProductSelectCB,
    QuantityAdjustCB,
    QuantityBackCB,
    QuantityConfirmCB,
    PaymentMethodCB,
    OrderCancelCB,
    MyKeySelectCB,
    MyKeysPageCB,
    MyKeySearchCB,
    MyKeyInputCB,
    CustomAmountCB,
    WalletActionCB,
    WalletTopupAmountCB,
    OrderListPageCB,
    OrderDetailCB,
    BackCB,
    BackServersCB,
)
from bot.utils.formatting import format_vnd
from bot.keyboards.pagination import build_pagination_buttons


# ── Helpers ─────────────────────────────────────────────────────────────────

def _paginate(items: Sequence, page: int, per_page: int) -> tuple[list, int]:
    """Trả về (items trang hiện tại, tổng số trang)."""
    total_pages = max(1, math.ceil(len(items) / per_page))
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    return list(items[start : start + per_page]), total_pages


def _pack_callback_data(value: str | object) -> str:
    """Cho phép truyền target ngắn hoặc callback object đầy đủ context."""
    if isinstance(value, str):
        return BackCB(target=value).pack()
    if hasattr(value, "pack"):
        return value.pack()
    return str(value)


def _format_key_label(key_row: dict) -> str:
    """Trả về nhãn key ngắn gọn, an toàn cho inline button."""
    label = key_row.get("label") or key_row.get("api_key", "")
    if len(label) > 20:
        return f"{label[:8]}...{label[-4:]}"
    return str(label)


def _build_my_keys_compact_pager(
    *,
    page: int,
    total_pages: int,
    server_id: int,
    cat_id: int,
) -> list[InlineKeyboardButton]:
    """Pager compact riêng cho màn xem tất cả key đã lưu."""
    is_first_page = page <= 0
    is_last_page = page >= total_pages - 1

    return [
        InlineKeyboardButton(
            text="·" if is_first_page else "◀️",
            callback_data="noop" if is_first_page else MyKeysPageCB(
                server_id=server_id,
                cat_id=cat_id,
                page=page - 1,
            ).pack(),
        ),
        InlineKeyboardButton(
            text=f"{page + 1}/{total_pages}",
            callback_data="noop",
        ),
        InlineKeyboardButton(
            text="·" if is_last_page else "▶️",
            callback_data="noop" if is_last_page else MyKeysPageCB(
                server_id=server_id,
                cat_id=cat_id,
                page=page + 1,
            ).pack(),
        ),
    ]


# ── Danh mục ────────────────────────────────────────────────────────────────

def categories_kb(
    categories: Sequence[dict],
    page: int = 0,
    per_page: int = 6,
) -> InlineKeyboardMarkup:
    """Inline keyboard danh mục có phân trang."""
    page_items, total_pages = _paginate(categories, page, per_page)

    builder = InlineKeyboardBuilder()
    for cat in page_items:
        icon = cat.get("icon", "📦")
        name = cat.get("name", "")
        builder.button(
            text=f"{icon} {name}",
            callback_data=CategorySelectCB(id=cat["id"]),
        )
    builder.adjust(1)  # Đổi thành 1 cột để hiển thị tên dài tốt hơn

    # Pagination
    if total_pages > 1:
        builder.row(*build_pagination_buttons(
            page=page,
            total_pages=total_pages,
            prev_callback=CategoryPageCB(page=page - 1).pack(),
            next_callback=CategoryPageCB(page=page + 1).pack(),
        ).inline_keyboard[0])

    return builder.as_markup()


# ── Key API sub-menu ────────────────────────────────────────────────────────

def key_action_kb(cat_id: int) -> InlineKeyboardMarkup:
    """Inline keyboard: Mua key mới / Nạp key cũ."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🔑 Mua key mới",
        callback_data=KeyActionCB(cat_id=cat_id, action="new"),
    )
    builder.button(
        text="💳 Nạp key cũ",
        callback_data=KeyActionCB(cat_id=cat_id, action="topup"),
    )
    builder.button(
        text="⬅️ Quay lại",
        callback_data=BackCB(target="cat"),
    )
    builder.adjust(2, 1)
    return builder.as_markup()


# ── Server selection ────────────────────────────────────────────────────────

def servers_kb(
    servers: Sequence[dict],
    cat_id: int,
    action: str,
) -> InlineKeyboardMarkup:
    """Inline keyboard chọn server."""
    builder = InlineKeyboardBuilder()
    for srv in servers:
        dollar_per_unit = srv.get("dollar_per_unit", 10.0)
        if dollar_per_unit <= 0: dollar_per_unit = 10.0
        price_per_dollar = int(srv["price_per_unit"] / dollar_per_unit)
        price = format_vnd(price_per_dollar)
        
        builder.button(
            text=f"🖥 {srv['name']} ({price}/$)",
            callback_data=ServerSelectCB(cat_id=cat_id, action=action, server_id=srv["id"]),
        )
    builder.button(
        text="⬅️ Quay lại",
        callback_data=BackCB(target="cat"),
    )
    builder.adjust(1)
    return builder.as_markup()


# ── Products (gói) ──────────────────────────────────────────────────────────

def products_kb(
    products: Sequence[dict],
    cat_id: int,
    srv_id: int,
    ptype: str,
    page: int = 0,
    per_page: int = 6,
    action: str = "new",
) -> InlineKeyboardMarkup:
    """Inline keyboard danh sách sản phẩm/gói có phân trang."""
    page_items, total_pages = _paginate(products, page, per_page)

    builder = InlineKeyboardBuilder()
    for prod in page_items:
        price = format_vnd(prod["price_vnd"])
        stock_text = ""
        if prod.get("stock", -1) != -1:
            stock_text = f" [Còn {prod['stock']}]"
            
        builder.button(
            text=f"{prod['name']} — {price}{stock_text}",
            callback_data=ProductSelectCB(product_id=prod["id"]),
        )
    builder.adjust(1)

    # Nút nhập số $ tùy chọn (chỉ cho key_new / key_topup)
    if ptype in ("key_new", "key_topup") and srv_id > 0:
        builder.row(
            InlineKeyboardButton(
                text="✏️ Nhập số $ tùy chọn",
                callback_data=CustomAmountCB(
                    cat_id=cat_id, action=action, server_id=srv_id
                ).pack(),
            )
        )

    # Pagination
    if total_pages > 1:
        builder.row(*build_pagination_buttons(
            page=page,
            total_pages=total_pages,
            prev_callback=ProductPageCB(cat_id=cat_id, srv_id=srv_id, ptype=ptype, page=page - 1).pack(),
            next_callback=ProductPageCB(cat_id=cat_id, srv_id=srv_id, ptype=ptype, page=page + 1).pack(),
        ).inline_keyboard[0])

    # Back
    back_target = "srv" if srv_id > 0 else "cat"
    builder.row(
        InlineKeyboardButton(
            text="⬅️ Quay lại",
            callback_data=(
                BackServersCB(cat_id=cat_id, action=action).pack()
                if back_target == "srv"
                else BackCB(target=back_target).pack()
            ),
        )
    )
    return builder.as_markup()


def quantity_picker_kb(
    *,
    product_id: int,
    quantity: int,
    max_quantity: int,
) -> InlineKeyboardMarkup:
    """Inline keyboard chọn số lượng cho 1 SKU."""
    builder = InlineKeyboardBuilder()
    previous_qty = max(1, quantity - 1)
    next_qty = min(max_quantity, quantity + 1)

    builder.row(
        InlineKeyboardButton(
            text="➖",
            callback_data=QuantityAdjustCB(product_id=product_id, qty=previous_qty).pack(),
        ),
        InlineKeyboardButton(text=f"x{quantity}", callback_data="noop"),
        InlineKeyboardButton(
            text="➕",
            callback_data=QuantityAdjustCB(product_id=product_id, qty=next_qty).pack(),
        ),
    )

    quick_values = []
    for value in (1, 2, 3, 5, 10):
        if 1 <= value <= max_quantity and value not in quick_values:
            quick_values.append(value)
    if max_quantity not in quick_values:
        quick_values.append(max_quantity)

    if len(quick_values) > 1:
        builder.row(
            *[
                InlineKeyboardButton(
                    text=f"x{value}",
                    callback_data=QuantityAdjustCB(product_id=product_id, qty=value).pack(),
                )
                for value in quick_values
            ]
        )

    builder.row(
        InlineKeyboardButton(
            text="✅ Tiếp tục thanh toán",
            callback_data=QuantityConfirmCB(product_id=product_id, qty=quantity).pack(),
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="⬅️ Quay lại",
            callback_data=QuantityBackCB(product_id=product_id).pack(),
        )
    )
    return builder.as_markup()


# ── Payment method ──────────────────────────────────────────────────────────

def payment_method_kb(order_id: int, show_qr: bool = True) -> InlineKeyboardMarkup:
    """Inline keyboard chọn phương thức thanh toán."""
    builder = InlineKeyboardBuilder()
    if show_qr:
        builder.button(
            text="🏦 Chuyển khoản QR",
            callback_data=PaymentMethodCB(order_id=order_id, method="qr"),
        )
    builder.button(
        text="👛 Thanh toán bằng ví",
        callback_data=PaymentMethodCB(order_id=order_id, method="wallet"),
    )
    builder.button(
        text="❌ Hủy đơn",
        callback_data=OrderCancelCB(order_id=order_id),
    )
    if show_qr:
        builder.adjust(2, 1)
    else:
        builder.adjust(1, 1)
    return builder.as_markup()


# ── My keys (chọn key để topup) ────────────────────────────────────────────

def my_keys_kb(
    keys: Sequence[dict],
    server_id: int,
    cat_id: int,
    *,
    total_count: int | None = None,
) -> InlineKeyboardMarkup:
    """Inline keyboard key gần đây cho luồng topup."""
    builder = InlineKeyboardBuilder()
    for key_row in keys:
        builder.button(
            text=f"🔑 {_format_key_label(key_row)}",
            callback_data=MyKeySelectCB(key_id=key_row["id"]),
        )
    if total_count and total_count > len(keys):
        builder.button(
            text=f"📚 Xem tất cả ({total_count})",
            callback_data=MyKeysPageCB(server_id=server_id, cat_id=cat_id, page=0),
        )
    if total_count:
        builder.button(
            text="🔎 Tìm key",
            callback_data=MyKeySearchCB(server_id=server_id, cat_id=cat_id),
        )
    builder.button(
        text="✏️ Dán key khác",
        callback_data=MyKeyInputCB(server_id=server_id, cat_id=cat_id),
    )
    builder.button(
        text="⬅️ Quay lại",
        callback_data=BackServersCB(cat_id=cat_id, action="topup"),
    )
    builder.adjust(1)
    return builder.as_markup()


def my_keys_all_kb(
    keys: Sequence[dict],
    *,
    server_id: int,
    cat_id: int,
    page: int = 0,
    per_page: int = 6,
) -> InlineKeyboardMarkup:
    """Inline keyboard toàn bộ key đã lưu, có phân trang."""
    page_items, total_pages = _paginate(keys, page, per_page)
    current_page = max(0, min(page, total_pages - 1))
    builder = InlineKeyboardBuilder()
    for key_row in page_items:
        builder.button(
            text=f"🔑 {_format_key_label(key_row)}",
            callback_data=MyKeySelectCB(key_id=key_row["id"]),
        )
    builder.adjust(1)

    if total_pages > 1:
        builder.row(*_build_my_keys_compact_pager(
            page=current_page,
            total_pages=total_pages,
            server_id=server_id,
            cat_id=cat_id,
        ))

    builder.row(
        InlineKeyboardButton(
            text="🔎 Tìm key",
            callback_data=MyKeySearchCB(server_id=server_id, cat_id=cat_id).pack(),
        ),
        InlineKeyboardButton(
            text="✏️ Dán key khác",
            callback_data=MyKeyInputCB(server_id=server_id, cat_id=cat_id).pack(),
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="⬅️ Quay lại",
            callback_data=BackServersCB(cat_id=cat_id, action="topup").pack(),
        )
    )
    return builder.as_markup()


def my_key_search_results_kb(
    keys: Sequence[dict],
    *,
    server_id: int,
    cat_id: int,
    total_count: int | None = None,
) -> InlineKeyboardMarkup:
    """Inline keyboard kết quả tìm key đã lưu."""
    builder = InlineKeyboardBuilder()
    for key_row in keys:
        builder.button(
            text=f"🔑 {_format_key_label(key_row)}",
            callback_data=MyKeySelectCB(key_id=key_row["id"]),
        )
    if total_count:
        builder.button(
            text=f"📚 Xem tất cả ({total_count})",
            callback_data=MyKeysPageCB(server_id=server_id, cat_id=cat_id, page=0),
        )
    builder.button(
        text="🔎 Tìm lại",
        callback_data=MyKeySearchCB(server_id=server_id, cat_id=cat_id),
    )
    builder.button(
        text="✏️ Dán key khác",
        callback_data=MyKeyInputCB(server_id=server_id, cat_id=cat_id),
    )
    builder.button(
        text="⬅️ Quay lại",
        callback_data=BackServersCB(cat_id=cat_id, action="topup"),
    )
    builder.adjust(1)
    return builder.as_markup()


# ── Wallet ──────────────────────────────────────────────────────────────────

def wallet_menu_kb() -> InlineKeyboardMarkup:
    """Inline keyboard ví: nạp tiền / lịch sử."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="💰 Nạp tiền",
        callback_data=WalletActionCB(action="topup"),
    )
    builder.button(
        text="📜 Lịch sử giao dịch",
        callback_data=WalletActionCB(action="history"),
    )
    builder.adjust(2)
    return builder.as_markup()


def wallet_topup_amounts_kb() -> InlineKeyboardMarkup:
    """Inline keyboard chọn số tiền nạp ví (preset + custom)."""
    presets = [50_000, 100_000, 200_000, 500_000, 1_000_000]

    builder = InlineKeyboardBuilder()
    for amt in presets:
        builder.button(
            text=format_vnd(amt),
            callback_data=WalletTopupAmountCB(amount=amt),
        )
    builder.button(
        text="✏️ Nhập số khác",
        callback_data=WalletTopupAmountCB(amount=0),
    )
    builder.button(
        text="⬅️ Quay lại",
        callback_data=BackCB(target="wallet"),
    )
    builder.adjust(3, 2, 1, 1)
    return builder.as_markup()


# ── Order list ──────────────────────────────────────────────────────────────

def orders_list_kb(
    orders: Sequence[dict],
    page: int = 0,
    per_page: int = 6,
    total_count: int | None = None,
) -> InlineKeyboardMarkup:
    """Inline keyboard danh sách đơn hàng có phân trang."""
    if total_count is None:
        page_items, total_pages = _paginate(orders, page, per_page)
    else:
        total_pages = max(1, math.ceil(total_count / per_page))
        page = max(0, min(page, total_pages - 1))
        page_items = list(orders)

    builder = InlineKeyboardBuilder()
    for order in page_items:
        code = order.get("order_code", "???")
        status = order.get("status", "pending")
        from bot.utils.formatting import status_emoji
        emoji = status_emoji(status)
        builder.button(
            text=f"{emoji} {code}",
            callback_data=OrderDetailCB(order_id=order["id"]),
        )
    builder.adjust(2)

    # Pagination
    if total_pages > 1:
        builder.row(*build_pagination_buttons(
            page=page,
            total_pages=total_pages,
            prev_callback=OrderListPageCB(page=page - 1).pack(),
            next_callback=OrderListPageCB(page=page + 1).pack(),
        ).inline_keyboard[0])

    return builder.as_markup()


# ── Confirm / Cancel generic ────────────────────────────────────────────────

def order_cancel_kb(order_id: int) -> InlineKeyboardMarkup:
    """Nút hủy đơn."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="❌ Hủy đơn hàng",
        callback_data=OrderCancelCB(order_id=order_id),
    )
    return builder.as_markup()


def order_detail_kb(
    order_id: int,
    can_cancel: bool = False,
) -> InlineKeyboardMarkup:
    """Nút cho màn chi tiết đơn hàng."""
    builder = InlineKeyboardBuilder()
    if can_cancel:
        builder.button(
            text="❌ Hủy đơn hàng",
            callback_data=OrderCancelCB(order_id=order_id),
        )
    builder.button(text="⬅️ Quay lại", callback_data=BackCB(target="orders_back"))
    builder.adjust(1)
    return builder.as_markup()


def back_only_kb(
    target: str | object,
    text: str = "⬅️ Quay lại",
) -> InlineKeyboardMarkup:
    """Inline keyboard chỉ gồm 1 nút quay lại."""
    builder = InlineKeyboardBuilder()
    builder.button(text=text, callback_data=_pack_callback_data(target))
    return builder.as_markup()
