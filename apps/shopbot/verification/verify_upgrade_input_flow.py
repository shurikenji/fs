"""Verification for multi-message service-upgrade input collection."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


class _FakeState:
    def __init__(self) -> None:
        self.data: dict = {}
        self.state_value = None

    async def get_data(self) -> dict:
        return dict(self.data)

    async def update_data(self, **kwargs) -> None:
        self.data.update(kwargs)

    async def set_state(self, value) -> None:
        self.state_value = value

    async def clear(self) -> None:
        self.data = {}
        self.state_value = None


class _FakeMessage:
    def __init__(self, text: str = "") -> None:
        self.text = text
        self.caption = None
        self.answers: list[dict] = []
        self.edits: list[dict] = []

    async def answer(self, text: str, reply_markup=None, parse_mode=None) -> None:
        self.answers.append(
            {"text": text, "reply_markup": reply_markup, "parse_mode": parse_mode}
        )

    async def edit_text(self, text: str, reply_markup=None, parse_mode=None) -> None:
        self.edits.append(
            {"text": text, "reply_markup": reply_markup, "parse_mode": parse_mode}
        )


class _FakeCallback:
    def __init__(self, message: _FakeMessage) -> None:
        self.message = message
        self.answers: list[dict] = []

    async def answer(self, text: str | None = None, show_alert: bool = False) -> None:
        self.answers.append({"text": text, "show_alert": show_alert})


async def main() -> None:
    import bot.handlers.flow_accounts as flow_accounts

    original_get_product_by_id = flow_accounts.get_product_by_id
    original_quote_non_api_product = flow_accounts.quote_non_api_product
    original_create_order = flow_accounts.create_order
    original_update_order_status = flow_accounts.update_order_status
    original_get_balance = flow_accounts.get_balance
    original_get_setting_int = flow_accounts.get_setting_int
    original_payment_method_kb = flow_accounts.payment_method_kb

    product = {
        "id": 99,
        "name": "Nâng cấp ChatGPT Plus",
        "product_type": "service_upgrade",
        "price_vnd": 150_000,
        "category_id": 7,
        "input_prompt": "Gửi session hoặc thông tin nâng cấp",
    }
    created_orders: list[dict] = []
    updated_orders: list[dict] = []

    async def _fake_get_product_by_id(product_id: int):
        return product if product_id == 99 else None

    async def _fake_quote_non_api_product(product_row: dict, user_id: int):
        _ = product_row, user_id
        return SimpleNamespace(
            payable_amount=150_000,
            base_amount=150_000,
            discount_amount=0,
            cashback_amount=0,
            spend_credit_amount=0,
            pricing_snapshot={"kind": "verify"},
            promotion_snapshot=None,
        )

    async def _fake_create_order(**kwargs) -> int:
        created_orders.append(kwargs)
        return 501

    async def _fake_update_order_status(order_id: int, status: str, **kwargs) -> None:
        updated_orders.append({"order_id": order_id, "status": status, **kwargs})

    async def _fake_get_balance(user_id: int) -> int:
        _ = user_id
        return 90_000_000

    async def _fake_get_setting_int(key: str, default: int = 0) -> int:
        _ = key
        return default

    flow_accounts.get_product_by_id = _fake_get_product_by_id
    flow_accounts.quote_non_api_product = _fake_quote_non_api_product
    flow_accounts.create_order = _fake_create_order
    flow_accounts.update_order_status = _fake_update_order_status
    flow_accounts.get_balance = _fake_get_balance
    flow_accounts.get_setting_int = _fake_get_setting_int
    flow_accounts.payment_method_kb = lambda order_id, show_qr=True: {
        "order_id": order_id,
        "show_qr": show_qr,
    }

    try:
        state = _FakeState()
        prompt_message = _FakeMessage()
        prompt_callback = _FakeCallback(prompt_message)

        await flow_accounts.handle_upgrade_product(
            prompt_callback,
            product,
            state,
            _db_user={"id": 1},
        )
        data_after_prompt = await state.get_data()
        assert data_after_prompt["upgrade_product_id"] == 99
        assert data_after_prompt["upgrade_input_parts"] == []
        assert prompt_message.edits
        assert "Xác nhận thông tin" in prompt_message.edits[0]["text"]
        print("[OK] handle_upgrade_product initializes multi-part input collection state")

        part_one = _FakeMessage("HEADER:")
        await flow_accounts.upgrade_user_input_received(part_one, state, db_user={"id": 1})
        assert "Đã nhận phần <b>1</b>" in part_one.answers[0]["text"]

        long_payload = "<token>" + ("A" * 1800)
        part_two = _FakeMessage(long_payload)
        await flow_accounts.upgrade_user_input_received(part_two, state, db_user={"id": 1})
        state_data = await state.get_data()
        assert state_data["upgrade_input_parts"] == ["HEADER:", long_payload]
        assert state_data["upgrade_input_total_chars"] == len("HEADER:") + len(long_payload)
        print("[OK] upgrade_user_input_received appends multiple message parts without creating an order")

        reset_message = _FakeMessage()
        reset_callback = _FakeCallback(reset_message)
        await flow_accounts.upgrade_user_input_reset(reset_callback, state)
        reset_data = await state.get_data()
        assert reset_data["upgrade_input_parts"] == []
        assert reset_data["upgrade_input_total_chars"] == 0
        assert reset_message.edits
        print("[OK] upgrade_user_input_reset clears collected parts and restores the prompt")

        await state.update_data(
            upgrade_product_id=99,
            current_cat_id=7,
            upgrade_input_parts=["HEADER:", long_payload],
            upgrade_input_total_chars=len("HEADER:") + len(long_payload),
        )
        await state.set_state(flow_accounts.UpgradeStates.waiting_user_input)

        confirm_message = _FakeMessage()
        confirm_callback = _FakeCallback(confirm_message)
        await flow_accounts.upgrade_user_input_confirm(
            confirm_callback,
            state,
            db_user={"id": 1},
        )
        assert created_orders and created_orders[0]["product_id"] == 99
        assert updated_orders and updated_orders[0]["user_input_data"] == "HEADER:" + long_payload
        assert confirm_message.answers
        payment_text = confirm_message.answers[0]["text"]
        assert "bot chỉ hiển thị phần xem trước" in payment_text
        assert "&lt;token&gt;" in payment_text
        print("[OK] upgrade_user_input_confirm creates one order from concatenated parts and truncates the user preview safely")

        print("\n=== UPGRADE INPUT FLOW VERIFICATION PASSED ===")
    finally:
        flow_accounts.get_product_by_id = original_get_product_by_id
        flow_accounts.quote_non_api_product = original_quote_non_api_product
        flow_accounts.create_order = original_create_order
        flow_accounts.update_order_status = original_update_order_status
        flow_accounts.get_balance = original_get_balance
        flow_accounts.get_setting_int = original_get_setting_int
        flow_accounts.payment_method_kb = original_payment_method_kb


if __name__ == "__main__":
    asyncio.run(main())
