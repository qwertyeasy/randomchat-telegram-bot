from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: str
    database_url: str
    redis_url: str

    # Phase 3 — NLP profile calibration
    nlp_enabled: bool = True
    nlp_use_translation: bool = False
    nlp_min_message_length: int = 5
    # rubert-tiny2-cedr: одна модель для sentiment + emotion, нативный русский, ~60MB.
    # Sentiment выводится из эмоций: joy - (sadness + anger + fear) * 0.5.
    # Альтернатива с раздельными моделями: blanchefort/rubert-base-cased-sentiment-rurewiews
    # (тяжелее ~450MB, зато только sentiment, выше точность на pure-sentiment задачах).
    nlp_model: str = "cointegrated/rubert-tiny2-cedr-emotion-detection"
    # Нагрузочные настройки
    nlp_max_concurrent: int = 4       # макс. параллельных torch-инференсов (семафор)
    nlp_process_every: int = 3        # обрабатывать каждое N-е сообщение пользователя

    # Phase 4 — умный матчинг
    match_min_queue_smart: int = 10   # минимум совместимых кандидатов для pgvector (иначе fallback к random)
    match_geo_radius_km: float = 100.0  # радиус R в формуле geo-веса exp(-dist/R)
    match_top_k: int = 3              # из скольких лучших по score выбирать случайно
    match_geo_neutral_weight: float = 0.5  # вес при отсутствии координат (нейтрально, ≈ R*ln2 км)

    # Phase 5 — карточка совместимости
    match_explain_enabled: bool = True            # глобальный выключатель карточки
    match_explain_cache_ttl: int = 3600           # TTL ключа explanation:{session_id} в Redis
    # LLM-объяснение (по умолчанию выключено — карточка содержит только расчёты и теги)
    match_explain_llm_enabled: bool = False       # включить живой текст от ИИ
    match_explain_llm_provider: str = "github"  # "anthropic" | "openai" | "github"

    anthropic_api_key: str = ""            # ключ Anthropic (если provider="anthropic")
    openai_api_key: str = ""               # ключ OpenAI   (если provider="openai")
    github_token: str = ""                 # GitHub Personal Access Token (classic, без доп. scopes)

    # Phase 6 — feedback loop
    phase6_feedback_enabled: bool = False   # запись исходов сессий и обучение M
    phase6_bilinear_enabled: bool = False   # использовать M в матчинге (включать после накопления данных)
    phase6_early_exit_threshold: int = 5    # < N сообщений = early_exit

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
