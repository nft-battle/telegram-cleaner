import asyncio
import logging

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .config import BOT_TOKEN, PORT
from .database import db
from .handlers import auth, dialogs
from .userbot import cleaner

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


async def _health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


async def _autosweep(interval: int = 1800) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            if await db.get("autokill") == "1":
                results = await cleaner.sweep_removed()
                if results:
                    logger.info("Авто-уборка: %d чатов обработано", len(results))
        except Exception:
            logger.exception("Ошибка авто-уборки")


async def main() -> None:
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не задан")
        return
    await db.init()
    logger.info("Cleaner: БД %s", "PostgreSQL" if db.is_pg else "SQLite")
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_routers(auth.router, dialogs.router)

    app = web.Application()
    app.router.add_get("/", _health)
    app.router.add_get("/health", _health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info("HTTP-сервер на порту %s", PORT)

    asyncio.get_event_loop().create_task(_autosweep())

    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot)
    finally:
        await db.close()