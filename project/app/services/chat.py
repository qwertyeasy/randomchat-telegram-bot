from aiogram import Bot
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.session_manager import SessionManager


class ChatService:
    def __init__(self, bot: Bot, redis: Redis, db: AsyncSession):
        self.bot = bot
        self.redis = redis
        self.db = db
        self.sessions = SessionManager(redis, db)

    async def relay(self, user_id: int, chat_id: int, message_id: int) -> None:
        session_id = await self.sessions.get_session_id(user_id)
        if not session_id:
            return

        partner_id = await self.sessions.get_partner(session_id, user_id)
        if not partner_id:
            return

        await self.bot.copy_message(
            chat_id=partner_id,
            from_chat_id=chat_id,
            message_id=message_id,
        )
        await self.redis.set(f"afk:{session_id}", "1", ex=120)

    async def close_session(self, user_id: int) -> None:
        session_id = await self.sessions.get_session_id(user_id)
        if session_id:
            await self.sessions.close(session_id)
            return session_id
        return None

    async def notify_closed(self, user_id: int, text: str) -> None:
        await self.bot.send_message(user_id, text)