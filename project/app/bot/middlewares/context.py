from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession


class ContextMiddleware(BaseMiddleware):
    ONLINE_TTL = 300

    def __init__(self, redis: Redis, db_factory):
        super().__init__()
        self.redis = redis
        self.db_factory = db_factory

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self.db_factory() as db:
            data["redis"] = self.redis
            data["db"] = db

            from_user = getattr(event, "from_user", None)
            if from_user:
                user_id = from_user.id
                await self.redis.set(f"online:{user_id}", "1", ex=self.ONLINE_TTL)

            result = await handler(event, data)
            await db.commit()
            return result