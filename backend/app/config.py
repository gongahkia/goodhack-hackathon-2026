from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Caregiver Companion API"
    database_url: str | None = None
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.5"
    exa_api_key: str | None = None
    tinyfish_api_key: str | None = None
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    demo_agent_mode: str = "auto"
    scheduled_review_enabled: bool = False
    scheduled_review_interval_seconds: int = 86400
    live_search_llm_verification: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def repo_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    @property
    def data_dir(self) -> Path:
        return self.repo_root / "data"

    @property
    def use_scripted_agent(self) -> bool:
        return self.demo_agent_mode == "scripted" or not self.openai_api_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
