from dataclasses import dataclass

from aiogram import Bot
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class AppContainer:
    bot: Bot
    redis: Redis
    db: AsyncSession