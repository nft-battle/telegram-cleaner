from aiogram.fsm.state import State, StatesGroup


class LoginFSM(StatesGroup):
    phone = State()
    code = State()
    password = State()