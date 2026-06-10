# Phase 6 — Feedback Loop + Матрица совместимости M

## Контекст

Бот: анонимный Telegram-чат (рулетка).

### Текущий стек
`Python 3.12` · `aiogram 3` · `FastAPI lifespan` · `PostgreSQL + pgvector` ·
`SQLAlchemy 2 async` · `Alembic` · `Redis` · `Docker`

### Текущий матчинг (Phase 4)
```
score = cosine(v_a, v_b) × geo_weight(dist)
      = [v_a · v_b / (|v_a||v_b|)] × exp(-dist/R)
```
pgvector HNSW-индекс — fast approximate search. Финальная сортировка и geo — в Python.

### Ключевой инвариант — НЕ нарушать
**Тексты сообщений нигде не хранятся.** `personality_vector` обновляется только
через NLP-анализ (Phase 3). В Phase 6 он не меняется.

---

## Цель Phase 6

Система обучается на реальных исходах сессий, не затрагивая профили пользователей.

**Три независимых блока:**

1. **Сбор сигналов** — записывать исход каждой сессии в `session_outcomes`
2. **Матрица совместимости M** (12×12) — обучается на исходах, хранит в PG
3. **Bilinear матчинг** — `v_a^T · M · v_b` вместо `cosine(v_a, v_b)`

### Почему M, а не просто cosine

Cosine находит *похожих*. M находит *совместимых* — это разные вещи.
Экстраверт + интроверт могут давать отличные сессии при низком cosine.

При M = I (единичная матрица, стартовое состояние): `v_a^T · I · v_b = dot(v_a, v_b)` —
идентично cosine. M начинает как cosine и медленно отклоняется по данным.

---

## Файлы для создания

### 1. `app/db/models.py` — добавить две модели

```python
class SessionOutcome(Base):
    """Исход сессии — сигналы для обучения матрицы M."""
    __tablename__ = "session_outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    user1_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user2_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    msg_count_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    contact_shared: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    early_exit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    success_score: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class CompatibilityMatrix(Base):
    """Обучаемая матрица совместимости M (12×12 = 144 float).
    
    Singleton-таблица: всегда одна строка с id=1.
    Стартовое состояние: M = I (единичная — поведение идентично cosine).
    """
    __tablename__ = "compatibility_matrix"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    # Матрица хранится построчно: matrix[i*12 + j] = M[i][j]
    matrix: Mapped[list[float]] = mapped_column(ARRAY(Float), nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
```

### 2. `alembic/versions/0004_phase6_feedback.py`

```python
"""Phase 6: session_outcomes + compatibility_matrix

Revision ID: 0004
Revises: 0003
"""
import math
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy import Float

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_DIMS = 12
_IDENTITY = [1.0 if i == j else 0.0 for i in range(_DIMS) for j in range(_DIMS)]


def upgrade() -> None:
    op.create_table(
        "session_outcomes",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.UUID, nullable=False, index=True),
        sa.Column("user1_id", sa.BigInteger, nullable=False),
        sa.Column("user2_id", sa.BigInteger, nullable=False),
        sa.Column("msg_count_total", sa.Integer, nullable=False, default=0),
        sa.Column("duration_sec", sa.Integer, nullable=False, default=0),
        sa.Column("contact_shared", sa.Boolean, nullable=False, default=False),
        sa.Column("early_exit", sa.Boolean, nullable=False, default=False),
        sa.Column("success_score", sa.Float, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "compatibility_matrix",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("matrix", ARRAY(Float), nullable=False),
        sa.Column("sample_count", sa.Integer, nullable=False, default=0),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    # Инициализировать единичной матрицей (стартовое поведение = cosine)
    from datetime import datetime
    op.execute(
        sa.text(
            "INSERT INTO compatibility_matrix (id, matrix, sample_count, updated_at) "
            "VALUES (1, :m, 0, :ts)"
        ).bindparams(m=_IDENTITY, ts=datetime.utcnow())
    )


def downgrade() -> None:
    op.drop_table("session_outcomes")
    op.drop_table("compatibility_matrix")
```

### 3. `app/db/repositories/outcomes.py`

```python
"""Репозиторий исходов сессий."""
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import SessionOutcome


class OutcomeRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, outcome: SessionOutcome) -> SessionOutcome:
        self.session.add(outcome)
        return outcome
```

### 4. `app/db/repositories/matrix.py`

```python
"""Репозиторий матрицы совместимости M."""
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import CompatibilityMatrix

_DIMS = 12
_IDENTITY = [1.0 if i == j else 0.0 for i in range(_DIMS) for j in range(_DIMS)]


class MatrixRepository:
    SINGLETON_ID = 1

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self) -> CompatibilityMatrix:
        """Вернуть матрицу (единственная строка). Создать identity если нет."""
        obj = await self.session.get(CompatibilityMatrix, self.SINGLETON_ID)
        if obj is None:
            obj = CompatibilityMatrix(
                id=self.SINGLETON_ID,
                matrix=list(_IDENTITY),
                sample_count=0,
                updated_at=datetime.utcnow(),
            )
            self.session.add(obj)
        return obj

    async def save(self, matrix: list[float], sample_count: int) -> None:
        obj = await self.get()
        obj.matrix = matrix
        obj.sample_count = sample_count
        obj.updated_at = datetime.utcnow()
```

### 5. `app/services/feedback.py` — новый сервис

```python
"""Phase 6 — запись исходов сессий и обновление матрицы совместимости M.

Запускается fire-and-forget из ChatService. Открывает собственную DB-сессию.
Тексты сообщений не хранятся — только агрегированные сигналы.
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
_EARLY_EXIT_THRESHOLD = 5   # < 5 сообщений = провал


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
    """Обновить матрицу M по одному исходу (Hebbian update).

    delta_M = lr · (success_score - 0.5) · outer(v1_norm, v2_norm)

    При success_score > 0.5 — усиливает паттерн этой пары.
    При success_score < 0.5 — ослабляет.
    lr убывает с ростом sample_count (decay).
    Все элементы M clamp(-2.0, 2.0).
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
    ) -> None:
        """Записать исход сессии и обновить матрицу M.

        Вызывается fire-and-forget — не блокирует закрытие чата.
        """
        try:
            early_exit = msg_count < _EARLY_EXIT_THRESHOLD
            score = compute_success_score(msg_count, duration_sec, contact_shared, early_exit)

            async with self.session_factory() as db:
                # 1. Сохранить исход
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
                OutcomeRepository(db).session.add(outcome)

                # 2. Обновить матрицу M
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
```

---

## Файлы для изменения

### 6. `app/core/config.py`

Добавить в `Settings`:

```python
# Phase 6 — feedback loop
phase6_feedback_enabled: bool = False    # включить запись исходов и обучение M
phase6_bilinear_enabled: bool = False    # использовать M в матчинге (включать после накопления данных)
phase6_early_exit_threshold: int = 5     # < N сообщений = early_exit
```

Оба флага по умолчанию `False` — фичи включаются в `.env` явно оператором.

### 7. `app/services/chat.py`

**Добавить `session_maker` в `__init__`:**

```python
def __init__(
    self,
    bot: Bot,
    redis: Redis,
    db: AsyncSession,
    session_maker: async_sessionmaker[AsyncSession] | None = None,
) -> None:
    ...
    self.session_maker = session_maker
    self._bg_tasks: set[asyncio.Task] = set()
```

**Добавить в `relay()` — счётчик сообщений сессии:**

В методе `relay`, сразу после успешного `copy_message`, добавить:
```python
await self.redis.incr(f"smsg:{session_id}")
```
(ключ `smsg:{session_id}` — per-session счётчик сообщений, удаляется при закрытии)

**Добавить приватный метод `_fire_feedback`:**

```python
async def _fire_feedback(self, session_id: str, user1_id: int, user2_id: int, started_at: datetime) -> None:
    """Считать сигналы из Redis и fire-and-forget запись исхода."""
    if self.session_maker is None or not settings.phase6_feedback_enabled:
        return

    msg_count = int(await self.redis.get(f"smsg:{session_id}") or 0)
    contact_shared = bool(await self.redis.get(f"contact:{session_id}"))
    duration_sec = int((datetime.utcnow() - started_at).total_seconds())

    # Удалить вспомогательные Redis-ключи
    await self.redis.delete(f"smsg:{session_id}", f"contact:{session_id}")

    from app.services.feedback import FeedbackService
    feedback = FeedbackService(self.session_maker)
    task = asyncio.create_task(
        feedback.record(session_id, user1_id, user2_id, msg_count, duration_sec, contact_shared)
    )
    self._bg_tasks.add(task)
    task.add_done_callback(self._bg_tasks.discard)
```

**Изменить `stop_chat` и `next_chat`:**

В обоих методах, перед `await self.sessions.close(session_id)`, сначала
прочитать данные сессии:
```python
session_data = await self.redis.hgetall(f"session:{session_id}")
# после close() данные из Redis уже удалены
```

Затем передать в `_fire_feedback`. Время старта: из `session_data` его нет,
поэтому добавить `"started_at"` в `session_manager.py` (см. ниже).

### 8. `app/services/session_manager.py`

**В `create()` — записывать `started_at` в Redis hash:**

```python
await self.redis.hset(
    f"session:{session_id}",
    mapping={
        "user1_id": user1_id,
        "user2_id": user2_id,
        "status": "active",
        "started_at": datetime.utcnow().isoformat(),   # ← добавить
    },
)
```

**В `close()` — вернуть данные сессии** (до их удаления), чтобы `ChatService`
мог передать их в `_fire_feedback`:

```python
async def close(self, session_id: str) -> dict:
    """Закрыть сессию. Возвращает данные из Redis (до удаления)."""
    data = await self.redis.hgetall(f"session:{session_id}")
    if data:
        for uid in (data.get("user1_id"), data.get("user2_id")):
            if uid:
                await self.redis.delete(f"user:{uid}:session")
    await self.redis.delete(f"session:{session_id}")
    # ... остаток метода (PG close) без изменений
    return data  # caller может читать user1_id, user2_id, started_at
```

Обновить все вызовы `await self.sessions.close(session_id)` в `ChatService`
чтобы принимать возвращаемый `data`.

### 9. `app/bot/handlers/chat_settings.py`

В хендлере `F.contact` (обмен контактами) найти блок, где подтверждается
обмен, и добавить:

```python
session_id = await state.redis.get(f"user:{user_id}:session")
if session_id:
    await state.redis.set(f"contact:{session_id}", "1", ex=3600)
```

Конкретную точку вставки определи по коду файла — сразу после того, как
contact sharing считается успешным (оба пользователя подтвердили или один
поделился).

### 10. `app/db/repositories/profiles.py`

**Расширить `find_best_matches`** — принять матрицу M и применять bilinear
вместо cosine при `phase6_bilinear_enabled`:

```python
async def find_best_matches(
    self,
    query_vector: list[float],
    candidate_ids: list[int],
    lat: float | None,
    lon: float | None,
    radius_km: float,
    top_k: int,
    neutral_geo_weight: float = 0.5,
    compat_matrix: list[float] | None = None,   # ← новый параметр
) -> list[int]:
```

Внутри метода — добавить helper для bilinear и использовать его в `scored`:

```python
def bilinear(va: list[float], M: list[float], vb: list[float]) -> float:
    """v_a^T · M · v_b (M хранится построчно, 144 элемента для 12x12)."""
    n = 12
    norm_a = math.sqrt(sum(x * x for x in va)) or 1.0
    norm_b = math.sqrt(sum(x * x for x in vb)) or 1.0
    an = [x / norm_a for x in va]
    bn = [x / norm_b for x in vb]
    result = 0.0
    for i in range(n):
        for j in range(n):
            result += an[i] * M[i * n + j] * bn[j]
    return result
```

SQL-запрос оставить без изменений — pgvector всё так же используется как
быстрый pre-filter (cosine ANN поиск). Python-сортировка после SQL:

```python
# Загрузить personality_vector кандидатов (нужен для bilinear)
# Для этого изменить SQL: добавить personality_vector в SELECT
stmt = text(f"""
    SELECT
        user_id,
        latitude,
        longitude,
        personality_vector,
        1 - (personality_vector <=> {vec_literal}) AS cosine_sim
    FROM user_profiles
    WHERE user_id = ANY(:ids)
    ORDER BY personality_vector <=> {vec_literal}
    LIMIT :limit
""")

scored = []
for row in rows:
    if compat_matrix is not None:
        sim = bilinear(query_vector, compat_matrix, list(row.personality_vector))
    else:
        sim = row.cosine_sim
    scored.append((row.user_id, sim * geo_weight(row.latitude, row.longitude)))
```

### 11. `app/services/matcher.py`

**В `try_match_once()`** — загрузить M перед вызовом `find_best_matches`:

```python
from app.db.repositories.matrix import MatrixRepository
from app.core.config import settings

# ... (внутри блока умного матчинга, перед find_best_matches)
compat_matrix: list[float] | None = None
if settings.phase6_bilinear_enabled:
    matrix_repo = MatrixRepository(self.db)
    m_obj = await matrix_repo.get()
    compat_matrix = m_obj.matrix

best_ids = await self.profiles.find_best_matches(
    ...,
    compat_matrix=compat_matrix,
)
```

### 12. `app/main.py` или инициализация `ChatService`

Передать `session_maker` в `ChatService` так же, как это сделано для
`MatcherService` в `matchmaking_worker.py`:

```python
chat_service = ChatService(bot=bot, redis=redis, db=db, session_maker=db_factory)
```

Найти все места создания `ChatService` и добавить `session_maker=db_factory`.

---

## Контейнер зависимостей

`AppContainer` (`app/core/di.py`) — добавить `session_maker`:

```python
@dataclass
class AppContainer:
    bot: Bot
    redis: Redis
    db: AsyncSession
    session_maker: async_sessionmaker[AsyncSession]   # ← добавить
```

Обновить инициализацию в `main.py`.

---

## Порядок применения

1. Изменить модели (`models.py`)
2. Создать миграцию (`0004_phase6_feedback.py`)
3. Создать репозитории (`outcomes.py`, `matrix.py`)
4. Создать `FeedbackService` (`feedback.py`)
5. Изменить `config.py` (флаги)
6. Изменить `session_manager.py` (`close()` возвращает data, `started_at` в Redis)
7. Изменить `chat.py` (session_maker, relay счётчик, _fire_feedback, stop/next hooks)
8. Изменить `chat_settings.py` (contact Redis-флаг)
9. Изменить `profiles.py` (bilinear в find_best_matches)
10. Изменить `matcher.py` (load M, pass to find_best_matches)
11. Изменить `di.py` + `main.py` (session_maker в AppContainer и ChatService)

---

## Применение миграции

```bash
docker compose exec app alembic upgrade head
```

---

## Проверка (без Docker)

```bash
python -m py_compile \
  app/db/models.py \
  app/db/repositories/outcomes.py \
  app/db/repositories/matrix.py \
  app/services/feedback.py \
  app/services/chat.py \
  app/services/session_manager.py \
  app/services/matcher.py \
  app/db/repositories/profiles.py \
  app/core/config.py
```

---

## Включение фич в `.env`

По умолчанию обе фичи выключены:

```env
# Включить запись исходов (безопасно включить сразу)
PHASE6_FEEDBACK_ENABLED=true

# Включить bilinear матчинг (включать после накопления ~200+ сессий с разными исходами)
PHASE6_BILINEAR_ENABLED=false
```

Логика двух флагов:
- `PHASE6_FEEDBACK_ENABLED=true` — начать копить данные, mathing пока прежний
- `PHASE6_BILINEAR_ENABLED=true` — включить только когда M реально обучена

---

## Инварианты (не нарушать)

- **Тексты сообщений не хранятся.** `FeedbackService.record()` принимает только
  количественные сигналы (`msg_count`, `duration_sec`, `contact_shared`).
- **Вектор пользователя обновляется только NLP** (Phase 3). `FeedbackService` не
  трогает `personality_vector` и `mbti_scores`.
- **Коммит** делает `FeedbackService` в своей сессии. `ChatService` только
  инициирует fire-and-forget.
- **M = I при старте** — поведение матчинга не меняется до накопления данных.
- **Fallback к cosine** при `compat_matrix=None` — `find_best_matches` работает
  как в Phase 4 при `phase6_bilinear_enabled=False`.
