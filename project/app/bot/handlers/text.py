from aiogram import Router, F
from aiogram.types import Message
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.chat import ChatService

router = Router()


@router.message(F.text)
async def relay_text(message: Message, redis: Redis, db: AsyncSession) -> None:
    text = message.text

    if text in {
        "/next",
        "/stop",
        "/find",
        "/start",
        "/help",
        "/delete",
        "⏭ Следующий",
        "⏹ Выйти",
        "Ищем собеседника...",
        "Собеседник найден. Можете начинать чат.",
        "Чат завершён.",
        "Жалоба отправлена.",
        "Слишком много запросов. Подождите минуту.",
    }:
        return

    service = ChatService(message.bot, redis, db)
    await service.relay(
        user_id=message.from_user.id,
        chat_id=message.chat.id,
        message_id=message.message_id,
        text=text,
    )