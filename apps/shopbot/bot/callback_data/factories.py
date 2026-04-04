"""
bot/callback_data/factories.py — Tất cả aiogram CallbackData classes.
Prefix ngắn để tránh vượt 64 bytes giới hạn Telegram callback_data.
"""
from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


# ── Danh mục ────────────────────────────────────────────────────────────────

class CategoryPageCB(CallbackData, prefix="catp"):
    """Phân trang danh mục."""
    page: int


class CategorySelectCB(CallbackData, prefix="cats"):
    """Chọn danh mục."""
    id: int


# ── Key API action ──────────────────────────────────────────────────────────

class KeyActionCB(CallbackData, prefix="ka"):
    """Chọn hành động key: new (mua mới) / topup (nạp key cũ)."""
    cat_id: int
    action: str  # 'new' | 'topup'


# ── Server selection ────────────────────────────────────────────────────────

class ServerSelectCB(CallbackData, prefix="srv"):
    """Chọn server."""
    cat_id: int
    action: str  # 'new' | 'topup'
    server_id: int


# ── Product pagination & selection ──────────────────────────────────────────

class ProductPageCB(CallbackData, prefix="pp"):
    """Phân trang sản phẩm."""
    cat_id: int
    srv_id: int
    ptype: str  # product_type filter
    page: int


class ProductSelectCB(CallbackData, prefix="ps"):
    """Chọn sản phẩm."""
    product_id: int


class QuantityAdjustCB(CallbackData, prefix="qtya"):
    """Tăng/giảm số lượng cho một sản phẩm đủ điều kiện."""
    product_id: int
    qty: int


class QuantityConfirmCB(CallbackData, prefix="qtyc"):
    """Xác nhận số lượng và đi tiếp sang bước tạo order."""
    product_id: int
    qty: int


class QuantityBackCB(CallbackData, prefix="qtyb"):
    """Quay lại danh sách sản phẩm từ màn chọn số lượng."""
    product_id: int


# ── Payment ─────────────────────────────────────────────────────────────────

class PaymentMethodCB(CallbackData, prefix="pay"):
    """Chọn phương thức thanh toán."""
    order_id: int
    method: str  # 'qr' | 'wallet'


class OrderCancelCB(CallbackData, prefix="oc"):
    """Hủy đơn hàng."""
    order_id: int


# ── My keys ─────────────────────────────────────────────────────────────────

class MyKeySelectCB(CallbackData, prefix="mk"):
    """Chọn key của tôi (để topup)."""
    key_id: int


class MyKeysPageCB(CallbackData, prefix="mkp"):
    """Xem danh sách key đã lưu theo trang."""
    server_id: int
    cat_id: int
    page: int


class MyKeySearchCB(CallbackData, prefix="mks"):
    """Mở màn tìm key đã lưu."""
    server_id: int
    cat_id: int


class MyKeyInputCB(CallbackData, prefix="mki"):
    """Nhập key mới cho server (trigger FSM)."""
    server_id: int
    cat_id: int


class CustomAmountCB(CallbackData, prefix="ca"):
    """Trigger nhập số $ custom cho key mới/topup."""
    cat_id: int
    action: str     # 'new' | 'topup'
    server_id: int


# ── Wallet ──────────────────────────────────────────────────────────────────

class WalletActionCB(CallbackData, prefix="wa"):
    """Hành động ví: topup / history."""
    action: str


class WalletTopupAmountCB(CallbackData, prefix="wta"):
    """Chọn số tiền nạp ví (preset hoặc custom)."""
    amount: int  # 0 = custom input


# ── Orders ──────────────────────────────────────────────────────────────────

class OrderListPageCB(CallbackData, prefix="olp"):
    """Phân trang danh sách đơn hàng."""
    page: int


class OrderDetailCB(CallbackData, prefix="od"):
    """Xem chi tiết đơn hàng."""
    order_id: int


# ── Back / Navigation ──────────────────────────────────────────────────────

class BackCB(CallbackData, prefix="back"):
    """Quay lại màn hình trước."""
    target: str  # 'cat' | 'srv' | 'prod' | 'main' | 'wallet' | ...


class BackServersCB(CallbackData, prefix="bs"):
    """Quay lại danh sách server trong một danh mục key API."""
    cat_id: int
    action: str


class BackKeyInputCB(CallbackData, prefix="bki"):
    """Quay từ màn nhập key về danh sách key hiện có của server."""
    server_id: int
    cat_id: int


class BackCustomAmountCB(CallbackData, prefix="bca"):
    """Quay từ màn nhập $ custom về danh sách gói của server."""
    server_id: int
    cat_id: int
    action: str


class UpgradeBackCB(CallbackData, prefix="bup"):
    """Quay từ màn nhập thông tin dịch vụ về danh sách sản phẩm của danh mục."""
    cat_id: int
