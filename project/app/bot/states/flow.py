from aiogram.fsm.state import State, StatesGroup


class StartFlow(StatesGroup):
    consent = State()
    gender = State()
    search_filter = State()
    idle = State()