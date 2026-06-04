import time

from aiogram import Bot
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.reply import chat_menu_kb
from app.services.queue import QueueService
from app.services.session_manager import SessionManager


class MatcherService:
    def __init__(self, bot: Bot, redis: Redis, db: AsyncSession):
        self.bot = bot
        self.redis = redis
        self.db = db
        self.queue = QueueService(redis)
        self.sessions = SessionManager(redis, db)

    def _lock_key(self, search_filter: str) -> str:
        return f"lock:match:{search_filter}"

    async def add_to_queue(self, user_id: int, search_filter: str, priority: int) -> None:
        if await self.sessions.get_session_id(user_id):
            return
        await self.queue.remove_user(search_filter, user_id)
        await self.queue.push(search_filter, user_id, priority, time.time())

    async def remove_from_queue(self, user_id: int, search_filter: str) -> int:
        return await self.queue.remove_user(search_filter, user_id)

    async def try_match_once(self, search_filter: str) -> tuple[int, int] | None:
        lock = self.redis.lock(self._lock_key(search_filter), timeout=5, blocking_timeout=1)
        async with lock:
            items = await self.redis.lrange(f"queue:{search_filter}", 0, -1)
            if len(items) < 2:
                return None

            parsed: list[int] = []
            for raw in items:
                item = self.queue._decode(raw)
                uid = int(item["user_id"])
                if await self.sessions.get_session_id(uid) is None and uid not in parsed:
                    parsed.append(uid)

            if len(parsed) < 2:
                return None

            user1_id = parsed[0]
            user2_id = parsed[1]

            await self.queue.remove_user(search_filter, user1_id)
            await self.queue.remove_user(search_filter, user2_id)

            await self.sessions.create(user1_id, user2_id)

            await self.bot.send_message(
                user1_id,
                "Собеседник найден. Можете начинать чат.",
                reply_markup=chat_menu_kb,
            )
            await self.bot.send_message(
                user2_id,
                "Собеседник найден. Можете начинать чат.",
                reply_markup=chat_menu_kb,
            )

            return user1_id, user2_id