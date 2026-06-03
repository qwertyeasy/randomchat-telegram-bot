from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.reply import chat_menu_kb
from app.services.matcher import MatcherService
from app.services.rate_limit import RateLimitService

router = Router()


@router.message(Command("find"))
@router.message(F.text == "🔍 Найти чат")
async def find_chat(
    message: Message,
    state: FSMContext,
    redis: Redis,
    db: AsyncSession,
) -> None:
    data = await state.get_data()
    search_filter = data.get("search_filter", "any")
    priority = int(data.get("priority", 0))

    rl = RateLimitService(redis)
    if not await rl.check(message.from_user.id):
        await message.answer("Слишком много запросов. Подождите минуту.")
        return

    matcher = MatcherService(redis, db)
    await matcher.add_to_queue(message.from_user.id, search_filter, priority)
    partner_id = await matcher.try_match(message.from_user.id, search_filter)

    if partner_id:
        await message.answer("Собеседник найден.", reply_markup=chat_menu_kb)
    else:
        await message.answer("Ищем собеседника...")

@router.message(Command("stop"))
@router.message(F.text == "⏹ Выйти")
async def stop_from_queue_or_chat(message: Message, redis: Redis, db: AsyncSession) -> None:
    matcher = MatcherService(redis, db)
    await matcher.remove_from_queue(message.from_user.id, "any")
    chat = matcher.sessions
    await chat.close(message.from_user.id) if await chat.get_session_id(message.from_user.id) else None
    await message.answer("Поиск остановлен.", reply_markup=chat_menu_kb)