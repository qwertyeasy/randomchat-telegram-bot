from aiogram.fsm.state import State, StatesGroup


class StartFlow(StatesGroup):
    consent = State()
    gender = State()
    search_filter = State()
    idle = State()

class SearchFilterState(StatesGroup):
    choice = State()


class Onboarding(StatesGroup):
    q1 = State()
    q2 = State()
    q3 = State()
    q4 = State()
    q5 = State()