# Промпт для Claude Code — Фаза 5: карточка совместимости

## Контекст

После матча (`MatcherService._pair`) пользователи получают только «Собеседник найден».
Задача — дополнительно отправлять карточку совместимости: % совпадения векторов, MBTI обоих,
общие теги. По умолчанию только эти данные (без LLM). Опционально — 2–3 живых предложения
от языковой модели (Anthropic Haiku, OpenAI GPT-4o-mini или Groq Cloud — бесплатно).

Фреймворк: aiogram 3, FastAPI lifespan, SQLAlchemy 2 async. Тексты сообщений нигде не хранятся.
Карточка строится только из агрегированных данных `user_profiles` (вектор, теги, mbti_scores).

---

## 1. requirements.txt — добавить зависимости

```
anthropic>=0.25.0
openai>=1.0.0
```

Обе опциональны в runtime: используются только если соответствующий ключ задан в `.env`.

---

## 2. app/core/config.py — добавить настройки

```python
# Phase 5 — match explanation card
match_explain_enabled: bool = True           # глобальный выключатель карточки
match_explain_cache_ttl: int = 3600          # TTL ключа explanation:{session_id} в Redis

# LLM-объяснение (по умолчанию выключено — карточка содержит только расчёты и теги)
match_explain_llm_enabled: bool = False      # включить живой текст от ИИ
match_explain_llm_provider: str = "anthropic"  # "anthropic" | "openai" | "groq"
anthropic_api_key: str = ""                  # ключ Anthropic (если provider="anthropic")
openai_api_key: str = ""                     # ключ OpenAI   (если provider="openai")
groq_api_key: str = ""                       # ключ Groq Cloud (если provider="groq", бесплатный tier)
# Groq model: "llama-3.3-70b-versatile" (качество) | "llama-3.1-8b-instant" (скорость)
groq_model: str = "llama-3.3-70b-versatile"
```

Обоснование: LLM-вызов — дополнительная стоимость (~$0.001/пара), поэтому по умолчанию
карточка отображает только детерминированные результаты. Оператор включает LLM явно через `.env`.

---

## 3. app/services/match_explainer.py — новый файл

Создать файл целиком:

```python
"""
Match explanation card generator (Phase 5).

Строит карточку совместимости из данных user_profiles — без исходных текстов.
По умолчанию: только расчёты (%, MBTI, общие теги).
Опционально: живой текст от языковой модели (Anthropic Haiku, OpenAI GPT-4o-mini или Groq Cloud — бесплатно).
"""
import logging
import math

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.db.models import UserProfile
from app.db.repositories.profiles import ProfileRepository

logger = logging.getLogger(__name__)

# Метки для 12 измерений personality_vector:
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
    """Косинусное сходство. Возвращает 0.0 если один из векторов нулевой."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _mbti(scores: list[float] | None) -> str:
    """
    Маппинг mbti_scores[4] → строка типа "ENFP".
    Оси: [E/I, S/N, T/F, J/P], positive = E/S/T/J (из OnboardingService.build_mbti).
    """
    if not scores or len(scores) < 4:
        return "?"
    pairs = [("E", "I"), ("S", "N"), ("T", "F"), ("J", "P")]
    return "".join(pos if s >= 0 else neg for s, (pos, neg) in zip(scores, pairs))


def _top_traits(vector: list[float], n: int = 3) -> list[str]:
    """Возвращает n наиболее выраженных черт профиля."""
    scored = [
        (abs(val), high if val >= 0 else low)
        for val, (high, low) in zip(vector, _DIMENSION_LABELS)
    ]
    scored.sort(key=lambda x: -x[0])
    return [label for _, label in scored[:n]]


def _common_tags(tags1: list[str], tags2: list[str]) -> list[str]:
    return sorted(set(tags1) & set(tags2))


def _compat_pct(cosine: float) -> int:
    """cosine_sim [-1,1] → [0,100]%"""
    return max(0, min(100, round(cosine * 100)))


class MatchExplainer:
    """Генерирует карточку совместимости для пары пользователей."""

    def __init__(self, redis: Redis, session_maker: async_sessionmaker[AsyncSession]) -> None:
        self.redis = redis
        self.session_maker = session_maker

    async def build_and_send(
        self,
        bot,
        user1_id: int,
        user2_id: int,
        session_id: str,
    ) -> None:
        """
        Загружает профили, строит карточку, кэширует в Redis и отправляет обоим.
        Ошибки логируются, не бросаются — не должны ронять чат.
        """
        try:
            async with self.session_maker() as db:
                repo = ProfileRepository(db)
                profile1 = await repo.get(user1_id)
                profile2 = await repo.get(user2_id)

            if profile1 is None or profile2 is None:
                return  # профиль отсутствует — пропускаем карточку

            card = await self._get_or_build(profile1, profile2, session_id)
            for uid in (user1_id, user2_id):
                await bot.send_message(uid, card, parse_mode="Markdown")
        except Exception:
            logger.exception(
                "match explanation failed for session %s (users %d, %d)",
                session_id, user1_id, user2_id,
            )

    async def _get_or_build(
        self,
        profile1: UserProfile,
        profile2: UserProfile,
        session_id: str,
    ) -> str:
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

        # --- Статистика (всегда присутствует) ---
        lines = ["✨ *Карточка совместимости*", ""]
        lines.append(f"🎯 Совместимость: *{compat}%*")
        if mbti1 != "?" and mbti2 != "?":
            lines.append(f"🧠 {mbti1} · {mbti2}")
        if common:
            lines.append(f"🏷 {', '.join(common[:4])}")

        # --- LLM-объяснение (опционально) ---
        if settings.match_explain_llm_enabled:
            traits1 = _top_traits(v1)
            traits2 = _top_traits(v2)
            text = await self._llm_text(traits1, traits2, common, compat)
            if text:
                lines.append("")
                lines.append(text)

        return "\n".join(lines)

    async def _llm_text(
        self,
        traits1: list[str],
        traits2: list[str],
        common_tags: list[str],
        compat_pct: int,
    ) -> str:
        """
        Запрашивает объяснение у выбранного провайдера.
        Возвращает пустую строку при любой ошибке (карточка всё равно покажет статистику).
        """
        provider = settings.match_explain_llm_provider.lower()
        try:
            if provider == "anthropic":
                return await self._anthropic_text(traits1, traits2, common_tags, compat_pct)
            elif provider == "openai":
                return await self._openai_text(traits1, traits2, common_tags, compat_pct)
            else:
                logger.warning("unknown match_explain_llm_provider: %r", provider)
                return ""
        except Exception:
            logger.exception("LLM explanation failed (provider=%r)", provider)
            return ""

    @staticmethod
    def _build_prompt(
        traits1: list[str],
        traits2: list[str],
        common_tags: list[str],
        compat_pct: int,
    ) -> str:
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

    async def _anthropic_text(
        self,
        traits1: list[str],
        traits2: list[str],
        common_tags: list[str],
        compat_pct: int,
    ) -> str:
        if not settings.anthropic_api_key:
            logger.warning("match_explain_llm_provider=anthropic but anthropic_api_key is empty")
            return ""

        import anthropic  # lazy import

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            messages=[{"role": "user", "content": self._build_prompt(traits1, traits2, common_tags, compat_pct)}],
        )
        return response.content[0].text.strip()

    async def _openai_text(
        self,
        traits1: list[str],
        traits2: list[str],
        common_tags: list[str],
        compat_pct: int,
    ) -> str:
        if not settings.openai_api_key:
            logger.warning("match_explain_llm_provider=openai but openai_api_key is empty")
            return ""

        import openai  # lazy import

        client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=150,
            messages=[{"role": "user", "content": self._build_prompt(traits1, traits2, common_tags, compat_pct)}],
        )
        return (response.choices[0].message.content or "").strip()
```

---

## 4. app/services/matcher.py — fire-and-forget карточки в `_pair()`

### 4a. Добавить импорты и module-level переменные в начало файла

```python
import asyncio
import logging

# ... существующие импорты ...
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.services.match_explainer import MatchExplainer

logger = logging.getLogger(__name__)
_bg_tasks: set[asyncio.Task] = set()
```

### 4b. Изменить `__init__` — добавить опциональный `session_maker`

```python
def __init__(
    self,
    bot: Bot,
    redis: Redis,
    db: AsyncSession,
    session_maker: async_sessionmaker[AsyncSession] | None = None,
) -> None:
    self.bot = bot
    self.redis = redis
    self.db = db
    self.session_maker = session_maker  # нужен для fire-and-forget explanation
    self.queue = QueueService(redis)
    self.sessions = SessionManager(redis, db)
    self.users = UserRepository(db)
    self.profiles = ProfileRepository(db)
```

### 4c. Заменить `_pair()` целиком

```python
async def _pair(self, user1_id: int, user2_id: int) -> tuple[int, int]:
    await self.queue.remove_user(user1_id)
    await self.queue.remove_user(user2_id)

    session_id = await self.sessions.create(user1_id, user2_id)

    for uid in (user1_id, user2_id):
        await self.bot.send_message(
            uid,
            "Собеседник найден. Можете начинать чат.",
            reply_markup=chat_menu_kb,
        )

    # Fire-and-forget карточка совместимости.
    # session_maker отсутствует, когда MatcherService создан из ChatService
    # (тот не вызывает _pair) — в этом случае пропускаем.
    if self.session_maker is not None and settings.match_explain_enabled:
        task = asyncio.create_task(
            self._send_explanation(user1_id, user2_id, session_id)
        )
        _bg_tasks.add(task)
        task.add_done_callback(_bg_tasks.discard)

    return user1_id, user2_id

async def _send_explanation(
    self, user1_id: int, user2_id: int, session_id: str
) -> None:
    """Фоновая задача: строит и отправляет карточку совместимости."""
    explainer = MatchExplainer(self.redis, self.session_maker)  # type: ignore[arg-type]
    await explainer.build_and_send(self.bot, user1_id, user2_id, session_id)
```

> **Почему `session_maker`, а не `self.db`?**
> `MatchmakingWorker` создаёт `MatcherService` внутри `async with db_factory() as db:`.
> Сессия закрывается после `try_match_once()`. Fire-and-forget задача живёт дольше —
> должна открывать свою сессию, как `ProfileCalibrator`.

---

## 5. app/services/matchmaking_worker.py — передать `db_factory` в `MatcherService`

Одна строка в `run()`:

```python
# Было:
matcher = MatcherService(self.bot, self.redis, db)

# Стало:
matcher = MatcherService(self.bot, self.redis, db, session_maker=self.db_factory)
```

---

## 6. Redis — новый ключ (справочно)

| Ключ | Тип | TTL | Назначение |
|------|-----|-----|-----------|
| `explanation:{session_id}` | string | `match_explain_cache_ttl` (3600с) | кэш карточки совместимости |

---

## Что НЕ менять

- `SessionManager.create()` — уже возвращает `str` (session_id)
- `ChatService` — создаёт `MatcherService` без `session_maker` (корректно: не вызывает `_pair`)
- `QueueService`, `MatchmakingWorker.__init__`, `CleanupService` — не трогаем
- Хендлеры, `OnboardingService`, `ProfileCalibrator`, `NLPProcessor` — не трогаем
- Alembic-миграции не нужны (новых таблиц нет)

---

## Порядок выполнения

1. Добавить `anthropic` и `openai` в `requirements.txt`
2. Добавить 6 настроек в `config.py`
3. Создать `app/services/match_explainer.py`
4. Обновить `app/services/matcher.py` (импорты + `__init__` + `_pair` + `_send_explanation`)
5. Обновить `app/services/matchmaking_worker.py` (одна строка)

---

## Проверка

```bash
python -m py_compile \
    app/services/match_explainer.py \
    app/services/matcher.py \
    app/services/matchmaking_worker.py \
    app/core/config.py
```

Показать итоговый `_pair()`, `_send_explanation()` и `__init__()` из `matcher.py` целиком.

### Тест 1 — карточка без LLM (по умолчанию)

`.env` не содержит `MATCH_EXPLAIN_LLM_ENABLED` (или `=false`).
После матча должна прийти карточка:

```
✨ Карточка совместимости

🎯 Совместимость: 17%
🧠 ENFP · INFJ
🏷 music, films
```

Текстового объяснения нет — только расчёты и теги.

### Тест 2 — карточка с Anthropic Haiku

`.env`:
```
MATCH_EXPLAIN_LLM_ENABLED=true
MATCH_EXPLAIN_LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

Карточка должна дополниться 2–3 предложениями на русском:

```
✨ Карточка совместимости

🎯 Совместимость: 17%
🧠 ENFP · INFJ
🏷 music, films

Вы оба цените глубокие разговоры и открыты к новым идеям. ...
```

### Тест 3 — карточка с OpenAI GPT-4o-mini

`.env`:
```
MATCH_EXPLAIN_LLM_ENABLED=true
MATCH_EXPLAIN_LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
```

Аналогично тесту 2, но текст генерирует GPT-4o-mini.

### Тест 4 — карточка с Groq Cloud (бесплатно)

`.env`:
```
MATCH_EXPLAIN_LLM_ENABLED=true
MATCH_EXPLAIN_LLM_PROVIDER=groq
GROQ_API_KEY=gsk_...
```

Ключ получить на [console.groq.com](https://console.groq.com) — бесплатный tier без карты.
Модель захардкожена в `_groq_text` (`llama-3.3-70b-versatile`); сменить — правкой этой строки
(напр. `llama-3.1-8b-instant` для скорости).

### Тест 5 — ключ не задан при включённом LLM

`MATCH_EXPLAIN_LLM_ENABLED=true`, ключ пустой →
в логах warning, карточка приходит без текстового объяснения (только статистика).

### Проверить Redis

```bash
docker compose exec redis redis-cli KEYS "explanation:*"
docker compose exec redis redis-cli GET "explanation:<session_id>"
```
