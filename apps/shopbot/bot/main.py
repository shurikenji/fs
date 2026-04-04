"""
bot/main.py - Điểm vào của bot và vòng đời ứng dụng.
Chạy với: python -m bot.main
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from bot.config import settings
from bot.handlers import setup_routers
from bot.middlewares.auth import AuthMiddleware
from bot.services.key_alert_poller import start_key_alert_poller
from bot.storage.sqlite_fsm import SQLiteFSMStorage
from bot.services.payment_poller import start_payment_poller
from db.bootstrap import init_db
from db.database import close_db

logger = logging.getLogger(__name__)

BOT_COMMANDS = (
    BotCommand(command="menu", description="🏠 Khôi phục menu"),
    BotCommand(command="products", description="🛒 Mua hàng"),
    BotCommand(command="wallet", description="👛 Ví của tôi"),
    BotCommand(command="orders", description="📋 Lịch sử đơn hàng"),
    BotCommand(command="search", description="🔎 Tìm đơn hàng"),
    BotCommand(command="profile", description="👤 Thông tin tài khoản"),
    BotCommand(command="support", description="🆘 Hỗ trợ"),
)


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def build_bot() -> Bot:
    return Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def build_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher(storage=SQLiteFSMStorage())
    middleware = AuthMiddleware()
    dispatcher.message.middleware(middleware)
    dispatcher.callback_query.middleware(middleware)
    setup_routers(dispatcher)
    return dispatcher


async def register_bot_commands(
    bot: Bot,
    commands: Iterable[BotCommand] = BOT_COMMANDS,
) -> None:
    await bot.set_my_commands(list(commands))


async def start_admin_server() -> asyncio.Task | None:
    try:
        import uvicorn

        from admin.app import create_admin_app

        config = uvicorn.Config(
            create_admin_app(),
            host="0.0.0.0",
            port=settings.admin_port,
            log_level="info",
        )
        server = uvicorn.Server(config)
        logger.info("Admin panel starting on port %d", settings.admin_port)
        return asyncio.create_task(server.serve())
    except ImportError:
        logger.warning("Admin panel not available")
    except Exception as exc:
        logger.warning("Admin panel failed to start: %s", exc)
    return None


async def cancel_task(task: asyncio.Task | None) -> None:
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def main() -> None:
    """Khởi động bot, poller thanh toán và admin panel."""
    configure_logging()

    if not settings.bot_token:
        logger.error("BOT_TOKEN is missing in environment configuration")
        return

    logger.info("Starting ShopBot...")
    await init_db()
    logger.info("Database initialized")

    bot = build_bot()
    dispatcher = build_dispatcher()
    await register_bot_commands(bot)

    poller_task = asyncio.create_task(start_payment_poller(bot))
    key_alert_task = asyncio.create_task(start_key_alert_poller(bot))
    admin_task = await start_admin_server()

    try:
        logger.info("Bot started; polling for updates...")
        await dispatcher.start_polling(bot)
    finally:
        logger.info("Shutting down...")
        await cancel_task(poller_task)
        await cancel_task(key_alert_task)
        await cancel_task(admin_task)
        await close_db()
        await bot.session.close()
        logger.info("Shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
