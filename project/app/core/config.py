from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: str
    database_url: str
    redis_url: str

    # Phase 3 — NLP profile calibration
    nlp_enabled: bool = True
    nlp_use_translation: bool = False
    nlp_min_message_length: int = 5
    nlp_sentiment_model: str = "blanchefort/rubert-base-cased-sentiment-rurewiews"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()