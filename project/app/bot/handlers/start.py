from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.onboarding import start_onboarding
from app.bot.keyboards.reply import consent_kb, gender_kb, search_filter_kb, main_menu_kb
from app.bot.states.flow import StartFlow
from app.db.models import User
from app.db.repositories.profiles import ProfileRepository
from app.db.repositories.users import UserRepository


router = Router()


@router.message(CommandStart())
async def start(message: Message, state: FSMContext, db: AsyncSession) -> None:
    repo = UserRepository(db)
    existing = await repo.get(message.from_user.id)

    if existing and existing.is_banned:
        await message.answer("Доступ запрещён.")
        return

    await state.set_state(StartFlow.consent)
    await message.answer(
        "Привет. Для работы бота нужно согласие на обработку данных.",
        reply_markup=consent_kb,
    )


@router.message(StartFlow.consent, F.text == "✅ Принимаю")
async def consent(message: Message, state: FSMContext, db: AsyncSession) -> None:
    await state.update_data(consent_given=True)
    await state.set_state(StartFlow.gender)
    await message.answer("Укажи свой пол:", reply_markup=gender_kb)


@router.message(StartFlow.gender, F.text.in_(["Мужчина", "Женщина"]))
async def gender(message: Message, state: FSMContext, db: AsyncSession) -> None:
    gender_value = "male" if message.text == "Мужчина" else "female"
    await state.update_data(gender=gender_value)
    await state.set_state(StartFlow.search_filter)
    await message.answer("Выбери фильтр поиска:", reply_markup=search_filter_kb)


@router.message(StartFlow.search_filter, F.text.in_(["Мужской", "Женский", "Не указано"]))
async def search_filter(message: Message, state: FSMContext, db: AsyncSession) -> None:
    filter_map = {
        "Мужской": "male",
        "Женский": "female",
        "Не указано": "any",
    }
    data = await state.get_data()
    gender_value = data.get("gender", "male")
    consent_given = data.get("consent_given", False)
    search_value = filter_map[message.text]

    repo = UserRepository(db)
    user = await repo.get(message.from_user.id)
    if user is None:
        user = User(
            user_id=message.from_user.id,
            gender=gender_value,
            search_filter=search_value,
            priority=0,
            is_banned=False,
            consent_given=consent_given,
        )
    else:
        user.gender = gender_value
        user.search_filter = search_value
        user.consent_given = consent_given

    await repo.upsert(user)
    await db.commit()

    await state.update_data(search_filter=search_value, priority=0)

    # Phase 2: first-time users go through the recommendation onboarding.
    profiles = ProfileRepository(db)
    if await profiles.get(message.from_user.id) is None:
        await start_onboarding(message, state)
    else:
        await state.set_state(StartFlow.idle)
        await message.answer("Готово. Используй поиск чата.", reply_markup=main_menu_kb)