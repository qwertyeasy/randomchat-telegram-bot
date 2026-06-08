# ARCHITECTURE

Подробная карта системы. Краткий контекст и инварианты — в [CLAUDE.md](CLAUDE.md).

## 1. Точка входа и жизненный цикл

[app/main.py](app/main.py) создаёт `FastAPI(lifespan=...)`. CMD контейнера — `uvicorn app.main:app`.
В `lifespan` при старте:
- `CleanupService.start()` — фоновый таск.
- `MatchmakingWorker.start()` — фоновый таск подбора.
- `polling_runner()` — `bot.delete_webhook(drop_pending_updates=True)` + `dp.start_polling`.

На остановке: отмена polling-таска, `matchmaking.stop()`, `cleanup.stop()`, закрытие bot/redis/engine.

HTTP: `GET /` и `GET /health` → `{"status":"ok"}` (для healthcheck, не несут логики).

Middleware [bot/middlewares/context.py](app/bot/middlewares/context.py) повешен на `dp.update`:
открывает `AsyncSession`, кладёт `redis`+`db` в `data`, ставит `online:{id}`, вызывает хендлер,
делает `db.commit()`. **`event` здесь — `Update`**, поэтому пользователь берётся из
`data["event_from_user"]` (его populate-ит встроенный aiogram-middleware раньше нашего).

## 2. Слои и зависимости

```
handlers (aiogram)  →  services (бизнес-логика)  →  repositories  →  models (SQLAlchemy)
                              ↘ Redis (очередь, сессии, presence, rate-limit)
```
- **Repository** — тонкая обёртка над `AsyncSession` (`get`/`create`/мутации), без commit.
- **Service** — оркестрация: matcher/chat/session_manager/onboarding/moderation/rate_limit.
- **AppContainer** ([core/di.py](app/core/di.py)) — dataclass(bot, redis, db); лёгкий контейнер зависимостей.

## 3. Модель данных (PostgreSQL)

- **users**: `user_id` (PK, BigInteger = Telegram id), `gender` (male/female), `search_filter`
  (male/female/any), `priority`, `is_banned`, `consent_given`, `msg_count`, `created_at`.
- **sessions**: `session_id` (UUID), `user1_id`, `user2_id`, `status` (waiting/active/closed),
  `created_at`, `closed_at`. **Это долговременная история диалогов**, не дубль Redis:
  Redis держит *живое* состояние активной сессии, а строка в PG — постоянная запись факта
  (на неё ссылается `reports.session_id`; нужна для feedback/метрик Фаз 6–7).
  `SessionManager.create` пишет строку `active`+commit; `SessionManager.close` помечает её
  `closed`+`closed_at` (И чистит Redis). Раньше close трогал только Redis → строки висели `active`.
- **reports**: `report_id`, `session_id`, `reporter_id`, `target_id`, `reason`, `attached_message`, `created_at`.
- **blocks**: `user_id` (PK), `reason`, `banned_at`.
- **user_profiles** (Фаза 2): `user_id` (PK, FK→users), `personality_vector VECTOR(12)`,
  `interest_tags TEXT[]`, `latitude`/`longitude` (nullable), `mbti_scores FLOAT[4]`,
  `msg_count`, `updated_at`.

Миграции: [alembic/versions/](alembic/versions/) — `0001_init`, `0002_user_profiles`
(делает `CREATE EXTENSION IF NOT EXISTS vector`). `alembic/env.py` берёт URL из `settings`,
`target_metadata = Base.metadata`, работает в async-режиме.

## 4. Схема ключей Redis

| Ключ | Тип | TTL | Назначение |
|------|-----|-----|-----------|
| `online:{user_id}` | string | 300с | presence; считается в «активные пользователи» |
| `queue:waiting` | list | — | единая очередь подбора; элемент = JSON `{user_id,gender,filter,priority,ts}` |
| `lock:match` | lock | 5с | сериализация подбора (`redis.lock`) |
| `session:{session_id}` | hash | — | `{user1_id,user2_id,status}` |
| `user:{user_id}:session` | string | — | обратный индекс user → активная сессия |
| `afk:{session_id}` | string | 120с | маркер активности диалога; cleanup продлевает |
| `rate_limit:{user_id}` | string(incr) | 60с | окно лимита (≤5 действий/мин) |

Legacy-ключи `chat:partner:*`, `chat:state:*`, `chat:room:*` упоминаются только в
`ChatService.end_chat_for_user` — путь похоже не используется в текущем флоу (кандидат на удаление).

## 5. Подбор собеседника (главный алгоритм)

Постановка в очередь: `MatcherService.add_to_queue(user_id)` — читает gender/filter/priority
**из БД** (источник правды), кладёт в `queue:waiting`. Если юзер уже в сессии — no-op.

Подбор: `MatchmakingWorker` раз в секунду открывает сессию и вызывает `try_match_once()` в цикле,
пока есть пары. `try_match_once()` под `lock:match`:
1. читает все элементы очереди, отбрасывает уже-в-сессии и дубли;
2. сортирует по `(-priority, ts)` (приоритет, затем FIFO/честность);
3. ищет первую **взаимно совместимую** пару:
   `_accepts(filter, gender) = filter=="any" or filter==gender`, нужно с обеих сторон;
4. создаёт сессию, удаляет обоих из очереди, шлёт «Собеседник найден».

Почему одна очередь, а не `queue:{filter}`: при раздельных очередях совместимые люди из разных
корзин (Ж-хочет-М в одной, М-хочет-Ж в другой) никогда бы не встретились.

## 6. Диалог и релей

[handlers/text.py](app/bot/handlers/text.py) (`F.text`) и [handlers/content.py](app/bot/handlers/content.py)
(photo/voice/video_note/sticker/document) → `ChatService.relay(...)`:
- отсекает системные тексты (кнопки/команды) — их не пересылаем;
- находит партнёра через `SessionManager`, делает `bot.copy_message` (анонимная копия);
- продлевает `afk:{session_id}`.

`/next` → закрыть сессию, уведомить партнёра, снова в поиск. `/stop` → закрыть и в меню.
`/complain` → `ModerationService.create_report`. Контакт (`F.contact`,
[handlers/chat_settings.py](app/bot/handlers/chat_settings.py)) → проверка активной сессии →
`bot.send_contact` партнёру (осознанная деанонимизация по кнопке `request_contact`).

## 7. Регистрация и онбординг (Фаза 2)

Стартовый флоу ([handlers/start.py](app/bot/handlers/start.py), FSM `StartFlow`):
`/start` → согласие → пол → фильтр → создаётся `User` (commit).
Затем проверка профиля: если `UserProfile` нет → `start_onboarding()`.
(Онбординг идёт ПОСЛЕ создания User, т.к. `user_profiles.user_id` — FK на `users`.)

Онбординг ([handlers/onboarding.py](app/bot/handlers/onboarding.py) + [services/onboarding.py](app/services/onboarding.py),
FSM `Onboarding.q1..q5`): 5 вопросов на inline-кнопках, ответы — callback-коды (`onb:q1:long`,
Q4 — мультивыбор тегов с togg‑галочками). Ответы копятся в FSM-data (`onb_answers`, `onb_tags`).

На финале `OnboardingService.complete()`:
- `build_vector(answers, tags)` → `personality_vector[12]` =
  `[energy, thinking, tone, depth, humor, joy, sadness, anger, fear, tempo, curiosity, expressiveness]`.
  Дельты из `ANSWER_SCORES` + `INTEREST_SCORES`, кламп в `[-1,1]`.
- `build_mbti(answers)` → `[E/I, S/N, T/F, J/P]` (positive = E/S/T/J).
- `ProfileRepository.create(user_id, vector, interest_tags=tags, mbti_scores=mbti)`.

## 7.5 NLP-калибровка профиля (Фаза 3)

Каждое текстовое сообщение в чате дообучает профиль автора — **privacy-first, текст не хранится**.

Поток: [text.py](app/bot/handlers/text.py) после `relay()` запускает `_calibrate_profile`
через `asyncio.create_task` (**fire-and-forget**, чат не ждёт; ссылки на таски держатся в
`_bg_tasks`, чтобы GC их не убил; исключения логируются, не роняют чат).

[services/nlp_processor.py](app/services/nlp_processor.py) `NLPProcessor.process(text) -> NLPResult`:
- **A. Структурный** (без моделей): `is_question` (`?`/вопросительные слова), `word_count`,
  `message_length`, `detected_topics` (подстрочный матч по `TOPIC_KEYWORDS`, коды ⊂ `INTEREST_CODES`).
- **B. Sentiment** (модель `blanchefort/rubert-...`): `score ∈ [-1,1]` = label_value × вероятность.
- **C. Emotion** (англ. модель + опц. перевод `argostranslate`): по умолчанию `nlp_use_translation=False`
  → эмоции нули. Инференс — в thread pool (`run_in_executor`, CPU-bound).
- Модели — module-level синглтоны, **lazy-load**; при отсутствии torch/моделей — graceful degradation
  (только структурный анализ). Прогрев в `lifespan` (`NLPProcessor.warmup` в executor).

[services/profile_calibrator.py](app/services/profile_calibrator.py) `calibrate(user_id, text)`:
- `< nlp_min_message_length` (5) символов → skip;
- открывает **свою** DB-сессию через `session_maker` (middleware-сессия уже закрыта);
- `_build_delta(NLPResult)` → дельта по `DIMENSIONS`; обновление с затуханием
  `new = clamp(old + delta / sqrt(msg_count+1))` (первые сообщения двигают сильно, после ~100 — почти нет);
- пишет `update_vector` + инкремент `msg_count` (в `user_profiles` и `users`) + `add_tags`, один `commit`.

Настройки в [config.py](app/core/config.py): `nlp_enabled`, `nlp_use_translation`,
`nlp_min_message_length`, `nlp_sentiment_model`. Зависимости: `transformers`, `torch`, `sentencepiece`.
Тест маппинга дельты — `tests/test_profile_calibrator.py` (без реальных моделей).

## 8. Конвенции и подводные камни

- **Порядок роутеров** в [bot/router.py](app/bot/router.py): первый совпавший хендлер выигрывает.
  Дубли одного триггера в разных роутерах = тихо мёртвый код. Держать триггеры уникальными.
- **FSM volatile** (MemoryStorage): не источник правды для долговременных настроек — только БД.
- **ARRAY-мутации** SQLAlchemy: переприсваивать новый список (`profile.interest_tags = merged`),
  иначе изменение не отследится.
- **str-enum** (`GenderEnum(str, Enum)`): `== "male"` работает, `json.dumps` даёт `"male"`;
  но `str(member)` вернёт `"GenderEnum.male"` — так не сериализовать.
- **Коммиты**: по умолчанию коммитит middleware; ранний `commit()` — только где результат нужен
  до конца хендлера.
