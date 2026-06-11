import asyncio
import logging
from datetime import datetime

from aiogram import Bot
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.keyboards.reply import chat_menu_kb, main_menu_kb
from app.core.config import settings
from app.services.matcher import MatcherService
from app.services.session_manager import SessionManager

logger = logging.getLogger(__name__)


class ChatService:
    SYSTEM_TEXTS = {
        "/next",
        "/stop",
        "/find",
        "/start",
        "/help",
        "/delete",
        "⏭ Следующий",
        "⏹ Выйти",
        "Ищем собеседника...",
        "Собеседник найден. Можете начинать чат.",
        "Чат завершён.",
        "Жалоба отправлена.",
        "Слишком много запросов. Подождите минуту.",
    }

    def __init__(
        self,
        bot: Bot,
        redis: Redis,
        db: AsyncSession,
        session_maker: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.bot = bot
        self.redis = redis
        self.db = db
        self.session_maker = session_maker  # для fire-and-forget фидбэка (Фаза 6)
        self.sessions = SessionManager(redis, db)
        self.matcher = MatcherService(bot, redis, db)
        self._bg_tasks: set[asyncio.Task] = set()

    def _is_system_text(self, text: str | None) -> bool:
        return bool(text) and (text in self.SYSTEM_TEXTS)

    async def get_active_users_count(self, exclude_user_id: int | None = None) -> int:
        online: set[str] = set()
        cursor = 0
        while True:
            cursor, keys = await self.redis.scan(cursor=cursor, match="online:*", count=200)
            online.update(keys)
            if cursor == 0:
                break
        if exclude_user_id is not None:
            online.discard(f"online:{exclude_user_id}")
        return len(online)

    async def start_search(self, user_id: int) -> None:
        active_users = await self.get_active_users_count(exclude_user_id=user_id)
        await self.matcher.add_to_queue(user_id)

        await self.bot.send_message(
            user_id,
            f"Активные пользователи: {active_users}\nИщем собеседника...",
            reply_markup=chat_menu_kb,
        )

    async def relay(self, user_id: int, chat_id: int, message_id: int, text: str | None = None) -> None:
        if text is not None and self._is_system_text(text):
            return

        session_id = await self.sessions.get_session_id(user_id)
        if not session_id:
            return

        partner_id = await self.sessions.get_partner(session_id, user_id)
        if not partner_id:
            return

        await self.bot.copy_message(
            chat_id=partner_id,
            from_chat_id=chat_id,
            message_id=message_id,
        )
        await self.redis.set(f"afk:{session_id}", "1", ex=120)

        # Per-session счётчик сообщений для фидбэка (Фаза 6). Гейтим, чтобы при
        # выключенной фиче ключи без TTL не накапливались.
        if settings.feedback_enabled:
            await self.redis.incr(f"smsg:{session_id}")

    async def close_session(self, user_id: int) -> str | None:
        session_id = await self.sessions.get_session_id(user_id)
        if not session_id:
            return None

        await self.sessions.close(session_id)
        return session_id

    async def next_chat(self, user_id: int) -> int | None:
        session_id = await self.sessions.get_session_id(user_id)
        partner_id = None

        if session_id:
            partner_id = await self.sessions.get_partner(session_id, user_id)
            session_data = await self.sessions.close(session_id)
            await self.redis.delete(f"afk:{session_id}")
            await self._fire_feedback(session_id, session_data)

        await self.matcher.remove_from_queue(user_id)
        if partner_id:
            await self.matcher.remove_from_queue(partner_id)

        if partner_id:
            await self.bot.send_message(
                partner_id,
                "Собеседник перешёл к следующему. Чат завершён.",
                reply_markup=main_menu_kb,
            )

        await self.start_search(user_id)
        return partner_id

    async def stop_chat(self, user_id: int) -> int | None:
        session_id = await self.sessions.get_session_id(user_id)
        partner_id = None

        if session_id:
            partner_id = await self.sessions.get_partner(session_id, user_id)
            session_data = await self.sessions.close(session_id)
            await self.redis.delete(f"afk:{session_id}")
            await self._fire_feedback(session_id, session_data)

        await self.matcher.remove_from_queue(user_id)
        if partner_id:
            await self.matcher.remove_from_queue(partner_id)

        if partner_id:
            await self.bot.send_message(
                partner_id,
                "Собеседник вышел. Чат завершён.",
                reply_markup=main_menu_kb,
            )

        return partner_id

    async def _fire_feedback(self, session_id: str, session_data: dict) -> None:
        """Считать сигналы сессии из Redis и fire-and-forget записать исход (Фаза 6)."""
        if self.session_maker is None or not settings.feedback_enabled:
            return
        if not session_data:
            return

        try:
            user1_id = int(session_data.get("user1_id", 0))
            user2_id = int(session_data.get("user2_id", 0))
        except (TypeError, ValueError):
            return
        if not (user1_id and user2_id):
            return

        msg_count = int(await self.redis.get(f"smsg:{session_id}") or 0)
        contact_shared = bool(await self.redis.get(f"contact:{session_id}"))

        duration_sec = 0
        started_raw = session_data.get("started_at")
        if started_raw:
            try:
                duration_sec = int((datetime.utcnow() - datetime.fromisoformat(started_raw)).total_seconds())
            except ValueError:
                duration_sec = 0

        await self.redis.delete(f"smsg:{session_id}", f"contact:{session_id}")

        from app.services.feedback import FeedbackService

        feedback = FeedbackService(self.session_maker)
        task = asyncio.create_task(
            feedback.record(
                session_id, user1_id, user2_id, msg_count, duration_sec, contact_shared,
                settings.early_exit_threshold,
            )
        )
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def end_chat_for_user(self, user_id: int, reason: str = "Чат завершен") -> None:
        partner_id = await self.redis.get(f"chat:partner:{user_id}")

        await self._clear_user_state(user_id)
        await self._send_menu(user_id, reason)

        if partner_id:
            partner_id = int(partner_id)
            await self._clear_user_state(partner_id)
            await self._send_menu(partner_id, "Собеседник вышел. Чат завершен.")

    async def _clear_user_state(self, user_id: int) -> None:
        await self.redis.delete(f"chat:partner:{user_id}")
        await self.redis.delete(f"chat:state:{user_id}")
        await self.redis.delete(f"chat:room:{user_id}")

    async def _send_menu(self, user_id: int, text: str) -> None:
        await self.bot.send_message(
            user_id,
            text,
            reply_markup=main_menu_kb,
        )