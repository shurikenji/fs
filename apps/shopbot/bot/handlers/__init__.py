"""
bot/handlers/__init__.py - Register all bot routers.
"""
from __future__ import annotations

from aiogram import Dispatcher

from bot.handlers.account import router as account_router
from bot.handlers.catalog import router as catalog_router
from bot.handlers.flow_accounts import router as flow_accounts_router
from bot.handlers.flow_api_key import router as flow_api_key_router
from bot.handlers.orders import router as orders_router
from bot.handlers.search_order import router as search_order_router
from bot.handlers.start import router as start_router
from bot.handlers.support import router as support_router
from bot.handlers.wallet import router as wallet_router

HANDLER_ROUTERS = (
    start_router,
    flow_accounts_router,
    catalog_router,
    flow_api_key_router,
    wallet_router,
    orders_router,
    search_order_router,
    account_router,
    support_router,
)


def setup_routers(dispatcher: Dispatcher) -> None:
    """Register all routers on the dispatcher."""
    dispatcher.include_routers(*HANDLER_ROUTERS)
