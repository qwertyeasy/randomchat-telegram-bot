import asyncio
import logging

from aiogram import Router, F
from aiogram.types import Message
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import session_maker
from app.services.chat import ChatService
from app.services.profile_calibrator import ProfileCalibrator

router = Router()
logger = logging.getLogger(__name__)

# Strong refs to fire-and-forget tasks — иначе GC может убить незавершённые.
_bg_tasks: set[asyncio.Task] = set()

# Потолок одновременных torch-инференсов (module-level, один на процесс).
_NLP_SEMAPHORE = asyncio.Semaphore(settings.nlp_max_concurrent)


@router.message(F.text)
async def relay_text(message: Message, redis: Redis, db: AsyncSession) -> None:
    text = message.text

    if text in {
        "/next",
        "/stop",
        "/find",
        "/start",
        "/help",
        "/delete",
        "/complain",
        "⏭ Следующий",
        "⏹ Выйти",
        "⚠️ Пожаловаться",
        "Ищем собеседника...",
        "Собеседник найден. Можете начинать чат.",
        "Жалоба отправлена.",
        "Слишком много запросов. Подождите минуту.",
    }:
        return

    service = ChatService(message.bot, redis, db)
    await service.relay(
        user_id=message.from_user.id,
        chat_id=message.chat.id,
        message_id=message.message_id,
        text=text,
    )

    # NLP-калибровка профиля — fire and forget, чат не блокируется.
    # Семплинг: обрабатываем каждое N-е сообщение пользователя. Счётчик ведём в Redis
    # (атомарный INCR на КАЖДОЕ сообщение). На db.msg_count гейт ставить нельзя —
    # он растёт только при фактической калибровке, поэтому % N застрял бы после первого раза.
    if text and settings.nlp_enabled:
        seen = await redis.incr(f"nlp:count:{message.from_user.id}")
        if seen % settings.nlp_process_every == 0:
            task = asyncio.create_task(_calibrate_profile(message.from_user.id, text))
            _bg_tasks.add(task)
            task.add_done_callback(_bg_tasks.discard)


async def _calibrate_profile(user_id: int, text: str) -> None:
    async with _NLP_SEMAPHORE:
        try:
            calibrator = ProfileCalibrator(session_maker)
            await calibrator.calibrate(user_id, text)
        except Exception:
            logger.exception("profile calibration failed for user %d", user_id)
