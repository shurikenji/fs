"""
bot/keyboards/pagination.py — Common pagination utilities for inline keyboards.

Extracts duplicated pagination logic from inline_kb.py.
"""
from __future__ import annotations

from typing import Callable, Sequence

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def build_pagination_buttons(
    page: int,
    total_pages: int,
    prev_callback: str,
    next_callback: str,
) -> InlineKeyboardMarkup:
    """
    Build generic pagination buttons row.
    
    Args:
        page: Current page (0-indexed)
        total_pages: Total number of pages
        prev_callback: Callback data for "previous" button
        next_callback: Callback data for "next" button
    
    Returns:
        InlineKeyboardMarkup with pagination buttons
    """
    builder = InlineKeyboardBuilder()
    nav_buttons: list[InlineKeyboardButton] = []
    
    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton(
                text="⬅️ Trước",
                callback_data=prev_callback,
            )
        )
    
    nav_buttons.append(
        InlineKeyboardButton(
            text=f"📄 {page + 1}/{total_pages}",
            callback_data="noop",
        )
    )
    
    if page < total_pages - 1:
        nav_buttons.append(
            InlineKeyboardButton(
                text="Sau ➡️",
                callback_data=next_callback,
            )
        )
    
    builder.row(*nav_buttons)
    return builder.as_markup()


def paginate_with_buttons(
    items: Sequence,
    page: int,
    per_page: int,
    prev_callback: str,
    next_callback: str,
) -> tuple[list, int, InlineKeyboardMarkup | None]:
    """
    Paginate items and build navigation buttons in one call.
    
    Args:
        items: Full list of items to paginate
        page: Current page (0-indexed)
        per_page: Items per page
        prev_callback: Callback data for previous button
        next_callback: Callback data for next button
    
    Returns:
        Tuple of (page_items, total_pages, pagination_markup)
    """
    import math
    total_pages = max(1, math.ceil(len(items) / per_page))
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    page_items = list(items[start : start + per_page])
    
    pagination_markup = None
    if total_pages > 1:
        pagination_markup = build_pagination_buttons(
            page=page,
            total_pages=total_pages,
            prev_callback=prev_callback,
            next_callback=next_callback,
        )
    
    return page_items, total_pages, pagination_markup
