import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from .config import load_config
from .crypto import Crypto
from .gamedb import GameDB
from .handlers import accounts, admin, bind, start
from .storage import Storage


log = logging.getLogger("bindbot")


async def sync_servers(cfg, db: Storage, games: GameDB) -> None:
    """Подтягиваем серверы из servers.json / .env и сразу проверяем подключение к их БД."""
    if not cfg.servers:
        log.warning("Серверы не заданы: заполните servers.json, либо добавьте через /admin")
    for sv in cfg.servers:
        sid, created = await db.upsert_server(sv["name"], sv["host"], sv["port"], sv["user"],
                                              sv["password"], sv["database"], sv["table"], sv["enabled"])
        s = await db.get_server(sid)
        err = await games.test(s)
        log.info("Сервер %r %s: %s", s.name, "добавлен" if created else "обновлён",
                 "подключение к БД OK" if not err else f"ОШИБКА подключения: {err}")


async def run() -> None:
    logging.basicConfig(level=logging.INFO)
    cfg = load_config()
    db = Storage(cfg.sqlite_path, Crypto(cfg.secret_key))
    games = GameDB()
    await sync_servers(cfg, db, games)

    bot = Bot(cfg.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage(), cfg=cfg, db=db, games=games)
    # админка первой, чтобы её состояния имели приоритет
    dp.include_routers(admin.router, start.router, bind.router, accounts.router)
    try:
        await dp.start_polling(bot)
    finally:
        await games.close_all()
        await bot.session.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
