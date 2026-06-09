# Промпт для Claude Code — Фаза 4: умный матчинг

## Контекст

Текущий матчинг (`app/services/matcher.py`, метод `try_match_once`) читает всю очередь из Redis,
сортирует по приоритету/времени и ищет первую совместимую по полу пару — O(N²), без учёта
личностных профилей. `personality_vector VECTOR(12)` и `latitude/longitude` в `user_profiles`
уже есть, но не используются в матчинге.

Задача Фазы 4: заменить случайный выбор на cosine similarity по pgvector + geo-вес,
с fallback к текущей логике при малой очереди.

---

## 1. Alembic миграция — HNSW индекс

Создать `alembic/versions/0003_hnsw_index.py`:

```python
"""hnsw index on personality_vector"""
from alembic import op

revision = "0003_hnsw_index"
down_revision = "0002_user_profiles"
branch_labels = None
depends_on = None

def upgrade() -> None:
    # HNSW — приближённый поиск ближайших соседей, O(log N) вместо O(N).
    # vector_cosine_ops — оператор косинусного расстояния (<=>).
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_user_profiles_vector_hnsw
        ON user_profiles
        USING hnsw (personality_vector vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)

def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_user_profiles_vector_hnsw")
```

---

## 2. app/core/config.py — добавить настройки матчинга

```python
# Фаза 4 — умный матчинг
match_min_queue_smart: int = 10      # минимум кандидатов для pgvector (иначе fallback к random)
match_geo_radius_km: float = 100.0   # радиус R в формуле exp(-dist/R)
match_top_k: int = 3                 # из скольких лучших выбирать случайно (снижает детерминизм)
```

---

## 3. app/db/repositories/profiles.py — метод find_best_matches

Добавить метод в `ProfileRepository`:

```python
async def find_best_matches(
    self,
    query_vector: list[float],
    candidate_ids: list[int],
    lat: float | None,
    lon: float | None,
    radius_km: float,
    top_k: int,
) -> list[int]:
    """
    Возвращает до top_k user_id из candidate_ids, отсортированных по
    combined_score = cosine_similarity * geo_weight (убывание).
    """
    if not candidate_ids:
        return []

    from pgvector.sqlalchemy import Vector
    from sqlalchemy import select, func, text
    import math

    # Cosine similarity = 1 - cosine_distance
    # pgvector оператор <=> возвращает косинусное РАССТОЯНИЕ [0, 2]
    vec_literal = f"'[{','.join(str(v) for v in query_vector)}]'::vector"

    stmt = text(f"""
        SELECT
            user_id,
            latitude,
            longitude,
            1 - (personality_vector <=> {vec_literal}) AS cosine_sim
        FROM user_profiles
        WHERE user_id = ANY(:ids)
        ORDER BY personality_vector <=> {vec_literal}
        LIMIT :limit
    """)

    rows = (await self.session.execute(
        stmt,
        {"ids": candidate_ids, "limit": min(top_k * 5, len(candidate_ids))}
    )).fetchall()

    def haversine(lat1, lon1, lat2, lon2) -> float:
        R = 6371.0
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlam = math.radians(lon2 - lon1)
        a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def geo_weight(rlat, rlon) -> float:
        if lat is None or lon is None or rlat is None or rlon is None:
            return 1.0  # нет координат — нейтральный вес, не штрафуем
        dist = haversine(lat, lon, rlat, rlon)
        return math.exp(-dist / radius_km)

    scored = [
        (row.user_id, row.cosine_sim * geo_weight(row.latitude, row.longitude))
        for row in rows
    ]
    scored.sort(key=lambda x: -x[1])
    return [uid for uid, _ in scored[:top_k]]
```

---

## 4. app/services/matcher.py — заменить логику выбора пары

Изменить только метод `try_match_once`. Всё остальное в MatcherService — не трогать.

Новая логика:

```python
async def try_match_once(self) -> tuple[int, int] | None:
    lock = self.redis.lock(self.LOCK_KEY, timeout=5, blocking_timeout=1)
    async with lock:
        items = await self.queue.items()

        # Дедупликация и фильтрация уже-в-сессии (как раньше)
        candidates: list[dict] = []
        seen: set[int] = set()
        for _, item in items:
            uid = int(item["user_id"])
            if uid in seen:
                continue
            if await self.sessions.get_session_id(uid) is not None:
                continue
            seen.add(uid)
            candidates.append(item)

        candidates.sort(key=lambda c: (-int(c["priority"]), float(c["ts"])))

        if not candidates:
            return None

        for i, first in enumerate(candidates):
            first_id = int(first["user_id"])

            # Совместимые кандидаты для first
            compatible = [
                c for c in candidates[i + 1:]
                if self._compatible(first, c)
            ]
            if not compatible:
                continue

            compatible_ids = [int(c["user_id"]) for c in compatible]

            # Умный матчинг если кандидатов достаточно
            if len(compatible_ids) >= settings.match_min_queue_smart:
                profile = await self.profiles.get(first_id)
                if profile is not None and profile.personality_vector is not None:
                    best_ids = await self.profiles.find_best_matches(
                        query_vector=list(profile.personality_vector),
                        candidate_ids=compatible_ids,
                        lat=profile.latitude,
                        lon=profile.longitude,
                        radius_km=settings.match_geo_radius_km,
                        top_k=settings.match_top_k,
                    )
                    if best_ids:
                        second_id = random.choice(best_ids)
                        return await self._pair(first_id, second_id)

            # Fallback: первый совместимый (как раньше)
            second_id = int(compatible[0]["user_id"])
            return await self._pair(first_id, second_id)

        return None
```

Добавить импорты в начало файла:
```python
import random
from app.core.config import settings
from app.db.repositories.profiles import ProfileRepository
```

Добавить в `__init__` MatcherService:
```python
self.profiles = ProfileRepository(db)
```

---

## 5. Геолокация — сбор координат от пользователя

### 5a. app/bot/handlers/settings.py — добавить кнопку и хендлер локации

В существующий файл settings.py добавить:
- Кнопку "📍 Поделиться геолокацией" в меню настроек (reply keyboard с `request_location=True`)
- Хендлер `F.location` который сохраняет координаты

```python
@router.message(F.location)
async def save_location(message: Message, db: AsyncSession) -> None:
    """Сохраняет геолокацию пользователя в профиль."""
    if message.location is None:
        return
    profiles = ProfileRepository(db)
    profile = await profiles.get(message.from_user.id)
    if profile is None:
        await message.answer("Сначала завершите настройку профиля.")
        return
    profile.latitude = message.location.latitude
    profile.longitude = message.location.longitude
    # commit делает middleware
    await message.answer(
        "📍 Геолокация сохранена. Теперь алгоритм будет учитывать близость собеседника.",
        reply_markup=main_menu_kb,
    )
```

Кнопка геолокации в Telegram работает через `KeyboardButton(request_location=True)` —
пользователь нажимает и телефон сам отправляет координаты. Геолокация опциональна:
у кого нет — geo_weight возвращает 1.0 (нейтральный вес, не штрафуем).

### 5b. app/db/repositories/profiles.py — добавить update_location

```python
async def update_location(self, user_id: int, lat: float, lon: float) -> None:
    profile = await self.get(user_id)
    if profile is None:
        return
    profile.latitude = lat
    profile.longitude = lon
```

---

## Что НЕ менять

- `QueueService` — очередь Redis остаётся как есть
- `SessionManager` — жизненный цикл сессии не трогаем
- `MatchmakingWorker` — воркер не трогаем
- `_pair()`, `add_to_queue()`, `remove_from_queue()` — не трогаем
- `_compatible()` — hard-фильтр по полу остаётся обязательным

---

## Порядок выполнения

1. Создать миграцию `0003_hnsw_index.py`
2. Добавить настройки в `config.py`
3. Добавить `find_best_matches` и `update_location` в `ProfileRepository`
4. Обновить `MatcherService.try_match_once`
5. Добавить хендлер геолокации в `settings.py`

## Проверка

```bash
python -m py_compile app/services/matcher.py app/db/repositories/profiles.py app/core/config.py app/bot/handlers/settings.py
```

Миграцию применить:
```bash
docker compose exec app alembic upgrade head
```

Показать diff изменённых файлов и итоговый `try_match_once` целиком.
