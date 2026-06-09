# CLAUDE.md

Контекст проекта для Claude Code. Цель файла — не перечитывать весь код каждую сессию.
Глубокая карта (потоки данных, схема Redis, алгоритмы) — в [ARCHITECTURE.md](ARCHITECTURE.md).

## Что это

Анонимный Telegram-бот «случайный чат» (рулетка). Пользователь ищет случайного
собеседника по фильтру пола и общается 1-на-1; сообщения пересылаются между
партнёрами через бота анонимно. Фаза 2 — рекомендательный профиль пользователя
(онбординг → `personality_vector[12]`).

## Стек

Python 3.12 · aiogram 3 (polling) · FastAPI (lifespan запускает воркеры+polling) ·
PostgreSQL + pgvector · SQLAlchemy 2 async · Alembic · Redis · Docker.

## Дорожная карта

Полный фазовый план — в [ROADMAP.md](ROADMAP.md). **Перед реализацией новой задачи сверяйся
с ним:** определи, к какой фазе относится задача, и следуй заложенному там подходу (формулы,
схемы, стек), чтобы не разойтись с планом.

Статус:

- **Фаза 0–1** (архитектура: bot/services/db, PG+Redis+Docker) — готово.
- **Фаза 2** (профиль + онбординг, `personality_vector[12]`) — готово.
- **Фаза 3** (NLP-калибровка профиля по речи, decay `1/sqrt(msg_count+1)`) — готово (этот код):
  `nlp_processor` + `profile_calibrator`, hook в [text.py](app/bot/handlers/text.py) (fire-and-forget).
  Модель: `cointegrated/rubert-tiny2-cedr-emotion-detection` (~60MB, нативный русский, emotion+sentiment).
  Семплинг: каждое `nlp_process_every`-е сообщение (Redis-счётчик `nlp:count:{id}`, не msg_count из БД).
  Семафор: `nlp_max_concurrent=4` параллельных инференса максимум.
  Тексты не сохраняются. Деградация без torch — структурный анализ.
- **Фаза 4** (умный матчинг) — готово (этот код): pgvector HNSW (`0003_hnsw_index`),
  `ProfileRepository.find_best_matches` (cosine `<=>` × geo-вес `exp(-dist/R)`), выбор random из top-k.
  Включается при ≥`match_min_queue_smart` совместимых, иначе fallback к first-compatible.
  Гео — опционально (кнопка `request_location` в настройках); нет координат → нейтральный
  geo-вес `match_geo_neutral_weight` (0.5), не лучший и не худший.
- **Фаза 5** (объяснение мэтча) — готово (этот код): `MatchExplainer`, карточка (%, MBTI, теги, Haiku-текст),
  fire-and-forget из `_pair()`, кэш `explanation:{session_id}` в Redis TTL 3600с.
  По умолчанию (`match_explain_llm_enabled=false`) — только расчёты и теги, без LLM.
  LLM опционален: `match_explain_llm_provider` = "anthropic" | "openai" | "github";
  ключи `anthropic_api_key` / `openai_api_key` / `github_token` задаются в `.env`.
  GitHub Models — бесплатно с любым GitHub-аккаунтом, OpenAI-совместимый API;
- **Фаза 6+** (feedback loop, матрица совместимости, метрики) — следующая.

ROADMAP — план; **фактическое состояние** кода описывает [ARCHITECTURE.md](ARCHITECTURE.md).
Реализация может опережать план или отклоняться (напр. `pgvector VECTOR(12)` введён уже в Фазе 2,
а не в Фазе 4; PK `users.user_id` = Telegram id напрямую, без отдельного `tg_id`).

## Карта кода

```
app/
├── main.py                  точка входа: FastAPI lifespan → polling + CleanupService + MatchmakingWorker
├── core/                    config (pydantic-settings), di (AppContainer), logging
├── db/
│   ├── models.py            User, ChatSession, Report, Block, UserProfile
│   ├── session.py           engine / session_maker
│   └── repositories/        users, sessions, reports, blocks, profiles  (паттерн Repository)
├── services/                бизнес-логика (см. ниже)
└── bot/
    ├── router.py            порядок include_routers ВАЖЕН (первый совпавший хендлер выигрывает)
    ├── middlewares/context.py  инжектит redis+db, ставит online-ключ, коммитит сессию
    ├── states/flow.py       FSM-состояния: StartFlow, SearchFilterState, Onboarding
    ├── keyboards/reply.py    reply-клавиатуры (онбординг — inline, строится в handlers/onboarding.py)
    └── handlers/            start, onboarding, help, chat, content, stop, chat_settings, settings, text
```

Сервисы: `matcher` (подбор пар), `queue` (очередь Redis), `chat` (релей/next/stop), `session_manager`
(жизненный цикл сессии Redis+PG), `matchmaking_worker` (фон, раз/сек), `cleanup` (afk-ключи),
`onboarding` (скоринг профиля), `nlp_processor` (фичи из текста), `profile_calibrator`
(онлайн-обновление вектора по речи), `moderation` (жалобы/баны), `rate_limit`.

## Критические инварианты (НЕ нарушать)

1. **Подбор — взаимная совместимость.** `search_filter` = пол ЖЕЛАЕМОГО собеседника, не свой.
   Пара (A,B) валидна ⇔ `A.filter ∈ {any, B.gender}` И `B.filter ∈ {any, A.gender}`.
   Очередь ОДНА: `queue:waiting` (не по-фильтрам — иначе совместимые пары из разных корзин не встретятся).
2. **БД — источник правды для gender/search_filter/priority.** FSM работает на MemoryStorage
   (volatile, теряется при рестарте). При поиске matcher читает профиль из БД, не из FSM.
   Смена фильтра в меню → пишется в БД ([settings.py](app/bot/handlers/settings.py)).
3. **Онлайн-присутствие** ставит middleware из `data["event_from_user"]`, НЕ `event.from_user`
   (event здесь — Update, у него нет from_user). Ключ `online:{id}` TTL 300с.
   Счётчик активных исключает самого себя.
4. **«Тексты сообщений нигде не хранятся».** Релей — `copy_message` (без атрибуции). UserProfile
   хранит только агрегат (вектор/теги/mbti). Онбординг — на inline-callback'ах, не на тексте.
5. **Нет дублей хендлеров.** Один триггер → один хендлер. `F.contact` живёт только в
   [chat_settings.py](app/bot/handlers/chat_settings.py); `⚙️ Настройки чата` — там же.
6. **Коммит БД** делает middleware после каждого апдейта; сервисы только `session.add`/мутируют.
   Исключение — там где нужен ранний commit (start.py, onboarding finish, moderation).

## Запуск

```bash
docker compose up -d --build          # postgres(pgvector)+redis+app(uvicorn :8000)
docker compose exec app alembic upgrade head   # миграции (НЕ автоматизированы в compose)
```
Приложение стартует как `uvicorn app.main:app` (CMD в Dockerfile); FastAPI-lifespan сам
поднимает polling и фоновые воркеры. `.env`: `bot_token`, `database_url`, `redis_url`.

## Проверка изменений

`python -m py_compile <files>` для синтаксиса. pgvector локально не установлен — модели
импортируются только в среде с зависимостями (Docker). Чистую логику (скоринг/совместимость)
проверяй автономным скриптом без импорта моделей.

## Гитфлоу

Ветка по умолчанию — `develop` (туда же PR). Коммитить/пушить только по просьбе.
