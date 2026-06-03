from aiogram import Router, F
from aiogram.types import Message
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.chat import ChatService

router = Router()


@router.message(F.photo)
async def relay_photo(message: Message, redis: Redis, db: AsyncSession) -> None:
    service = ChatService(message.bot, redis, db)
    await service.relay(message.from_user.id, message.chat.id, message.message_id)


@router.message(F.voice)
async def relay_voice(message: Message, redis: Redis, db: AsyncSession) -> None:
    service = ChatService(message.bot, redis, db)
    await service.relay(message.from_user.id, message.chat.id, message.message_id)


@router.message(F.video_note)
async def relay_video_note(message: Message, redis: Redis, db: AsyncSession) -> None:
    service = ChatService(message.bot, redis, db)
    await service.relay(message.from_user.id, message.chat.id, message.message_id)