"""
Compatibility shim for the retired legacy products handler.

The active bot flow lives in:
  - bot.handlers.catalog
  - bot.handlers.flow_api_key
  - bot.handlers.flow_accounts

This module intentionally keeps only the legacy public symbols still used by
older verification scripts.
"""
from __future__ import annotations

from aiogram import Router
from aiogram.fsm.state import State, StatesGroup

router = Router(name="products")


class ProductStates(StatesGroup):
    waiting_existing_key = State()
    waiting_custom_dollar = State()


__all__ = ["ProductStates", "router"]
