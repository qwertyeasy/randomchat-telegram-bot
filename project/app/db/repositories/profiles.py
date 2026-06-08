from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserProfile


class ProfileRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, user_id: int) -> UserProfile | None:
        return await self.session.get(UserProfile, user_id)

    async def create(
        self,
        user_id: int,
        initial_vector: list[float],
        *,
        interest_tags: list[str] | None = None,
        mbti_scores: list[float] | None = None,
    ) -> UserProfile:
        profile = UserProfile(
            user_id=user_id,
            personality_vector=initial_vector,
            interest_tags=interest_tags or [],
            mbti_scores=mbti_scores,
            msg_count=0,
            updated_at=datetime.utcnow(),
        )
        self.session.add(profile)
        return profile

    async def update_vector(self, user_id: int, new_vector: list[float], msg_count: int) -> None:
        profile = await self.get(user_id)
        if profile is None:
            return
        profile.personality_vector = new_vector
        profile.msg_count = msg_count
        profile.updated_at = datetime.utcnow()

    async def add_tags(self, user_id: int, tags: list[str]) -> None:
        profile = await self.get(user_id)
        if profile is None:
            return
        # Reassign a new list so SQLAlchemy detects the ARRAY change.
        merged = list(profile.interest_tags or [])
        for tag in tags:
            if tag not in merged:
                merged.append(tag)
        profile.interest_tags = merged
