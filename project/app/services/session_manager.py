import uuid
from datetime import datetime

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChatSession, SessionStatusEnum
from app.db.repositories.sessions import SessionRepository


class SessionManager:
    def __init__(self, redis: Redis, db: AsyncSession):
        self.redis = redis
        self.db = db
        self.sessions = SessionRepository(db)

    async def create(self, user1_id: int, user2_id: int) -> uuid.UUID:
        session_id = uuid.uuid4()
        session = ChatSession(
            session_id=session_id,
            user1_id=user1_id,
            user2_id=user2_id,
            status=SessionStatusEnum.active,
            created_at=datetime.utcnow(),
        )
        await self.sessions.create(session)
        await self.db.commit()

        await self.redis.hset(
            f"session:{session_id}",
            mapping={"user1_id": user1_id, "user2_id": user2_id, "status": "active"},
        )
        await self.redis.set(f"user:{user1_id}:session", str(session_id))
        await self.redis.set(f"user:{user2_id}:session", str(session_id))
        await self.redis.set(f"afk:{session_id}", "1", ex=120)
        return session_id

    async def get_partner(self, session_id: str, user_id: int) -> int | None:
        data = await self.redis.hgetall(f"session:{session_id}")
        if not data:
            return None
        u1 = int(data["user1_id"])
        u2 = int(data["user2_id"])
        if user_id == u1:
            return u2
        if user_id == u2:
            return u1
        return None

    async def get_session_id(self, user_id: int) -> str | None:
        return await self.redis.get(f"user:{user_id}:session")

    async def close(self, session_id: str) -> None:
        data = await self.redis.hgetall(f"session:{session_id}")
        if data:
            for uid in (data.get("user1_id"), data.get("user2_id")):
                if uid:
                    await self.redis.delete(f"user:{uid}:session")
        await self.redis.delete(f"session:{session_id}")
        await self.redis.delete(f"afk:{session_id}")