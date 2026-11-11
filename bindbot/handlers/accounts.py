from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..common import attempts_left, lock_left, lock_text, owned_binding, safe_delete
from ..config import Config
from ..gamedb import GameDB
from ..security import (DEFAULT_VARIANT, make_hash, random_salt, valid_admin_pass,
                        valid_password, valid_pin, verify_password)
from ..states import AccSG
from ..storage import Storage
from ..ui import account_kb, back_menu_kb, cancel_kb, h, yes_no_kb

router = Router()
router.message.filter(F.chat.type == "private")

DB_ERROR = "⚠️ Не удалось подключиться к базе сервера. Попробуйте позже."


async def _load(db: Storage, games: GameDB, tg_id: int, binding_id: int):
    """Возвращает (binding, server, account) или (None, None, None) с уже удалённой битой привязкой."""
    b = await owned_binding(db, tg_id, binding_id)
    if b is None:
        return None, None, None
    server = await db.get_server(b.server_id)
    if server is None:
        await db.delete_binding(b.id)
        return None, None, None
    acc = await games.find_by_id(server, b.account_id)
    if acc is None:  # аккаунт удалён в игре
        await db.delete_binding(b.id)
        return None, None, None
    return b, server, acc


@router.callback_query(F.data == "accounts")
async def cb_accounts(call: CallbackQuery, state: FSMContext, db: Storage):
    await state.clear()
    mine = await db.list_bindings(call.from_user.id)
    if not mine:
        await call.message.edit_text("У вас пока нет привязанных аккаунтов.",
                                     reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                         [InlineKeyboardButton(text="🔗 Привязать аккаунт", callback_data="bind")],
                                         [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]]))
        return await call.answer()
    servers = {s.id: s for s in await db.list_servers()}
    rows = []
    for b in mine:
        sname = servers[b.server_id].name if b.server_id in servers else "?"
        rows.append([InlineKeyboardButton(text=f"👤 {b.nickname} — {sname}", callback_data=f"acc:{b.id}")])
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")])
    await call.message.edit_text("Ваши аккаунты:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await call.answer()


@router.callback_query(F.data.startswith("acc:"))
async def cb_account(call: CallbackQuery, state: FSMContext, db: Storage, games: GameDB):
    await state.clear()
    try:
        b, server, acc = await _load(db, games, call.from_user.id, int(call.data.split(":")[1]))
    except Exception:  # noqa: BLE001
        return await call.answer(DB_ERROR, show_alert=True)
    if b is None:
        return await cb_accounts(call, state, db)
    is_admin = (acc.get("admin") or 0) > 0
    await call.message.edit_text(
        f"👤 <b>{h(b.nickname)}</b>\n🖥 Сервер: {h(server.name)}\nУровень админки: {acc.get('admin') or 0}\n\nВыберите действие:",
        reply_markup=account_kb(b.id, is_admin))
    await call.answer()


# ---------- смена пароля / PIN / админ-пароля ----------
PROMPTS = {
    "pw": (AccSG.new_password, "🔑 Введите <b>новый пароль</b> от аккаунта (сообщение будет удалено):"),
    "pin": (AccSG.new_pin, "🔢 Введите <b>новый PIN-код</b> (4 цифры):"),
    "apass": (AccSG.new_apass, "🛡 Введите <b>новый админ-пароль</b> (4 цифры, 1000–9999):"),
}


@router.callback_query(F.data.regexp(r"^act:(pw|pin|apass):\d+$"))
async def cb_change(call: CallbackQuery, state: FSMContext, db: Storage, games: GameDB):
    _, kind, bid = call.data.split(":")
    try:
        b, server, acc = await _load(db, games, call.from_user.id, int(bid))
    except Exception:  # noqa: BLE001
        return await call.answer(DB_ERROR, show_alert=True)
    if b is None:
        return await call.answer("Аккаунт не найден", show_alert=True)
    if kind == "apass" and (acc.get("admin") or 0) <= 0:
        return await call.answer("У этого аккаунта нет админ-прав", show_alert=True)
    st, text = PROMPTS[kind]
    await state.set_state(st)
    await state.update_data(binding_id=b.id)
    await call.message.edit_text(text, reply_markup=cancel_kb())
    await call.answer()


async def _ctx(message: Message, state: FSMContext, db: Storage, games: GameDB):
    data = await state.get_data()
    try:
        b, server, acc = await _load(db, games, message.from_user.id, data.get("binding_id", 0))
    except Exception:  # noqa: BLE001
        await message.answer(DB_ERROR, reply_markup=cancel_kb())
        return None, None, None
    if b is None:
        await state.clear()
        await message.answer("Аккаунт не найден.", reply_markup=back_menu_kb())
    return b, server, acc


def _back(b_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ К аккаунту", callback_data=f"acc:{b_id}")]])


@router.message(AccSG.new_password, F.text)
async def set_new_password(message: Message, state: FSMContext, db: Storage, games: GameDB, cfg: Config):
    value = message.text
    await safe_delete(message)
    err = valid_password(value, cfg.pw_min, cfg.pw_max)
    if err:
        return await message.answer(f"❌ {err}\nВведите пароль ещё раз:", reply_markup=cancel_kb())
    b, server, acc = await _ctx(message, state, db, games)
    if b is None:
        return
    variant = b.hash_variant or cfg.hash_variant or DEFAULT_VARIANT
    salt = random_salt()
    try:
        ok = await games.set_password(server, acc["id"], make_hash(value, salt, variant), salt)
    except Exception:  # noqa: BLE001
        return await message.answer(DB_ERROR, reply_markup=cancel_kb())
    await state.clear()
    await message.answer("✅ Пароль изменён." if ok else "❌ Не удалось изменить пароль.", reply_markup=_back(b.id))


@router.message(AccSG.new_pin, F.text)
async def set_new_pin(message: Message, state: FSMContext, db: Storage, games: GameDB):
    value = message.text.strip()
    await safe_delete(message)
    err = valid_pin(value)
    if err:
        return await message.answer(f"❌ {err}\nВведите PIN-код ещё раз:", reply_markup=cancel_kb())
    b, server, acc = await _ctx(message, state, db, games)
    if b is None:
        return
    try:
        ok = await games.set_pin(server, acc["id"], value)
    except Exception:  # noqa: BLE001
        return await message.answer(DB_ERROR, reply_markup=cancel_kb())
    await state.clear()
    await message.answer("✅ PIN-код изменён." if ok else "❌ Не удалось изменить PIN-код.", reply_markup=_back(b.id))


@router.message(AccSG.new_apass, F.text)
async def set_new_apass(message: Message, state: FSMContext, db: Storage, games: GameDB):
    value = message.text.strip()
    await safe_delete(message)
    err = valid_admin_pass(value)
    if err:
        return await message.answer(f"❌ {err}\nВведите админ-пароль ещё раз:", reply_markup=cancel_kb())
    b, server, acc = await _ctx(message, state, db, games)
    if b is None:
        return
    if (acc.get("admin") or 0) <= 0:
        await state.clear()
        return await message.answer("У этого аккаунта нет админ-прав.", reply_markup=_back(b.id))
    try:
        ok = await games.set_admin_pass(server, acc["id"], int(value))
    except Exception:  # noqa: BLE001
        return await message.answer(DB_ERROR, reply_markup=cancel_kb())
    await state.clear()
    await message.answer("✅ Админ-пароль изменён." if ok else "❌ Не удалось изменить админ-пароль.",
                         reply_markup=_back(b.id))


# ---------- отвязка ----------
@router.callback_query(F.data.regexp(r"^act:unlink:\d+$"))
async def cb_unlink_ask(call: CallbackQuery, db: Storage):
    bid = int(call.data.split(":")[2])
    b = await owned_binding(db, call.from_user.id, bid)
    if b is None:
        return await call.answer("Аккаунт не найден", show_alert=True)
    await call.message.edit_text(
        f"Отвязать <b>{h(b.nickname)}</b> от Telegram?\n\nПосле этого бот не сможет менять данные аккаунта, "
        "а привязать его сможет любой, кто знает пароль.",
        reply_markup=yes_no_kb(f"unlink_yes:{bid}", "🔓 Да, отвязать"))
    await call.answer()


@router.callback_query(F.data.regexp(r"^unlink_yes:\d+$"))
async def cb_unlink_yes(call: CallbackQuery, db: Storage):
    b = await owned_binding(db, call.from_user.id, int(call.data.split(":")[1]))
    if b is None:
        return await call.answer("Аккаунт не найден", show_alert=True)
    await db.delete_binding(b.id)
    await call.message.edit_text(f"🔓 Аккаунт <b>{h(b.nickname)}</b> отвязан.", reply_markup=back_menu_kb())
    await call.answer()


# ---------- удаление аккаунта ----------
@router.callback_query(F.data.regexp(r"^act:del:\d+$"))
async def cb_delete_ask(call: CallbackQuery, db: Storage):
    bid = int(call.data.split(":")[2])
    b = await owned_binding(db, call.from_user.id, bid)
    if b is None:
        return await call.answer("Аккаунт не найден", show_alert=True)
    await call.message.edit_text(
        f"⚠️ Вы точно хотите <b>удалить аккаунт {h(b.nickname)}</b>?\n\n"
        "Он будет полностью удалён из базы сервера. Это необратимо.",
        reply_markup=yes_no_kb(f"del_ask:{bid}", "🗑 Да, удалить"))
    await call.answer()


@router.callback_query(F.data.regexp(r"^del_ask:\d+$"))
async def cb_delete_password(call: CallbackQuery, state: FSMContext, db: Storage):
    b = await owned_binding(db, call.from_user.id, int(call.data.split(":")[1]))
    if b is None:
        return await call.answer("Аккаунт не найден", show_alert=True)
    await state.set_state(AccSG.delete_password)
    await state.update_data(binding_id=b.id)
    await call.message.edit_text(
        f"Для удаления <b>{h(b.nickname)}</b> введите пароль от аккаунта (сообщение будет удалено):",
        reply_markup=cancel_kb())
    await call.answer()


@router.message(AccSG.delete_password, F.text)
async def do_delete(message: Message, state: FSMContext, db: Storage, games: GameDB, cfg: Config):
    password = message.text
    await safe_delete(message)
    tg = message.from_user.id
    if await lock_left(db, cfg, tg):
        await state.clear()
        return await message.answer(lock_text(cfg), reply_markup=back_menu_kb())
    b, server, acc = await _ctx(message, state, db, games)
    if b is None:
        return
    variant = verify_password(password, acc["salt"] or "", acc["password"] or "", cfg.hash_variant)
    if variant is None:
        await db.note_failure(tg)
        left = await attempts_left(db, cfg, tg)
        if left == 0:
            await state.clear()
            return await message.answer(lock_text(cfg), reply_markup=back_menu_kb())
        return await message.answer(f"❌ Неверный пароль. Осталось попыток: {left}.", reply_markup=cancel_kb())
    if (acc.get("admin") or 0) > 0 and not cfg.allow_delete_admin:
        await state.clear()
        return await message.answer("⛔ Аккаунты администраторов нельзя удалять через бота.",
                                    reply_markup=_back(b.id))
    try:
        ok = await games.delete_account(server, acc["id"], cfg.cascade_tables)
    except Exception:  # noqa: BLE001
        return await message.answer(DB_ERROR, reply_markup=cancel_kb())
    await state.clear()
    if not ok:
        return await message.answer("❌ Не удалось удалить аккаунт.", reply_markup=_back(b.id))
    await db.delete_binding(b.id)
    await db.clear_failures(tg)
    await message.answer(f"🗑 Аккаунт <b>{h(b.nickname)}</b> удалён из базы сервера.", reply_markup=back_menu_kb())
