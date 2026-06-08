import enum
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import ARRAY, BigInteger, Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class GenderEnum(str, enum.Enum):
    male = "male"
    female = "female"


class SearchFilterEnum(str, enum.Enum):
    male = "male"
    female = "female"
    any = "any"


class SessionStatusEnum(str, enum.Enum):
    waiting = "waiting"
    active = "active"
    closed = "closed"


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    gender: Mapped[str] = mapped_column(Enum(GenderEnum), nullable=False)
    search_filter: Mapped[str] = mapped_column(Enum(SearchFilterEnum), nullable=False, default=SearchFilterEnum.any)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_banned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    consent_given: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    msg_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class ChatSession(Base):
    __tablename__ = "sessions"

    session_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user1_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user2_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(Enum(SessionStatusEnum), nullable=False, default=SessionStatusEnum.waiting)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Report(Base):
    __tablename__ = "reports"

    report_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    reporter_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    target_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    attached_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class Block(Base):
    __tablename__ = "blocks"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    banned_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class UserProfile(Base):
    __tablename__ = "user_profiles"

    # Aggregated recommendation profile. Holds ONLY derived signals —
    # никаких исходных текстов сообщений здесь не хранится.
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.user_id"), primary_key=True
    )
    # [energy, thinking, tone, depth, humor, joy, sadness, anger, fear, tempo, curiosity, expressiveness]
    personality_vector: Mapped[list[float]] = mapped_column(Vector(12), nullable=False)
    interest_tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    # MBTI axes: [E/I, S/N, T/F, J/P]
    mbti_scores: Mapped[list[float] | None] = mapped_column(ARRAY(Float), nullable=True)
    msg_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )