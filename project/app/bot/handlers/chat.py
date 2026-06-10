from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.reply import chat_menu_kb, main_menu_kb
from app.db.session import session_maker
from app.services.chat import ChatService
from app.services.moderation import ModerationService
from app.services.session_manager import SessionManager


router = Router()


@router.message(Command("find"))
@router.message(F.text == "🔍 Найти чат")
async def find_chat(message: Message, state: FSMContext, redis: Redis, db: AsyncSession) -> None:
    service = ChatService(message.bot, redis, db, session_maker=session_maker)
    await service.start_search(message.from_user.id)
    await state.set_state(None)


@router.message(Command("next"))
@router.message(F.text == "⏭ Следующий")
async def next_chat(message: Message, state: FSMContext, redis: Redis, db: AsyncSession) -> None:
    service = ChatService(message.bot, redis, db, session_maker=session_maker)
    await service.next_chat(message.from_user.id)
    await state.set_state(None)


@router.message(Command("stop"))
@router.message(F.text == "⏹ Выйти")
async def stop_chat(message: Message, state: FSMContext, redis: Redis, db: AsyncSession) -> None:
    service = ChatService(message.bot, redis, db, session_maker=session_maker)
    await service.stop_chat(message.from_user.id)
    await state.clear()
    await message.answer("Чат завершён.", reply_markup=main_menu_kb)


@router.message(Command("complain"))
@router.message(F.text == "⚠️ Пожаловаться")
async def report(message: Message, redis: Redis, db: AsyncSession) -> None:
    session_manager = SessionManager(redis, db)
    session_id = await session_manager.get_session_id(message.from_user.id)
    if not session_id:
        await message.answer("Сначала нужно находиться в чате.")
        return

    partner_id = await session_manager.get_partner(session_id, message.from_user.id)
    if not partner_id:
        await message.answer("Не удалось определить собеседника.")
        return

    mod = ModerationService(db)
    await mod.create_report(
        session_id=session_id,
        reporter_id=message.from_user.id,
        target_id=partner_id,
        reason="Жалоба через кнопку",
        attached_message=None,
    )
    await message.answer("Жалоба отправлена.")
