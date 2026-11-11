"""Общие помощники для хендлеров."""
from aiogram.types import Message

from .storage import Binding, Server, Storage


async def safe_delete(message: Message) -> None:
    """Удаляем сообщения с паролями, чтобы они не оставались в переписке."""
    try:
        await message.delete()
    except Exception:  # noqa: BLE001 - нет прав/слишком старое сообщение
        pass


async def lock_left(db: Storage, cfg, tg_id: int) -> bool:
    """True, если пользователь заблокирован из-за слишком многих ошибок."""
    n = await db.failures_recent(tg_id, cfg.lock_minutes * 60)
    return n >= cfg.max_attempts


async def attempts_left(db: Storage, cfg, tg_id: int) -> int:
    n = await db.failures_recent(tg_id, cfg.lock_minutes * 60)
    return max(0, cfg.max_attempts - n)


async def owned_binding(db: Storage, tg_id: int, binding_id: int):
    """Привязка, только если она принадлежит этому пользователю."""
    b = await db.get_binding(binding_id)
    if b is None or b.tg_id != tg_id:
        return None
    return b


def lock_text(cfg) -> str:
    return (f"⛔ Слишком много неверных паролей. Попробуйте через {cfg.lock_minutes} мин.")
