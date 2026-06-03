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

    matcher = MatcherService(message.bot, redis, db)
    await matcher.add_to_queue(message.from_user.id, search_filter, priority)
    await message.answer("Ищем собеседника...", reply_markup=chat_menu_kb)