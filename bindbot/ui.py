import html

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def h(text) -> str:
    return html.escape(str(text))


def footer(cfg) -> str:
    return f"\n\n<i>💡 Автор идеи: {h(cfg.author)}</i>"


def main_kb(is_admin: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🔗 Привязать аккаунт", callback_data="bind")
    b.button(text="👤 Мои аккаунты", callback_data="accounts")
    if is_admin:
        b.button(text="🛠 Админ-панель", callback_data="adm")
    b.adjust(1)
    return b.as_markup()


def cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✖️ Отмена", callback_data="cancel")]])


def back_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]])


def account_kb(binding_id: int, show_admin: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🔑 Поменять пароль", callback_data=f"act:pw:{binding_id}")
    b.button(text="🔢 Поменять PIN-код", callback_data=f"act:pin:{binding_id}")
    if show_admin:
        b.button(text="🛡 Поменять админ-пароль", callback_data=f"act:apass:{binding_id}")
    b.button(text="🔓 Отвязать от Telegram", callback_data=f"act:unlink:{binding_id}")
    b.button(text="🗑 Удалить аккаунт", callback_data=f"act:del:{binding_id}")
    b.button(text="⬅️ К списку", callback_data="accounts")
    b.adjust(1)
    return b.as_markup()


def yes_no_kb(yes_data: str, yes_text="✅ Да") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=yes_text, callback_data=yes_data)
    b.button(text="✖️ Отмена", callback_data="cancel")
    b.adjust(1)
    return b.as_markup()
