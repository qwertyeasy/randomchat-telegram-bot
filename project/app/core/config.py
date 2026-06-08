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

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
