from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..config import Config
from ..ui import footer, h, main_kb

router = Router()
router.message.filter(F.chat.type == "private")


def _welcome(cfg: Config) -> str:
    return ("👋 <b>QAZAQ MOBILE</b>\n<i>Игровой аккаунтты Telegram-ға байланыстыру</i>\n\n"
            "Привяжите аккаунт к Telegram, чтобы менять пароль, PIN-код и админ-пароль, "
            "отвязать или удалить аккаунт прямо из бота." + footer(cfg))


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, cfg: Config):
    await state.clear()
    await message.answer(_welcome(cfg), reply_markup=main_kb(message.from_user.id in cfg.admin_ids))


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, cfg: Config):
    await state.clear()
    await message.answer("Отменено.", reply_markup=main_kb(message.from_user.id in cfg.admin_ids))


@router.message(Command("about"))
async def cmd_about(message: Message, cfg: Config):
    await message.answer(
        f"🤖 <b>QAZAQ MOBILE</b>\\n"
        f"Telegram: @qazaqmobilee01\\n"
        f"Әзірлеуші: <b>{h(cfg.author)}</b>"
    )


@router.callback_query(F.data == "menu")
async def cb_menu(call: CallbackQuery, state: FSMContext, cfg: Config):
    await state.clear()
    await call.message.edit_text(_welcome(cfg), reply_markup=main_kb(call.from_user.id in cfg.admin_ids))
    await call.answer()


@router.callback_query(F.data == "cancel")
async def cb_cancel(call: CallbackQuery, state: FSMContext, cfg: Config):
    await state.clear()
    await call.message.edit_text("Отменено.", reply_markup=main_kb(call.from_user.id in cfg.admin_ids))
    await call.answer()
