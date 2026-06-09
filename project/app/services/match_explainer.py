"""
Match explanation card generator (Phase 5).

Builds a compatibility card from user_profiles data - no raw message text.
Default: stats only (%, MBTI, common tags).
Optional: natural language text from an LLM:
  - Anthropic Claude Haiku
  - OpenAI GPT-4o-mini
  - GitHub Models (free with GitHub account) - OpenAI-compatible API
"""
import logging
import math

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.db.models import UserProfile
from app.db.repositories.profiles import ProfileRepository

logger = logging.getLogger(__name__)

# [energy, thinking, tone, depth, humor, joy, sadness, anger, fear, tempo, curiosity, expressiveness]
_DIMENSION_LABELS: list[tuple[str, str]] = [
    ("энергичный", "спокойный"),
    ("аналитический", "интуитивный"),
    ("позитивный", "сдержанный"),
    ("глубокий", "поверхностный"),
    ("весёлый", "серьёзный"),
    ("радостный", "меланхоличный"),
    ("эмоциональный", "невозмутимый"),
    ("страстный", "хладнокровный"),
    ("тревожный", "уверенный"),
    ("быстрый", "неторопливый"),
    ("любопытный", "прагматичный"),
    ("экспрессивный", "сдержанный"),
]


def _cosine_sim(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _mbti(scores: list[float] | None) -> str:
    if not scores or len(scores) < 4:
        return "?"
    pairs = [("E", "I"), ("S", "N"), ("T", "F"), ("J", "P")]
    return "".join(pos if s >= 0 else neg for s, (pos, neg) in zip(scores, pairs))


def _top_traits(vector: list[float], n: int = 3) -> list[str]:
    scored = [
        (abs(val), high if val >= 0 else low)
        for val, (high, low) in zip(vector, _DIMENSION_LABELS)
    ]
    scored.sort(key=lambda x: -x[0])
    return [label for _, label in scored[:n]]


def _common_tags(tags1: list[str], tags2: list[str]) -> list[str]:
    return sorted(set(tags1) & set(tags2))


def _compat_pct(cosine: float) -> int:
    return max(0, min(100, round(cosine * 100)))


class MatchExplainer:
    def __init__(self, redis: Redis, session_maker: async_sessionmaker[AsyncSession]) -> None:
        self.redis = redis
        self.session_maker = session_maker

    async def build_and_send(self, bot, user1_id: int, user2_id: int, session_id: str) -> None:
        try:
            async with self.session_maker() as db:
                repo = ProfileRepository(db)
                profile1 = await repo.get(user1_id)
                profile2 = await repo.get(user2_id)

            if profile1 is None or profile2 is None:
                return

            card = await self._get_or_build(profile1, profile2, session_id)
            for uid in (user1_id, user2_id):
                await bot.send_message(uid, card, parse_mode="Markdown")
        except Exception:
            logger.exception(
                "match explanation failed for session %s (users %d, %d)",
                session_id, user1_id, user2_id,
            )

    async def _get_or_build(self, profile1: UserProfile, profile2: UserProfile, session_id: str) -> str:
        cache_key = f"explanation:{session_id}"
        cached = await self.redis.get(cache_key)
        if cached:
            return cached
        card = await self._build_card(profile1, profile2)
        await self.redis.set(cache_key, card, ex=settings.match_explain_cache_ttl)
        return card

    async def _build_card(self, p1: UserProfile, p2: UserProfile) -> str:
        v1 = list(p1.personality_vector)
        v2 = list(p2.personality_vector)

        cosine = _cosine_sim(v1, v2)
        compat = _compat_pct(cosine)
        mbti1 = _mbti(p1.mbti_scores)
        mbti2 = _mbti(p2.mbti_scores)
        common = _common_tags(list(p1.interest_tags or []), list(p2.interest_tags or []))

        lines = ["✨ *Карточка совместимости*", ""]
        lines.append(f"🎯 Совместимость: *{compat}%*")
        if mbti1 != "?" and mbti2 != "?":
            lines.append(f"🧠 {mbti1} · {mbti2}")
        if common:
            lines.append(f"🏷 {', '.join(common[:4])}")

        if settings.match_explain_llm_enabled:
            traits1 = _top_traits(v1)
            traits2 = _top_traits(v2)
            text = await self._llm_text(traits1, traits2, common, compat)
            if text:
                lines.append("")
                lines.append(text)

        return "\n".join(lines)

    async def _llm_text(self, traits1: list[str], traits2: list[str], common_tags: list[str], compat_pct: int) -> str:
        provider = settings.match_explain_llm_provider.lower()
        try:
            if provider == "anthropic":
                return await self._anthropic_text(traits1, traits2, common_tags, compat_pct)
            elif provider == "openai":
                return await self._openai_text(traits1, traits2, common_tags, compat_pct)
            elif provider == "github":
                return await self._github_text(traits1, traits2, common_tags, compat_pct)
            else:
                logger.warning("unknown match_explain_llm_provider: %r", provider)
                return ""
        except Exception:
            logger.exception("LLM explanation failed (provider=%r)", provider)
            return ""

    @staticmethod
    def _build_prompt(traits1: list[str], traits2: list[str], common_tags: list[str], compat_pct: int) -> str:
        tags_str = ", ".join(common_tags[:4]) if common_tags else "не выявлено"
        return (
            "Собеседники анонимного чата подобраны по психологическому профилю.\n"
            f"Профиль A: {', '.join(traits1)}.\n"
            f"Профиль B: {', '.join(traits2)}.\n"
            f"Общие интересы: {tags_str}.\n"
            f"Совместимость по вектору: {compat_pct}%.\n\n"
            "Напиши 2–3 коротких предложения на русском, объясняющих, "
            "почему им может быть интересно общаться. "
            "Пиши от второго лица множественного числа: «Вы оба…», «У вас…». "
            "Тон: тёплый, позитивный. Без заголовков и приветствий — только текст."
        )

    async def _anthropic_text(self, traits1: list[str], traits2: list[str], common_tags: list[str], compat_pct: int) -> str:
        if not settings.anthropic_api_key:
            logger.warning("match_explain_llm_provider=anthropic but anthropic_api_key is empty")
            return ""
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            messages=[{"role": "user", "content": self._build_prompt(traits1, traits2, common_tags, compat_pct)}],
        )
        return response.content[0].text.strip()

    async def _openai_text(self, traits1: list[str], traits2: list[str], common_tags: list[str], compat_pct: int) -> str:
        if not settings.openai_api_key:
            logger.warning("match_explain_llm_provider=openai but openai_api_key is empty")
            return ""
        import openai
        client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=150,
            messages=[{"role": "user", "content": self._build_prompt(traits1, traits2, common_tags, compat_pct)}],
        )
        return (response.choices[0].message.content or "").strip()

    async def _github_text(self, traits1: list[str], traits2: list[str], common_tags: list[str], compat_pct: int) -> str:
        """
        GitHub Models - free with any GitHub account, OpenAI-compatible API.
        Key: GitHub Personal Access Token (classic), no special scopes needed.
        Model set via github_model setting (default: Llama-3.3-70B-Instruct).
        """
        if not settings.github_token:
            logger.warning("match_explain_llm_provider=github but github_token is empty")
            return ""
        import openai
        client = openai.AsyncOpenAI(
            api_key=settings.github_token,
            base_url="https://models.inference.ai.azure.com",
        )
        response = await client.chat.completions.create(# или Meta-Llama-3.1-8B-Instruct (быстрее)
            model="Llama-3.3-70B-Instruct",
            max_tokens=150,
            messages=[{"role": "user", "content": self._build_prompt(traits1, traits2, common_tags, compat_pct)}],
        )
        return (response.choices[0].message.content or "").strip()
