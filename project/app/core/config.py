from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: str
    public_base_url: str = "https://randompersonbot.trycloudflare.com"
    webhook_path: str = "/webhook"
    database_url: str
    redis_url: str = "redis://redis:6379/0"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()