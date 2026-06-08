import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChatSession, SessionStatusEnum


class SessionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, chat_session: ChatSession) -> ChatSession:
        self.session.add(chat_session)
        return chat_session

    async def close(self, session_id: uuid.UUID, closed_at: datetime) -> ChatSession | None:
        chat_session = await self.session.get(ChatSession, session_id)
        if chat_session is None:
            return None
        chat_session.status = SessionStatusEnum.closed
        chat_session.closed_at = closed_at
        return chat_session