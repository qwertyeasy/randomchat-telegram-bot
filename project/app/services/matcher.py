from datetime import datetime

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.queue import QueueService
from app.services.session_manager import SessionManager


class MatcherService:
    def __init__(self, redis: Redis, db: AsyncSession):
        self.redis = redis
        self.db = db
        self.queue = QueueService(redis)
        self.sessions = SessionManager(redis, db)

    async def add_to_queue(self, user_id: int, search_filter: str, priority: int) -> None:
        await self.queue.push(search_filter, user_id, priority, datetime.utcnow().timestamp())

    async def try_match(self, user_id: int, search_filter: str) -> int | None:
        partner = await self.queue.pop(search_filter)
        if not partner:
            return None

        partner_id = int(partner["user_id"])
        if partner_id == user_id:
            return None

        await self.sessions.create(user_id, partner_id)
        return partner_id

    async def remove_from_queue(self, user_id: int, search_filter: str) -> None:
        await self.queue.remove_user(search_filter, user_id)