from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from aiogram.types import Update
from fastapi import FastAPI, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bot.middlewares.context import ContextMiddleware
from app.bot.router import router
from app.core.config import settings
from app.services.cleanup import CleanupService
from app.services.matchmaking_worker import MatchmakingWorker

engine = create_async_engine(settings.database_url, echo=False)
session_maker = async_sessionmaker(engine, expire_on_commit=False)

redis = Redis.from_url(settings.redis_url, decode_responses=True)
bot = Bot(token=settings.bot_token)
dp = Dispatcher()
dp.include_router(router)
dp.update.middleware(ContextMiddleware(redis=redis, db_factory=session_maker))

cleanup = CleanupService(redis, session_maker)
matchmaking = MatchmakingWorker(bot, redis, session_maker)


@asynccontextmanager
async def lifespan(app: FastAPI):
    cleanup.start()
    matchmaking.start()
    yield
    await matchmaking.stop()
    await cleanup.stop()
    await bot.session.close()
    await redis.aclose()
    await engine.dispose()


app = FastAPI(lifespan=lifespan)


@app.post(settings.webhook_path)
async def telegram_webhook(request: Request) -> dict:
    data = await request.json()
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return {"ok": True}