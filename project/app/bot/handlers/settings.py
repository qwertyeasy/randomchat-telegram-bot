from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.reply import main_menu_kb, search_filter_kb
from app.bot.states.flow import SearchFilterState
from app.db.repositories.profiles import ProfileRepository
from app.db.repositories.users import UserRepository


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
async def filter_choice(message: Message, state: FSMContext, db: AsyncSession) -> None:
    filter_map = {
        "Мужской": "male",
        "Женский": "female",
        "Не указано": "any",
    }

    search_value = filter_map[message.text]

    repo = UserRepository(db)
    if await repo.set_search_filter(message.from_user.id, search_value) is None:
        await message.answer(
            "Сначала пройдите регистрацию через /start.",
            reply_markup=main_menu_kb,
        )
        await state.set_state(None)
        return

    await state.set_state(None)
    await message.answer(
        f"Фильтр поиска сохранён: {message.text}",
        reply_markup=main_menu_kb,
    )


@router.message(F.location)
async def save_location(message: Message, state: FSMContext, db: AsyncSession) -> None:
    """Сохраняет геолокацию пользователя в профиль (опционально, по кнопке)."""
    if message.location is None:
        return

    # Защита: если пользователь ещё в регистрации — профиля нет, геолокация недоступна.
    current_state = await state.get_state()
    if current_state is not None and current_state.startswith("StartFlow"):
        await message.answer("Сначала завершите регистрацию.")
        return

    profiles = ProfileRepository(db)
    if await profiles.get(message.from_user.id) is None:
        await state.set_state(None)
        await message.answer(
            "Сначала завершите настройку профиля через /start.",
            reply_markup=main_menu_kb,
        )
        return

    await profiles.update_location(
        message.from_user.id,
        message.location.latitude,
        message.location.longitude,
    )
    await state.set_state(None)
    # commit делает middleware
    await message.answer(
        "📍 Геолокация сохранена. Теперь алгоритм учитывает близость собеседника.",
        reply_markup=main_menu_kb,
    )


@router.message(SearchFilterState.choice)
async def filter_unknown(message: Message) -> None:
    await message.answer("Выберите значение кнопкой на клавиатуре.")