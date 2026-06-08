import asyncio
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bot.middlewares.context import ContextMiddleware
from app.bot.router import router
from app.core.config import settings
from app.services.cleanup import CleanupService
from app.services.matchmaking_worker import MatchmakingWorker
from app.services.nlp_processor import NLPProcessor

engine = create_async_engine(settings.database_url, echo=False)
session_maker = async_sessionmaker(engine, expire_on_commit=False)

redis = Redis.from_url(settings.redis_url, decode_responses=True)
bot = Bot(token=settings.bot_token)
dp = Dispatcher()
dp.include_router(router)
dp.update.middleware(ContextMiddleware(redis=redis, db_factory=session_maker))

cleanup = CleanupService(redis, session_maker)
matchmaking = MatchmakingWorker(bot, redis, session_maker)

polling_task: asyncio.Task | None = None


async def polling_runner() -> None:
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, close_bot_session=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global polling_task

    cleanup.start()
    matchmaking.start()
    polling_task = asyncio.create_task(polling_runner())

    # Прогрев NLP-моделей заранее, чтобы первый пользователь не ждал загрузку весов.
    # run_in_executor возвращает Future (не корутину) — НЕ оборачивать в create_task.
    if settings.nlp_enabled:
        asyncio.get_event_loop().run_in_executor(None, NLPProcessor.warmup)

    try:
        yield
    finally:
        if polling_task:
            polling_task.cancel()
            try:
                await polling_task
            except asyncio.CancelledError:
                pass

        await matchmaking.stop()
        await cleanup.stop()
        await bot.session.close()
        await redis.aclose()
        await engine.dispose()


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def root() -> dict:
    return {"status": "ok"}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}