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
    jina_api_key: str | None = None
    openalex_api_key: str | None = None
    semantic_scholar_api_key: str | None = None
    sealion_api_key: str | None = None
    sealion_base_url: str = "https://api.sea-lion.ai/v1"
    sealion_model: str = "aisingapore/Gemma-SEA-LION-v4-27B-IT"
    sealion_guard_model: str = "aisingapore/SEA-Guard"
    transcription_provider: str = "local"
    mlx_whisper_model: str = "mlx-community/whisper-small-mlx"
    groq_api_key: str | None = None
    groq_transcription_model: str = "whisper-large-v3-turbo"
    transcription_language: str = "en"
    transcription_max_bytes: int = 25 * 1024 * 1024
    transcription_timeout_seconds: int = 120
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
