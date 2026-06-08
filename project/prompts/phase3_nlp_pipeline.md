# Промпт для Claude Code — Фаза 3: NLP Pipeline

Вставь этот промпт в Claude Code (VS Code) как есть.

---

## Контекст проекта

Telegram-бот анонимного чата. Стек: Python 3.12, aiogram 3, FastAPI, PostgreSQL + pgvector, SQLAlchemy 2 async, Redis, Docker.

Фазы 0–2 реализованы:
- Пользователи проходят онбординг (5 вопросов) → `personality_vector[12]` записывается в `user_profiles`
- Вектор описывает 12 измерений личности (порядок строгий, менять нельзя):
  `[energy, thinking, tone, depth, humor, joy, sadness, anger, fear, tempo, curiosity, expressiveness]`
- Репозиторий `ProfileRepository` (app/db/repositories/profiles.py) уже имеет готовые методы:
  `update_vector(user_id, new_vector, msg_count)` и `add_tags(user_id, tags)`
- Модель `UserProfile` (app/db/models.py) имеет поля: `personality_vector`, `interest_tags`, `msg_count`, `mbti_scores`
- Модель `User` (app/db/models.py) имеет поле `msg_count`
- Точка входа для обработки сообщений — `app/bot/handlers/text.py`, хендлер `relay_text`

**Принцип privacy-first — строго обязателен:**
Тексты сообщений **нигде не сохраняются**. NLP обрабатывает текст в памяти → получает дельта-вектор → применяет к профилю → текст забывается. В БД хранится только обновлённый вектор и счётчик сообщений.

---

## Задача Фазы 3 — NLP Pipeline

Реализовать автоматическую калибровку профиля пользователя по ходу переписки.

### Архитектурные требования

1. **Неблокирующий.** NLP-обработка запускается через `asyncio.create_task()` после `relay()` — чат пользователя не ждёт результата.
2. **CPU-bound → thread pool.** Инференс трансформеров запускать через `asyncio.get_event_loop().run_in_executor(None, ...)`, чтобы не блокировать event loop.
3. **Lazy-load моделей.** Модели загружаются при первом вызове и кешируются в памяти процесса (module-level singleton). Не перезагружать на каждое сообщение.
4. **Короткие сообщения пропускаются.** Длина < 5 символов → skip полностью.
5. **Один коммит.** ProfileRepository мутирует объект, коммит делает вызывающий код (сервис сам открывает session через session_maker).
6. **Отдельная DB-сессия.** NLP-таск живёт вне middleware-сессии (та уже закрыта к моменту выполнения таска). Открывать через `session_maker` из `app/db/session.py`.

### Что реализовать

#### 1. `app/services/nlp_processor.py` — извлечение признаков из текста

Класс `NLPProcessor` с методом:
```python
async def process(self, text: str) -> NLPResult
```

`NLPResult` — dataclass/pydantic:
```python
@dataclass
class NLPResult:
    sentiment_score: float        # [-1, 1]: -1 негатив, +1 позитив
    emotion_scores: dict[str, float]  # joy, sadness, anger, fear → [0, 1]
    is_question: bool
    message_length: int           # в символах
    word_count: int
    detected_topics: list[str]    # из INTEREST_CODES
```

**Уровни анализа (реализовать все три):**

**A. Структурный анализ (без моделей, детерминированный):**
- `is_question`: текст содержит `?` или вопросительные слова (как, что, почему, зачем, когда, где, кто, сколько)
- `message_length`, `word_count`: прямой подсчёт
- `detected_topics`: сопоставление со словарём ключевых слов по темам:
  ```python
  TOPIC_KEYWORDS = {
      "music": ["музык", "песн", "альбом", "плейлист", "трек", "концерт", "группа", "исполнитель"],
      "movies": ["фильм", "сериал", "кино", "смотрел", "режиссёр", "актёр", "сцена"],
      "sport": ["спорт", "футбол", "трениров", "зал", "бег", "качал", "игра"],
      "games": ["игр", "геймер", "стрим", "мод", "персонаж", "уровень"],
      "books": ["книг", "читал", "автор", "роман", "глав", "страниц"],
      "travel": ["путешеств", "поездк", "город", "страна", "туризм", "билет", "отель"],
      "tech": ["програм", "код", "сервер", "питон", "разработк", "технолог", "алгоритм"],
  }
  ```
  Сравнение case-insensitive, по подстроке (чтобы покрывать падежи).

**B. Sentiment (модель):**
Использовать `blanchefort/rubert-base-cased-sentiment-rurewiews` из HuggingFace (3-class: NEGATIVE/NEUTRAL/POSITIVE).
Возвращает `sentiment_score`: POSITIVE → +1.0, NEUTRAL → 0.0, NEGATIVE → -1.0, с учётом вероятности (`score * label_value`).

**C. Emotion (модель):**
Использовать `setempler/multilingual-sentiment` **ИЛИ** `j-hartmann/emotion-english-distilroberta-base`.
Если модель не поддерживает русский — добавить опциональный перевод через `argostranslate` (ru→en) перед инференсом, но сделать перевод отключаемым флагом `USE_TRANSLATION: bool = False` (по умолчанию False — пропускать emotion до настройки).
Emotion scores заполнять нулями если модель недоступна/отключена.

Загрузку моделей обернуть в try/except: если модель недоступна (нет интернета, нет GPU) — graceful degradation, работать только со структурным анализом.

**Eager load при старте приложения (важно):**
В `app/main.py`, в блоке `lifespan` после запуска воркеров, добавить прогрев:
```python
from app.services.nlp_processor import NLPProcessor
# Загружаем модели заранее, чтобы первый пользователь не ждал
asyncio.create_task(asyncio.get_event_loop().run_in_executor(None, NLPProcessor.warmup))
```
Метод `NLPProcessor.warmup()` — статический, просто вызывает `_get_sentiment_model()` и `_get_emotion_model()` (те же синглтоны), тем самым загружая веса в память до первого сообщения.

#### 2. `app/services/profile_calibrator.py` — обновление профиля

Класс `ProfileCalibrator` с методом:
```python
async def calibrate(self, user_id: int, text: str) -> None
```

**Алгоритм:**

```python
# 1. Пропустить короткие
if len(text.strip()) < 5:
    return

# 2. NLP
result = await nlp_processor.process(text)

# 3. Открыть отдельную DB-сессию
async with session_maker() as session:
    profile_repo = ProfileRepository(session)
    user_repo = UserRepository(session)

    profile = await profile_repo.get(user_id)
    if profile is None:
        return  # онбординг ещё не пройден

    # 4. Decay weight
    msg_count = profile.msg_count
    weight = 1.0 / math.sqrt(msg_count + 1)

    # 5. Вычислить дельта-вектор из NLPResult
    delta = _build_delta(result)  # см. ниже

    # 6. Применить обновление
    old_vector = list(profile.personality_vector)
    new_vector = [
        _clamp(old_vector[i] + weight * delta[i])
        for i in range(12)
    ]

    # 7. Сохранить
    new_msg_count = msg_count + 1
    await profile_repo.update_vector(user_id, new_vector, new_msg_count)

    # 8. Обновить msg_count на модели User тоже
    user = await user_repo.get(user_id)
    if user:
        user.msg_count = new_msg_count

    # 9. Добавить теги если найдены
    if result.detected_topics:
        await profile_repo.add_tags(user_id, result.detected_topics)

    await session.commit()
```

**`_build_delta(result: NLPResult) -> list[float]`** — перевод NLPResult в дельта-вектор по DIMENSIONS:

```
DIMENSIONS = [energy, thinking, tone, depth, humor, joy, sadness, anger, fear, tempo, curiosity, expressiveness]
```

Маппинг:
- `tone` ← `sentiment_score * 0.5`
- `joy` ← `emotion_scores["joy"] * 0.6`
- `sadness` ← `emotion_scores["sadness"] * 0.6`
- `anger` ← `emotion_scores["anger"] * 0.6`
- `fear` ← `emotion_scores["fear"] * 0.6`
- `curiosity` ← `0.4 if result.is_question else -0.05`
- `tempo` ← нормализовать word_count: `min(result.word_count / 20, 1.0) * 0.3 - 0.15` (длинные → высокий темп)
- `expressiveness` ← `min(result.word_count / 30, 1.0) * 0.25`
- `depth` ← если word_count > 15: `+0.1`, если < 5: `-0.1`, иначе `0.0`
- `energy`, `thinking`, `humor` ← `0.0` (пока нет источника сигнала, оставить нейтральными)

`_clamp(v)` → `max(-1.0, min(1.0, v))`

#### 3. Интеграция в `app/bot/handlers/text.py`

После вызова `service.relay(...)` — запустить NLP-таск **без await**:

```python
from app.services.profile_calibrator import ProfileCalibrator
from app.db.session import session_maker

@router.message(F.text)
async def relay_text(message: Message, redis: Redis, db: AsyncSession) -> None:
    text = message.text
    # ... существующий фильтр системных текстов ...

    service = ChatService(message.bot, redis, db)
    await service.relay(
        user_id=message.from_user.id,
        chat_id=message.chat.id,
        message_id=message.message_id,
        text=text,
    )

    # NLP — fire and forget, не блокируем чат
    if text:
        asyncio.create_task(
            _calibrate_profile(message.from_user.id, text)
        )

async def _calibrate_profile(user_id: int, text: str) -> None:
    try:
        calibrator = ProfileCalibrator(session_maker)
        await calibrator.calibrate(user_id, text)
    except Exception:
        # NLP никогда не должен ронять чат
        logging.getLogger(__name__).exception("profile calibration failed for user %d", user_id)
```

#### 4. `requirements.txt` — добавить зависимости

```
transformers>=4.40.0
torch>=2.0.0
sentencepiece
```

Не добавлять тяжёлые зависимости (argostranslate) в requirements.txt — только если `USE_TRANSLATION=True`.

#### 5. `app/core/config.py` — добавить настройки NLP

```python
nlp_enabled: bool = True
nlp_use_translation: bool = False
nlp_min_message_length: int = 5
nlp_sentiment_model: str = "blanchefort/rubert-base-cased-sentiment-rurewiews"
```

---

## Что НЕ нужно делать

- Не хранить тексты сообщений в БД или Redis
- Не изменять логику `ChatService.relay()` — hook только в хендлере
- Не ломать существующий онбординг и вектор, созданный `OnboardingService`
- Не добавлять синхронные операции в event loop — только `run_in_executor` для CPU-bound кода

---

## Ожидаемый результат

После реализации каждое сообщение пользователя (≥5 символов) в активном чате:
1. Пересылается партнёру (как раньше)
2. Асинхронно запускает NLP-обработку
3. Обновляет `personality_vector` пользователя с затуханием `1/sqrt(msg_count+1)`
4. Обновляет `interest_tags` если найдены топики
5. Увеличивает `msg_count` в `user_profiles` и `users`

Текст сообщения нигде не сохраняется.

---

## Проверка после реализации

1. `python -m py_compile app/services/nlp_processor.py app/services/profile_calibrator.py` — синтаксис
2. Написать unit-тест `tests/test_profile_calibrator.py` — тест метода `_build_delta` с mock NLPResult (без реальных моделей)
3. Показать итоговое дерево изменённых файлов
