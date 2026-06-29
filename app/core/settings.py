from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AI_QUOTA_",
        extra="ignore",
        populate_by_name=True,
    )

    database_url: str = "sqlite:///./ai_quota.db"
    api_prefix: str = "/api/v1"
    ai_provider: str = Field(
        default="local",
        validation_alias=AliasChoices("AI_PROVIDER", "ai_provider"),
    )
    model_name: str = Field(
        default="Qwen/Qwen2.5-0.5B-Instruct",
        validation_alias=AliasChoices("AI_MODEL_NAME", "model_name"),
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
