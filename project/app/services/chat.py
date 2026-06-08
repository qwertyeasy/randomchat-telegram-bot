from aiogram import Bot
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.reply import chat_menu_kb, main_menu_kb
from app.services.matcher import MatcherService
from app.services.session_manager import SessionManager


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

    def __init__(self, bot: Bot, redis: Redis, db: AsyncSession):
        self.bot = bot
        self.redis = redis
        self.db = db
        self.sessions = SessionManager(redis, db)
        self.matcher = MatcherService(bot, redis, db)

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
            await self.sessions.close(session_id)
            await self.redis.delete(f"afk:{session_id}")

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
            await self.sessions.close(session_id)
            await self.redis.delete(f"afk:{session_id}")

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