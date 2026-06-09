"""Phase 3 — обновление personality_vector по ходу переписки.

Запускается fire-and-forget из хендлера. Открывает СВОЮ DB-сессию (middleware-
сессия к этому моменту уже закрыта). Текст не сохраняется — только дельта вектора.
"""

import math

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.db.repositories.profiles import ProfileRepository
from app.db.repositories.users import UserRepository
from app.services.nlp_processor import NLPProcessor, NLPResult
from app.services.onboarding import DIMENSIONS

VECTOR_SIZE = len(DIMENSIONS)


class ProfileCalibrator:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory
        self.nlp = NLPProcessor()

    @staticmethod
    def _clamp(value: float) -> float:
        return max(-1.0, min(1.0, value))

    @staticmethod
    def _build_delta(result: NLPResult) -> list[float]:
        """NLPResult → дельта-вектор в строгом порядке DIMENSIONS."""
        delta = {dim: 0.0 for dim in DIMENSIONS}

        delta["tone"] = result.sentiment_score * 0.5
        delta["joy"] = result.emotion_scores.get("joy", 0.0) * 0.6
        delta["sadness"] = result.emotion_scores.get("sadness", 0.0) * 0.6
        delta["anger"] = result.emotion_scores.get("anger", 0.0) * 0.6
        delta["fear"] = result.emotion_scores.get("fear", 0.0) * 0.6
        delta["curiosity"] = 0.4 if result.is_question else -0.05
        delta["tempo"] = min(result.word_count / 20, 1.0) * 0.3 - 0.15
        delta["expressiveness"] = min(result.word_count / 30, 1.0) * 0.25

        if result.word_count > 15:
            delta["depth"] = 0.1
        elif result.word_count < 5:
            delta["depth"] = -0.1

        # energy, thinking, humor — нет источника сигнала, остаются 0.0
        return [delta[dim] for dim in DIMENSIONS]

    @staticmethod
    def _build_mbti_delta(result: NLPResult) -> list[float]:
        """NLPResult → дельта для [ei, sn, tf, jp].

        Оси: положительный полюс = E / S / T / J.
        Дельты малые — MBTI калибруется медленнее, чем personality_vector.
        """
        joy = result.emotion_scores.get("joy", 0.0)
        sad = result.emotion_scores.get("sadness", 0.0)
        anger = result.emotion_scores.get("anger", 0.0)
        fear = result.emotion_scores.get("fear", 0.0)

        ei = (min(result.word_count / 25.0, 1.0) - 0.4) * 0.25
        sn = -0.25 if result.is_question else 0.05
        tf = -(joy + sad + anger + fear) * 0.12
        jp = -0.20 if result.is_question else 0.04

        return [ei, sn, tf, jp]

    async def calibrate(self, user_id: int, text: str) -> None:
        if len(text.strip()) < settings.nlp_min_message_length:
            return

        result = await self.nlp.process(text)

        async with self.session_factory() as session:
            profile_repo = ProfileRepository(session)
            user_repo = UserRepository(session)

            profile = await profile_repo.get(user_id)
            if profile is None:
                return  # онбординг ещё не пройден — нечего калибровать

            msg_count = profile.msg_count
            weight = 1.0 / math.sqrt(msg_count + 1)

            delta = self._build_delta(result)
            old_vector = list(profile.personality_vector)
            new_vector = [
                self._clamp(old_vector[i] + weight * delta[i]) for i in range(VECTOR_SIZE)
            ]

            new_msg_count = msg_count + 1
            await profile_repo.update_vector(user_id, new_vector, new_msg_count)

            user = await user_repo.get(user_id)
            if user:
                user.msg_count = new_msg_count

            if result.detected_topics:
                await profile_repo.add_tags(user_id, result.detected_topics)

            # Калибровка MBTI (если профиль прошёл онбординг и mbti_scores уже есть).
            if profile.mbti_scores and len(profile.mbti_scores) == 4:
                mbti_delta = self._build_mbti_delta(result)
                old_mbti = list(profile.mbti_scores)
                new_mbti = [
                    self._clamp(old_mbti[i] + weight * mbti_delta[i]) for i in range(4)
                ]
                await profile_repo.update_mbti(user_id, new_mbti)

            await session.commit()