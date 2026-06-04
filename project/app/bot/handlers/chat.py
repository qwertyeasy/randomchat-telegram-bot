from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.reply import chat_menu_kb, chat_settings_kb, main_menu_kb
from app.services.chat import ChatService
from app.services.moderation import ModerationService
from app.services.session_manager import SessionManager


router = Router()


@router.message(Command("next"))
@router.message(F.text == "⏭ Следующий")
async def next_chat(message: Message, state: FSMContext, redis: Redis, db: AsyncSession) -> None:
    data = await state.get_data()
    search_filter = data.get("search_filter")
    priority = int(data.get("priority", 0))

    if search_filter is None:
        search_filter = "any"
        await state.update_data(search_filter=search_filter)

    service = ChatService(message.bot, redis, db)
    await service.next_chat(message.from_user.id, search_filter, priority)
    await state.clear()
    await state.update_data(search_filter=search_filter, priority=priority)
    await message.answer("Ищем следующего собеседника...", reply_markup=chat_menu_kb)


@router.message(Command("stop"))
@router.message(F.text == "⏹ Выйти")
async def stop_chat(message: Message, state: FSMContext, redis: Redis, db: AsyncSession) -> None:
    service = ChatService(message.bot, redis, db)
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


@router.message(F.text == "⚙️ Настройки чата")
async def chat_settings(message: Message) -> None:
    await message.answer(
        "Настройки доступа:\nЕсли хотите, можете поделиться контактом.",
        reply_markup=chat_settings_kb,
    )
    await message.delete()


@router.message(F.contact)
async def contact_shared(message: Message) -> None:
    await message.answer("Контакт получен.")