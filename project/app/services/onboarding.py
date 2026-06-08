from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.profiles import ProfileRepository

# Order is meaningful — it maps 1:1 onto UserProfile.personality_vector (12 dims).
DIMENSIONS = [
    "energy",
    "thinking",
    "tone",
    "depth",
    "humor",
    "joy",
    "sadness",
    "anger",
    "fear",
    "tempo",
    "curiosity",
    "expressiveness",
]

# Interest option codes (Q4). Labels live in the handler (UI layer).
INTEREST_CODES = ["music", "movies", "sport", "games", "books", "travel", "tech", "other"]

# Each answer contributes deltas to personality dimensions. No raw text is stored —
# only these aggregated nudges end up in the vector.
ANSWER_SCORES: dict[str, dict[str, float]] = {
    # Q1 — как общается
    "q1_short": {"tempo": -0.4, "depth": -0.2, "expressiveness": -0.2, "thinking": 0.3},
    "q1_long": {"tempo": 0.6, "depth": 0.4, "expressiveness": 0.3},
    # Q2 — слушает / рассказывает
    "q2_listen": {"expressiveness": -0.4, "energy": -0.2, "curiosity": 0.3},
    "q2_tell": {"expressiveness": 0.5, "energy": 0.3},
    # Q3 — настроение
    "q3_positive": {"joy": 0.6, "tone": 0.4, "sadness": -0.2},
    "q3_neutral": {"joy": 0.1, "tone": 0.0},
    "q3_vent": {"sadness": 0.5, "expressiveness": 0.3, "tone": -0.3, "fear": 0.1},
    # Q5 — интроверт / экстраверт
    "q5_intro": {"energy": -0.5, "expressiveness": -0.3},
    "q5_extra": {"energy": 0.6, "expressiveness": 0.4, "joy": 0.1},
    "q5_mid": {"energy": 0.0},
}

# Interests also nudge the personality vector a little.
INTEREST_SCORES: dict[str, dict[str, float]] = {
    "music": {"expressiveness": 0.1, "humor": 0.1},
    "movies": {"expressiveness": 0.1, "curiosity": 0.1},
    "sport": {"energy": 0.2},
    "games": {"energy": 0.1, "tempo": 0.1},
    "books": {"thinking": 0.2, "depth": 0.2, "curiosity": 0.1},
    "travel": {"curiosity": 0.3, "energy": 0.1},
    "tech": {"thinking": 0.2, "curiosity": 0.2},
    "other": {},
}

# MBTI axes contributions: positive = E / S / T / J.
MBTI_SCORES: dict[str, dict[str, float]] = {
    "q1_short": {"tf": 0.5, "jp": 0.2},
    "q1_long": {"tf": -0.3, "jp": -0.2},
    "q2_listen": {"ei": -0.3},
    "q2_tell": {"ei": 0.3},
    "q3_positive": {"tf": -0.1},
    "q3_vent": {"tf": -0.4},
    "q5_intro": {"ei": -0.6},
    "q5_extra": {"ei": 0.6},
    "q5_mid": {"ei": 0.0},
}


class OnboardingService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.profiles = ProfileRepository(db)

    @staticmethod
    def _clamp(value: float) -> float:
        return max(-1.0, min(1.0, value))

    @classmethod
    def build_vector(cls, answer_keys: list[str], tags: list[str]) -> list[float]:
        scores = {dim: 0.0 for dim in DIMENSIONS}

        for key in answer_keys:
            for dim, delta in ANSWER_SCORES.get(key, {}).items():
                scores[dim] += delta

        for tag in tags:
            for dim, delta in INTEREST_SCORES.get(tag, {}).items():
                scores[dim] += delta

        return [round(cls._clamp(scores[dim]), 4) for dim in DIMENSIONS]

    @classmethod
    def build_mbti(cls, answer_keys: list[str]) -> list[float]:
        axes = {"ei": 0.0, "sn": 0.0, "tf": 0.0, "jp": 0.0}
        for key in answer_keys:
            for axis, delta in MBTI_SCORES.get(key, {}).items():
                axes[axis] += delta
        return [round(cls._clamp(axes[a]), 4) for a in ("ei", "sn", "tf", "jp")]

    async def complete(self, user_id: int, answer_keys: list[str], tags: list[str]) -> None:
        vector = self.build_vector(answer_keys, tags)
        mbti = self.build_mbti(answer_keys)
        await self.profiles.create(
            user_id,
            vector,
            interest_tags=tags,
            mbti_scores=mbti,
        )
