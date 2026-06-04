from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot.keyboards.reply import main_menu_kb, search_filter_kb
from app.bot.states.flow import SearchFilterState


router = Router()


@router.message(Command("settings"))
@router.message(F.text == "⚙️ Настройки")
async def settings_command(message: Message, state: FSMContext) -> None:
    await state.set_state(SearchFilterState.choice)
    await message.answer(
        "Фильтр поиска:\nВыберите, кого искать.",
        reply_markup=search_filter_kb,
    )


@router.message(SearchFilterState.choice, F.text.in_({"Мужской", "Женский", "Не указано"}))
async def filter_choice(message: Message, state: FSMContext) -> None:
    filter_map = {
        "Мужской": "male",
        "Женский": "female",
        "Не указано": "any",
    }

    search_value = filter_map[message.text]
    await state.update_data(search_filter=search_value)
    await state.set_state(None)

    await message.answer(
        f"Фильтр поиска сохранён: {message.text}",
        reply_markup=main_menu_kb,
    )


@router.message(SearchFilterState.choice)
async def filter_unknown(message: Message) -> None:
    await message.answer("Выберите значение кнопкой на клавиатуре.")