import random
import time

from aiogram import Bot
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.reply import chat_menu_kb
from app.core.config import settings
from app.db.repositories.profiles import ProfileRepository
from app.db.repositories.users import UserRepository
from app.services.queue import QueueService
from app.services.session_manager import SessionManager


class MatcherService:
    LOCK_KEY = "lock:match"

    def __init__(self, bot: Bot, redis: Redis, db: AsyncSession):
        self.bot = bot
        self.redis = redis
        self.db = db
        self.queue = QueueService(redis)
        self.sessions = SessionManager(redis, db)
        self.users = UserRepository(db)
        self.profiles = ProfileRepository(db)

    @staticmethod
    def _accepts(search_filter: str, gender: str | None) -> bool:
        return search_filter == "any" or search_filter == gender

    def _compatible(self, a: dict, b: dict) -> bool:
        return self._accepts(a["filter"], b.get("gender")) and self._accepts(
            b["filter"], a.get("gender")
        )

    async def add_to_queue(self, user_id: int) -> None:
        if await self.sessions.get_session_id(user_id):
            return

        # The DB profile is the source of truth for gender / filter / priority.
        user = await self.users.get(user_id)
        if user is None:
            return

        await self.queue.remove_user(user_id)
        await self.queue.push(user_id, user.gender, user.search_filter, user.priority, time.time())

    async def remove_from_queue(self, user_id: int) -> int:
        return await self.queue.remove_user(user_id)

    async def try_match_once(self) -> tuple[int, int] | None:
        lock = self.redis.lock(self.LOCK_KEY, timeout=5, blocking_timeout=1)
        async with lock:
            items = await self.queue.items()

            # Drop users that are already in a session and dedupe by user_id,
            # keeping queue order (FIFO) so longer-waiting users match first.
            candidates: list[dict] = []
            seen: set[int] = set()
            for _, item in items:
                uid = int(item["user_id"])
                if uid in seen:
                    continue
                if await self.sessions.get_session_id(uid) is not None:
                    continue
                seen.add(uid)
                candidates.append(item)

            # Higher priority first, then earlier timestamp (fairness).
            candidates.sort(key=lambda c: (-int(c["priority"]), float(c["ts"])))

            if not candidates:
                return None

            for i, first in enumerate(candidates):
                first_id = int(first["user_id"])

                # Совместимые по полу кандидаты после first (hard-фильтр обязателен).
                compatible = [c for c in candidates[i + 1:] if self._compatible(first, c)]
                if not compatible:
                    continue

                compatible_ids = [int(c["user_id"]) for c in compatible]

                # Умный матчинг: при достаточной очереди ранжируем по cosine * geo.
                if len(compatible_ids) >= settings.match_min_queue_smart:
                    profile = await self.profiles.get(first_id)
                    if profile is not None and profile.personality_vector is not None:
                        best_ids = await self.profiles.find_best_matches(
                            query_vector=list(profile.personality_vector),
                            candidate_ids=compatible_ids,
                            lat=profile.latitude,
                            lon=profile.longitude,
                            radius_km=settings.match_geo_radius_km,
                            top_k=settings.match_top_k,
                            neutral_geo_weight=settings.match_geo_neutral_weight,
                        )
                        if best_ids:
                            second_id = random.choice(best_ids)
                            return await self._pair(first_id, second_id)

                # Fallback: первый совместимый (как раньше).
                return await self._pair(first_id, int(compatible[0]["user_id"]))

            return None

    async def _pair(self, user1_id: int, user2_id: int) -> tuple[int, int]:
        await self.queue.remove_user(user1_id)
        await self.queue.remove_user(user2_id)

        await self.sessions.create(user1_id, user2_id)

        for uid in (user1_id, user2_id):
            await self.bot.send_message(
                uid,
                "Собеседник найден. Можете начинать чат.",
                reply_markup=chat_menu_kb,
            )

        return user1_id, user2_id
