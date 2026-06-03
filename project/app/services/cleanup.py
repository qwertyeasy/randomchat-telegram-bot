import asyncio

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class CleanupService:
    def __init__(self, redis: Redis, db_factory: async_sessionmaker[AsyncSession]):
        self.redis = redis
        self.db_factory = db_factory
        self._task: asyncio.Task | None = None

    async def run(self) -> None:
        while True:
            keys = await self.redis.keys("afk:*")
            for key in keys:
                ttl = await self.redis.ttl(key)
                if ttl == -2:
                    continue
                if ttl == -1:
                    await self.redis.expire(key, 120)
            await asyncio.sleep(30)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass