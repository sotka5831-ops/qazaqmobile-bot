import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..common import attempts_left, lock_left, lock_text, safe_delete
from ..config import Config
from ..gamedb import GameDB
from ..security import verify_password
from ..states import BindSG
from ..storage import Storage
from ..ui import back_menu_kb, cancel_kb, h

router = Router()
router.message.filter(F.chat.type == "private")

NICK_RE = re.compile(r"^[A-Za-z0-9_\[\]\.\$@=\(\)]{3,24}$")


@router.callback_query(F.data == "bind")
async def cb_bind(call: CallbackQuery, state: FSMContext, db: Storage, cfg: Config):
    await state.clear()
    mine = await db.list_bindings(call.from_user.id)
    if len(mine) >= cfg.max_accounts:
        await call.message.edit_text(
            f"У вас уже привязано максимум аккаунтов ({cfg.max_accounts}). Отвяжите лишний.",
            reply_markup=back_menu_kb())
        return await call.answer()
    servers = await db.list_servers(only_enabled=True)
    if not servers:
        await call.message.edit_text("Сейчас нет доступных серверов. Загляните позже.", reply_markup=back_menu_kb())
        return await call.answer()
    rows = [[InlineKeyboardButton(text=f"🖥 {s.name}", callback_data=f"bind_srv:{s.id}")] for s in servers]
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")])
    await call.message.edit_text("Выберите сервер:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await call.answer()


@router.callback_query(F.data.startswith("bind_srv:"))
async def cb_server(call: CallbackQuery, state: FSMContext, db: Storage):
    server = await db.get_server(int(call.data.split(":")[1]))
    if server is None or not server.enabled:
        await call.answer("Сервер недоступен", show_alert=True)
        return
    await state.set_state(BindSG.nickname)
    await state.update_data(server_id=server.id)
    await call.message.edit_text(f"Сервер: <b>{h(server.name)}</b>\n\nВведите игровой ник:", reply_markup=cancel_kb())
    await call.answer()


@router.message(BindSG.nickname, F.text)
async def got_nick(message: Message, state: FSMContext, db: Storage, games: GameDB):
    nick = message.text.strip()
    if not NICK_RE.match(nick):
        return await message.answer("Некорректный ник. Введите ник ещё раз:", reply_markup=cancel_kb())
    data = await state.get_data()
    server = await db.get_server(data.get("server_id", 0))
    if server is None or not server.enabled:
        await state.clear()
        return await message.answer("Сервер недоступен.", reply_markup=back_menu_kb())
    try:
        acc = await games.find_by_name(server, nick)
    except Exception:  # noqa: BLE001
        return await message.answer("⚠️ Не удалось подключиться к базе сервера. Попробуйте позже.",
                                    reply_markup=cancel_kb())
    if acc is None:
        return await message.answer("❌ Аккаунт с таким ником не найден. Введите ник ещё раз:",
                                    reply_markup=cancel_kb())
    existing = await db.find_binding(server.id, acc["id"])
    if existing:
        await state.clear()
        text = ("Этот аккаунт уже привязан к вашему Telegram." if existing.tg_id == message.from_user.id
                else "🔒 Этот аккаунт уже привязан к другому Telegram. Попросите владельца отвязать его.")
        return await message.answer(text, reply_markup=back_menu_kb())
    await state.update_data(account_id=acc["id"], nickname=acc["name"])
    await state.set_state(BindSG.password)
    await message.answer(f"Аккаунт <b>{h(acc['name'])}</b> найден.\nВведите пароль от аккаунта "
                         "(сообщение с паролем будет удалено):", reply_markup=cancel_kb())


@router.message(BindSG.password, F.text)
async def got_password(message: Message, state: FSMContext, db: Storage, games: GameDB, cfg: Config):
    password = message.text
    await safe_delete(message)
    tg = message.from_user.id
    if await lock_left(db, cfg, tg):
        await state.clear()
        return await message.answer(lock_text(cfg), reply_markup=back_menu_kb())

    data = await state.get_data()
    server = await db.get_server(data.get("server_id", 0))
    if server is None or not server.enabled:
        await state.clear()
        return await message.answer("Сервер недоступен.", reply_markup=back_menu_kb())
    try:
        acc = await games.find_by_id(server, data["account_id"])
    except Exception:  # noqa: BLE001
        return await message.answer("⚠️ Не удалось подключиться к базе сервера. Попробуйте позже.",
                                    reply_markup=cancel_kb())
    if acc is None:
        await state.clear()
        return await message.answer("Аккаунт больше не существует.", reply_markup=back_menu_kb())

    variant = verify_password(password, acc["salt"] or "", acc["password"] or "", cfg.hash_variant)
    if variant is None:
        await db.note_failure(tg)
        left = await attempts_left(db, cfg, tg)
        if left == 0:
            await state.clear()
            return await message.answer(lock_text(cfg), reply_markup=back_menu_kb())
        return await message.answer(f"❌ Неверный пароль. Осталось попыток: {left}. Введите пароль ещё раз:",
                                    reply_markup=cancel_kb())

    if await db.find_binding(server.id, acc["id"]):  # гонка: успели привязать
        await state.clear()
        return await message.answer("Этот аккаунт уже привязан.", reply_markup=back_menu_kb())
    await db.add_binding(tg, server.id, acc["id"], acc["name"], variant)
    await db.clear_failures(tg)
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Мои аккаунты", callback_data="accounts")],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]])
    await message.answer(f"✅ Аккаунт <b>{h(acc['name'])}</b> ({h(server.name)}) привязан к вашему Telegram.",
                         reply_markup=kb)
