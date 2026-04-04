"""Quick verification script for active bot handlers."""
import asyncio
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from db.database import close_db
from db.models import init_db


async def main() -> None:
    await init_db()

    from bot.handlers.start import router as start_router

    print(f"[OK] start.py - router name: {start_router.name}")

    from bot.handlers.catalog import router as catalog_router

    print(f"[OK] catalog.py - router name: {catalog_router.name}")

    from bot.handlers.flow_api_key import router as api_key_router

    print(f"[OK] flow_api_key.py - router name: {api_key_router.name}")

    from bot.handlers.flow_accounts import router as account_flow_router

    print(f"[OK] flow_accounts.py - router name: {account_flow_router.name}")

    from bot.handlers.wallet import router as wallet_router

    print(f"[OK] wallet.py - router name: {wallet_router.name}")

    from bot.handlers.orders import router as orders_router

    print(f"[OK] orders.py - router name: {orders_router.name}")

    from bot.handlers.search_order import router as search_order_router

    print(f"[OK] search_order.py - router name: {search_order_router.name}")

    from bot.handlers.account import router as account_router

    print(f"[OK] account.py - router name: {account_router.name}")

    from bot.handlers.support import router as support_router

    print(f"[OK] support.py - router name: {support_router.name}")

    from aiogram import Dispatcher
    from bot.handlers import setup_routers
    from bot.storage.sqlite_fsm import SQLiteFSMStorage

    dispatcher = Dispatcher(storage=SQLiteFSMStorage())
    setup_routers(dispatcher)
    print(f"[OK] setup_routers - {len(dispatcher.sub_routers)} routers registered")

    from bot.handlers.flow_accounts import UpgradeStates
    from bot.handlers.flow_api_key import ApiKeyStates
    from bot.handlers.search_order import SearchOrderStates
    from bot.handlers.wallet import WalletTopupStates

    _ = (ApiKeyStates, UpgradeStates, WalletTopupStates, SearchOrderStates)
    print("[OK] FSM states exist for active flows")

    from bot.main import main as bot_main

    _ = bot_main
    print("[OK] bot.main.main importable")

    await close_db()
    print("\n=== ALL PHASE 3 TESTS PASSED ===")


asyncio.run(main())
