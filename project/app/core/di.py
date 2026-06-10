from dataclasses import dataclass

from aiogram import Bot
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass
class AppContainer:
    bot: Bot
    redis: Redis
    db: AsyncSession
    session_maker: async_sessionmaker[AsyncSession] | None = None