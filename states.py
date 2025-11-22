# states.py

from aiogram.fsm.state import StatesGroup, State


class Registration(StatesGroup):
    waiting_full_name = State()
    waiting_wish = State()
