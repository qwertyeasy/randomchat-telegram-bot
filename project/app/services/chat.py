from aiogram import Bot
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.matcher import MatcherService
from app.services.session_manager import SessionManager


class ChatService:
    SYSTEM_TEXTS = {
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
    }

    def __init__(self, bot: Bot, redis: Redis, db: AsyncSession):
        self.bot = bot
        self.redis = redis
        self.db = db
        self.sessions = SessionManager(redis, db)
        self.matcher = MatcherService(bot, redis, db)

    def _is_system_text(self, text: str | None) -> bool:
        return bool(text) and (text in self.SYSTEM_TEXTS or text.startswith("/"))

    async def relay(self, user_id: int, chat_id: int, message_id: int, text: str | None = None) -> None:
        if text is not None and self._is_system_text(text):
            return

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

    async def close_session(self, user_id: int) -> str | None:
        session_id = await self.sessions.get_session_id(user_id)
        if not session_id:
            return None

        await self.sessions.close(session_id)
        return session_id

    async def next_chat(self, user_id: int, search_filter: str, priority: int = 0) -> None:
        await self.stop_chat(user_id)
        await self.matcher.add_to_queue(user_id, search_filter, priority)

    async def stop_chat(self, user_id: int) -> None:
        session_id = await self.close_session(user_id)

        for flt in ("any", "male", "female"):
            await self.matcher.remove_from_queue(user_id, flt)

        if session_id:
            await self.redis.delete(f"afk:{session_id}")