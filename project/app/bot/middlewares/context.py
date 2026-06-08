from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from redis.asyncio import Redis


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

            # `event` here is an Update, which has no `from_user`; aiogram exposes
            # the actual sender via `event_from_user` in the middleware data.
            user = data.get("event_from_user") or getattr(event, "from_user", None)
            if user is not None:
                await self.redis.set(f"online:{user.id}", "1", ex=self.ONLINE_TTL)

            result = await handler(event, data)
            await db.commit()
            return result