"""Phase 6 — запись исходов сессий и обновление матрицы совместимости M.

Запускается fire-and-forget из ChatService. Открывает собственную DB-сессию.
Тексты сообщений не хранятся — только агрегированные сигналы.
Векторы пользователей НЕ трогаются (их меняет только NLP, Фаза 3).
"""
import logging
import math
import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import SessionOutcome
from app.db.repositories.matrix import MatrixRepository
from app.db.repositories.outcomes import OutcomeRepository
from app.db.repositories.profiles import ProfileRepository

logger = logging.getLogger(__name__)

_DIMS = 12


def compute_success_score(
    msg_count: int,
    duration_sec: int,
    contact_shared: bool,
    early_exit: bool,
) -> float:
    """Исход сессии → success_score ∈ [0, 1].

    Веса (настраивать экспериментально):
      0.35 · log(msg+1)           — объём переписки
      0.25 · min(dur/300, 1.0)    — длительность (насыщение на 5 мин)
      0.50 · contact_shared       — самый сильный сигнал
     -0.40 · early_exit           — штраф за быстрый уход
    """
    raw = (
        0.35 * math.log(msg_count + 1)
        + 0.25 * min(duration_sec / 300.0, 1.0)
        + 0.50 * float(contact_shared)
        - 0.40 * float(early_exit)
    )
    return max(0.0, min(1.0, raw / 1.1))


def update_matrix(
    M: list[float],
    sample_count: int,
    v1: list[float],
    v2: list[float],
    success_score: float,
) -> list[float]:
    """Обновить M по одному исходу (Hebbian update).

    delta_M = lr · (success_score - 0.5) · outer(v1_norm, v2_norm)
    success > 0.5 усиливает паттерн пары, < 0.5 ослабляет.
    lr убывает с ростом sample_count. Элементы clamp(-2.0, 2.0).
    """
    n = _DIMS
    lr = 0.005 / math.sqrt(sample_count + 1)
    delta = success_score - 0.5

    norm1 = math.sqrt(sum(x * x for x in v1)) or 1.0
    norm2 = math.sqrt(sum(x * x for x in v2)) or 1.0
    v1n = [x / norm1 for x in v1]
    v2n = [x / norm2 for x in v2]

    M_new = list(M)
    for i in range(n):
        for j in range(n):
            idx = i * n + j
            M_new[idx] = max(-2.0, min(2.0, M_new[idx] + lr * delta * v1n[i] * v2n[j]))
    return M_new


class FeedbackService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def record(
        self,
        session_id: str,
        user1_id: int,
        user2_id: int,
        msg_count: int,
        duration_sec: int,
        contact_shared: bool,
        early_exit_threshold: int = 5,
    ) -> None:
        """Записать исход сессии и обновить матрицу M. Fire-and-forget."""
        try:
            early_exit = msg_count < early_exit_threshold
            score = compute_success_score(msg_count, duration_sec, contact_shared, early_exit)

            async with self.session_factory() as db:
                outcome = SessionOutcome(
                    session_id=uuid.UUID(session_id),
                    user1_id=user1_id,
                    user2_id=user2_id,
                    msg_count_total=msg_count,
                    duration_sec=duration_sec,
                    contact_shared=contact_shared,
                    early_exit=early_exit,
                    success_score=score,
                    created_at=datetime.utcnow(),
                )
                await OutcomeRepository(db).create(outcome)

                profile_repo = ProfileRepository(db)
                p1 = await profile_repo.get(user1_id)
                p2 = await profile_repo.get(user2_id)

                if p1 is not None and p2 is not None:
                    matrix_repo = MatrixRepository(db)
                    m_obj = await matrix_repo.get()
                    new_matrix = update_matrix(
                        m_obj.matrix,
                        m_obj.sample_count,
                        list(p1.personality_vector),
                        list(p2.personality_vector),
                        score,
                    )
                    await matrix_repo.save(new_matrix, m_obj.sample_count + 1)

                await db.commit()
        except Exception:
            logger.exception(
                "feedback record failed for session %s (users %d, %d)",
                session_id, user1_id, user2_id,
            )
