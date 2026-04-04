"""
bot/handlers/wallet.py — Xem số dư, nạp ví QR, lịch sử giao dịch.
"""
from __future__ import annotations
from bot.utils.time_utils import get_now_vn

from datetime import datetime, timedelta

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.callback_data.factories import WalletActionCB, WalletTopupAmountCB, BackCB
from bot.keyboards.inline_kb import wallet_menu_kb, wallet_topup_amounts_kb, back_only_kb
from bot.utils.formatting import format_vnd, status_emoji, format_time_vn
from bot.utils.order_code import generate_order_code
from bot.services.vietqr import build_qr_url, build_qr_caption
from db.queries.wallets import get_balance, get_wallet_transactions, count_wallet_transactions
from db.queries.orders import create_order
from db.queries.settings import get_setting_int

router = Router(name="wallet")


# ── FSM cho nhập số tiền custom ─────────────────────────────────────────────

class WalletTopupStates(StatesGroup):
    waiting_custom_amount = State()


# ── Reply keyboard trigger ──────────────────────────────────────────────────

@router.message(Command("wallet"))
@router.message(F.text == "👛 Ví")
async def wallet_menu(message: Message, db_user: dict) -> None:
    """Hiện menu ví: số dư + nút nạp/lịch sử."""
    balance = await get_balance(db_user["id"])
    text = (
        f"👛 <b>Ví của bạn</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Số dư: <b>{format_vnd(balance)}</b>"
    )
    await message.answer(text, reply_markup=wallet_menu_kb(), parse_mode="HTML")


# ── Nạp tiền ────────────────────────────────────────────────────────────────

@router.callback_query(WalletActionCB.filter(F.action == "topup"))
async def wallet_topup_menu(callback: CallbackQuery, db_user: dict) -> None:
    """Hiện bảng chọn số tiền nạp."""
    await callback.message.edit_text(
        "💰 <b>Nạp tiền vào ví</b>\n\nChọn số tiền bạn muốn nạp:",
        reply_markup=wallet_topup_amounts_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(WalletTopupAmountCB.filter(F.amount > 0))
async def wallet_topup_preset(
    callback: CallbackQuery,
    callback_data: WalletTopupAmountCB,
    db_user: dict,
) -> None:
    """Xử lý nạp ví với số tiền preset → tạo QR."""
    await _create_topup_order(callback, db_user, callback_data.amount)


@router.callback_query(WalletTopupAmountCB.filter(F.amount == 0))
async def wallet_topup_custom_prompt(
    callback: CallbackQuery,
    state: FSMContext,
    db_user: dict,
) -> None:
    """Yêu cầu nhập số tiền custom."""
    await callback.message.edit_text(
        f"✏️ <b>Nhập số tiền muốn nạp</b>\n\n"
        f"Nhập số tiền (VNĐ, tối thiểu 10.000đ):\n"
        f"Ví dụ: <code>50000</code> hoặc <code>100000</code>",
        reply_markup=back_only_kb("wallet"),
        parse_mode="HTML",
    )
    await state.set_state(WalletTopupStates.waiting_custom_amount)
    await callback.answer()


@router.message(WalletTopupStates.waiting_custom_amount)
async def wallet_topup_custom_input(
    message: Message,
    state: FSMContext,
    db_user: dict,
) -> None:
    """Xử lý input số tiền custom."""
    # Parse số tiền
    text = message.text.strip().replace(".", "").replace(",", "").replace(" ", "")
    if not text.isdigit():
        await message.answer(
            "❌ Số tiền không hợp lệ. Vui lòng nhập số nguyên.\n"
            "Ví dụ: <code>50000</code>",
            parse_mode="HTML",
            reply_markup=back_only_kb("wallet"),
        )
        return

    amount = int(text)
    wallet_min = 10000
    if amount < wallet_min:
        await message.answer(
            f"❌ Số tiền tối thiểu là <b>{format_vnd(wallet_min)}</b>",
            parse_mode="HTML",
            reply_markup=back_only_kb("wallet"),
        )
        return
    wallet_max = 100_000_000
    if amount > wallet_max:
        await message.answer(
            f"❌ Số tiền tối đa là <b>{format_vnd(wallet_max)}</b>",
            parse_mode="HTML",
            reply_markup=back_only_kb("wallet"),
        )
        return

    await state.clear()

    # Tạo đơn nạp ví
    order_code = generate_order_code()
    expire_min = await get_setting_int("order_expire_min", 30)
    expired_at = (get_now_vn() + timedelta(minutes=expire_min)).isoformat()

    order_id = await create_order(
        order_code=order_code,
        user_id=db_user["id"],
        product_type="wallet_topup",
        amount=amount,
        payment_method="qr",
        product_name="Nạp ví",
        expired_at=expired_at,
    )

    # Tạo QR
    qr_url = await build_qr_url(amount, order_code)
    caption = await build_qr_caption(amount, order_code, expire_min)

    from bot.keyboards.inline_kb import order_cancel_kb
    await message.answer_photo(
        photo=qr_url,
        caption=caption,
        parse_mode="HTML",
        reply_markup=order_cancel_kb(order_id)
    )


async def _create_topup_order(
    callback: CallbackQuery,
    db_user: dict,
    amount: int,
) -> None:
    """Helper: tạo đơn nạp ví + gửi QR."""
    order_code = generate_order_code()
    expire_min = await get_setting_int("order_expire_min", 30)
    expired_at = (get_now_vn() + timedelta(minutes=expire_min)).isoformat()

    order_id = await create_order(
        order_code=order_code,
        user_id=db_user["id"],
        product_type="wallet_topup",
        amount=amount,
        payment_method="qr",
        product_name="Nạp ví",
        expired_at=expired_at,
    )

    qr_url = await build_qr_url(amount, order_code)
    caption = await build_qr_caption(amount, order_code, expire_min)

    # Xóa message cũ, gửi ảnh QR
    from bot.keyboards.inline_kb import order_cancel_kb
    await callback.message.delete()
    await callback.message.answer_photo(
        photo=qr_url,
        caption=caption,
        parse_mode="HTML",
        reply_markup=order_cancel_kb(order_id)
    )
    await callback.answer()


# ── Lịch sử giao dịch ──────────────────────────────────────────────────────

@router.callback_query(WalletActionCB.filter(F.action == "history"))
async def wallet_history(callback: CallbackQuery, db_user: dict) -> None:
    """Hiện lịch sử giao dịch ví."""
    txs = await get_wallet_transactions(db_user["id"], limit=10)

    if not txs:
        await callback.message.edit_text(
            "📜 <b>Lịch sử giao dịch</b>\n\nChưa có giao dịch nào.",
            reply_markup=back_only_kb("wallet"),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    lines = ["📜 <b>Lịch sử giao dịch (10 gần nhất)</b>\n"]
    for tx in txs:
        amount = tx["amount"]
        sign = "+" if amount > 0 else ""
        tx_type = tx["type"]
        type_icons = {
            "topup": "💰",
            "purchase": "🛒",
            "refund": "↩️",
            "admin_adjust": "⚙️",
        }
        icon = type_icons.get(tx_type, "💳")
        created = format_time_vn(tx.get("created_at", ""))[:16]

        lines.append(
            f"{icon} <code>{sign}{format_vnd(amount)}</code> "
            f"→ {format_vnd(tx['balance_after'])} "
            f"<i>({created})</i>"
        )

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=back_only_kb("wallet"),
        parse_mode="HTML",
    )
    await callback.answer()


# ── Back to wallet ──────────────────────────────────────────────────────────

@router.callback_query(BackCB.filter(F.target == "wallet"))
async def back_to_wallet(
    callback: CallbackQuery,
    state: FSMContext,
    db_user: dict,
) -> None:
    """Quay lại menu ví."""
    await state.clear()
    balance = await get_balance(db_user["id"])
    text = (
        f"👛 <b>Ví của bạn</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Số dư: <b>{format_vnd(balance)}</b>"
    )
    await callback.message.edit_text(
        text, reply_markup=wallet_menu_kb(), parse_mode="HTML"
    )
    await callback.answer()
