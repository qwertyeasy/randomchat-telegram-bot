import asyncio

from aiogram import Bot
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.matcher import MatcherService


class MatchmakingWorker:
    def __init__(
        self,
        bot: Bot,
        redis: Redis,
        db_factory: async_sessionmaker[AsyncSession],
        filters: list[str] | None = None,
    ):
        self.bot = bot
        self.redis = redis
        self.db_factory = db_factory
        self.filters = filters or ["any", "male", "female"]
        self._task: asyncio.Task | None = None
        self._running = False

    async def run(self) -> None:
        self._running = True
        while self._running:
            async with self.db_factory() as db:
                matcher = MatcherService(self.bot, self.redis, db)
                for search_filter in self.filters:
                    try:
                        await matcher.try_match_once(search_filter)
                    except Exception:
                        pass
            await asyncio.sleep(1)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass