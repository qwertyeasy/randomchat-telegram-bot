from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import session_maker
from app.services.chat import ChatService

router = Router()


@router.message(Command("stop"))
@router.message(F.text == "⏹ Выйти")
async def stop_command(message: Message, state: FSMContext, redis: Redis, db: AsyncSession) -> None:
    chat_service = ChatService(message.bot, redis, db, session_maker=session_maker)
    await chat_service.stop_chat(message.from_user.id)
    await state.clear()


@router.callback_query(F.data == "stop")
async def stop_callback(callback: CallbackQuery, state: FSMContext, redis: Redis, db: AsyncSession) -> None:
    chat_service = ChatService(callback.bot, redis, db, session_maker=session_maker)
    await chat_service.stop_chat(callback.from_user.id)
    await state.clear()
    await callback.answer()