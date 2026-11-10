"""Let main-menu navigation leave input flows before state filters run."""
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.filters import Command
from aiogram.types import Message

from bot.keyboards.reply_kb import main_menu_kb


class MenuNavigationMiddleware(BaseMiddleware):
    def __init__(self, commands: Iterable[str]) -> None:
        self.menu_texts = {
            button.text for row in main_menu_kb().keyboard for button in row
        } | {"🛒 Sản phẩm"}
        self.commands = Command("start", *commands)

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        state = data.get("state")
        if state and (event.text in self.menu_texts or await self.commands(event, data["bot"])):
            await state.clear()
            # Aiogram caches the state before the message's outer middlewares.
            data["raw_state"] = None
        return await handler(event, data)
