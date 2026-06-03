from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChatSession


class SessionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, chat_session: ChatSession) -> ChatSession:
        self.session.add(chat_session)
        return chat_session