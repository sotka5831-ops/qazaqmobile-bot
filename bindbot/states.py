from aiogram.fsm.state import State, StatesGroup


class BindSG(StatesGroup):
    nickname = State()
    password = State()


class AccSG(StatesGroup):
    new_password = State()
    new_pin = State()
    new_apass = State()
    delete_password = State()


class AdminSG(StatesGroup):
    name = State()
    host = State()
    port = State()
    user = State()
    password = State()
    dbname = State()
    table = State()
