from aiogram import F, Router
from aiogram.filters import Command, Filter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..common import safe_delete
from ..config import Config
from ..gamedb import GameDB
from ..states import AdminSG
from ..storage import Storage
from ..ui import cancel_kb, h


class IsAdmin(Filter):
    async def __call__(self, event, cfg: Config) -> bool:
        user = getattr(event, "from_user", None)
        return bool(user and user.id in cfg.admin_ids)


router = Router()
router.message.filter(F.chat.type == "private", IsAdmin())
router.callback_query.filter(IsAdmin())


def _panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🖥 Серверы", callback_data="adm_srv")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="adm_stats")],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]])


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🛠 <b>Админ-панель</b>", reply_markup=_panel_kb())


@router.callback_query(F.data == "adm")
async def cb_admin(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("🛠 <b>Админ-панель</b>", reply_markup=_panel_kb())
    await call.answer()


@router.callback_query(F.data == "adm_stats")
async def cb_stats(call: CallbackQuery, db: Storage):
    servers = await db.list_servers()
    per = await db.bindings_per_server()
    lines = [f"{'🟢' if s.enabled else '🔴'} {h(s.name)}: привязок {per.get(s.id, 0)}" for s in servers]
    text = "📊 <b>Статистика</b>\n\n" + ("\n".join(lines) if lines else "Серверов нет.")
    await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="adm")]]))
    await call.answer()


@router.callback_query(F.data == "adm_srv")
async def cb_servers(call: CallbackQuery, state: FSMContext, db: Storage):
    await state.clear()
    servers = await db.list_servers()
    rows = [[InlineKeyboardButton(text=f"{'🟢' if s.enabled else '🔴'} {s.name}", callback_data=f"adm_s:{s.id}")]
            for s in servers]
    rows.append([InlineKeyboardButton(text="➕ Добавить сервер", callback_data="adm_add")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="adm")])
    await call.message.edit_text("🖥 <b>Серверы</b> (🟢 — доступен для выбора в боте):",
                                 reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await call.answer()


async def _show_server(call: CallbackQuery, db: Storage, server_id: int, note: str = ""):
    s = await db.get_server(server_id)
    if s is None:
        return await call.answer("Сервер не найден", show_alert=True)
    text = (f"🖥 <b>{h(s.name)}</b> {'🟢 включён' if s.enabled else '🔴 выключен'}\n"
            f"Хост: <code>{h(s.host)}:{s.port}</code>\nБаза: <code>{h(s.db_name)}</code>\n"
            f"Пользователь: <code>{h(s.db_user)}</code>\nТаблица: <code>{h(s.table)}</code>")
    if note:
        text += f"\n\n{note}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔌 Проверить подключение", callback_data=f"adm_test:{s.id}")],
        [InlineKeyboardButton(text="🔴 Выключить" if s.enabled else "🟢 Включить", callback_data=f"adm_tog:{s.id}")],
        [InlineKeyboardButton(text="🗑 Удалить сервер", callback_data=f"adm_del:{s.id}")],
        [InlineKeyboardButton(text="⬅️ К серверам", callback_data="adm_srv")]])
    await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data.regexp(r"^adm_s:\d+$"))
async def cb_server(call: CallbackQuery, db: Storage):
    await _show_server(call, db, int(call.data.split(":")[1]))


@router.callback_query(F.data.regexp(r"^adm_tog:\d+$"))
async def cb_toggle(call: CallbackQuery, db: Storage):
    sid = int(call.data.split(":")[1])
    await db.toggle_server(sid)
    await _show_server(call, db, sid)


@router.callback_query(F.data.regexp(r"^adm_test:\d+$"))
async def cb_test(call: CallbackQuery, db: Storage, games: GameDB):
    sid = int(call.data.split(":")[1])
    s = await db.get_server(sid)
    if s is None:
        return await call.answer("Сервер не найден", show_alert=True)
    err = await games.test(s)
    await _show_server(call, db, sid, "✅ Подключение успешно." if not err else f"❌ Ошибка: <code>{h(err)[:300]}</code>")


@router.callback_query(F.data.regexp(r"^adm_del:\d+$"))
async def cb_delete_ask(call: CallbackQuery):
    sid = int(call.data.split(":")[1])
    await call.message.edit_text(
        "Удалить сервер вместе со всеми привязками к нему? Аккаунты в самой игре не затрагиваются.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Да, удалить", callback_data=f"adm_delyes:{sid}")],
            [InlineKeyboardButton(text="✖️ Отмена", callback_data=f"adm_s:{sid}")]]))
    await call.answer()


@router.callback_query(F.data.regexp(r"^adm_delyes:\d+$"))
async def cb_delete(call: CallbackQuery, state: FSMContext, db: Storage, games: GameDB):
    sid = int(call.data.split(":")[1])
    await games.drop(sid)
    await db.delete_server(sid)
    await cb_servers(call, state, db)


# ---------- добавление сервера ----------
STEPS = [
    (AdminSG.name, "name", "Введите <b>название сервера</b> (его увидят игроки):"),
    (AdminSG.host, "host", "Введите <b>хост MySQL</b> (например 127.0.0.1):"),
    (AdminSG.port, "port", "Введите <b>порт MySQL</b> (обычно 3306):"),
    (AdminSG.user, "user", "Введите <b>пользователя MySQL</b>:"),
    (AdminSG.password, "password", "Введите <b>пароль MySQL</b> (сообщение будет удалено):"),
    (AdminSG.dbname, "dbname", "Введите <b>название базы данных</b>:"),
    (AdminSG.table, "table", "Введите <b>таблицу с аккаунтами</b> (обычно <code>accounts</code>):"),
]


@router.callback_query(F.data == "adm_add")
async def cb_add(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(STEPS[0][0])
    await call.message.edit_text(STEPS[0][2], reply_markup=cancel_kb())
    await call.answer()


async def _next(message: Message, state: FSMContext, db: Storage, games: GameDB, idx: int):
    if idx + 1 < len(STEPS):
        await state.set_state(STEPS[idx + 1][0])
        return await message.answer(STEPS[idx + 1][2], reply_markup=cancel_kb())
    d = await state.get_data()
    await state.clear()
    sid = await db.add_server(d["name"], d["host"], int(d["port"]), d["user"], d["password"], d["dbname"], d["table"])
    s = await db.get_server(sid)
    err = await games.test(s)
    if err:
        await db.toggle_server(sid)  # выключаем, пока подключение не работает
        text = f"⚠️ Сервер сохранён, но подключиться не удалось (выключен):\n<code>{h(err)[:300]}</code>"
    else:
        text = f"✅ Сервер <b>{h(s.name)}</b> добавлен, подключение работает."
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🖥 К серверам", callback_data="adm_srv")]]))


def _make_step(idx: int):
    st, key, _ = STEPS[idx]

    @router.message(st, F.text)
    async def handler(message: Message, state: FSMContext, db: Storage, games: GameDB):
        value = message.text.strip()
        if key == "password":
            await safe_delete(message)
        if key == "port" and not (value.isdigit() and 1 <= int(value) <= 65535):
            return await message.answer("Порт — число от 1 до 65535. Введите ещё раз:", reply_markup=cancel_kb())
        if key == "table":
            import re
            if not re.fullmatch(r"[A-Za-z0-9_]+", value):
                return await message.answer("Только латиница, цифры и _. Введите ещё раз:", reply_markup=cancel_kb())
        if not value:
            return await message.answer("Пустое значение. Введите ещё раз:", reply_markup=cancel_kb())
        await state.update_data(**{key: value})
        await _next(message, state, db, games, idx)

    handler.__name__ = f"admin_step_{key}"
    return handler


for _i in range(len(STEPS)):
    _make_step(_i)
