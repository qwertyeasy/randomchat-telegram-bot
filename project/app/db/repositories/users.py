from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)

    async def upsert(self, user: User) -> User:
        existing = await self.get(user.user_id)
        if existing:
            existing.gender = user.gender
            existing.search_filter = user.search_filter
            existing.priority = user.priority
            existing.is_banned = user.is_banned
            existing.consent_given = user.consent_given
            return existing
        self.session.add(user)
        return user

    async def is_banned(self, user_id: int) -> bool:
        user = await self.get(user_id)
        return bool(user and user.is_banned)