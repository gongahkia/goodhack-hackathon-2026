from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    app_name: str = "Caregiver Companion API"
    app_env: str = "development"
    database_url: str | None = None
    openai_api_key: str | None = Field(default=None, repr=False)
    openai_model: str = "gpt-5.5"
    exa_api_key: str | None = Field(default=None, repr=False)
    tinyfish_api_key: str | None = Field(default=None, repr=False)
    jina_api_key: str | None = Field(default=None, repr=False)
    openalex_api_key: str | None = Field(default=None, repr=False)
    semantic_scholar_api_key: str | None = Field(default=None, repr=False)
    sealion_api_key: str | None = Field(default=None, repr=False)
    sealion_base_url: str = "https://api.sea-lion.ai/v1"
    sealion_model: str = "aisingapore/Gemma-SEA-LION-v4-27B-IT"
    sealion_guard_model: str = "aisingapore/SEA-Guard"
    sealion_transcript_review_enabled: bool = False
    transcription_provider: str = "openai"
    openai_transcription_model: str = "gpt-4o-transcribe"
    local_transcription_backend: str = "auto"
    mlx_whisper_model: str = "mlx-community/whisper-large-v3-turbo-q4"
    faster_whisper_model: str = "base.en"
    faster_whisper_compute_type: str = "int8"
    groq_api_key: str | None = Field(default=None, repr=False)
    groq_transcription_model: str = "whisper-large-v3-turbo"
    transcription_language: str | None = None
    transcription_max_bytes: int = 25 * 1024 * 1024
    transcription_timeout_seconds: int = 120
    transcription_rate_limit: int = 20
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    live_search_llm_verification: bool = True
    api_read_key: str | None = Field(default=None, repr=False)
    api_write_key: str | None = Field(default=None, repr=False)
    clinician_review_key: str | None = Field(default=None, repr=False)
    data_encryption_key: str | None = Field(default=None, repr=False)
    raw_transcript_retention_days: int = 30
    placeholder_map_retention_days: int = 30
    audit_log_retention_days: int = 365
    external_vendors_enabled: bool = True
    vendor_openai_enabled: bool = True
    vendor_groq_enabled: bool = True
    vendor_sealion_enabled: bool = True
    vendor_exa_enabled: bool = True
    vendor_tinyfish_enabled: bool = True
    vendor_jina_enabled: bool = True
    vendor_openalex_enabled: bool = True
    vendor_semantic_scholar_enabled: bool = True
    vendor_google_calendar_enabled: bool = True
    vendor_allowed_purposes: str = ""
    google_calendar_id: str = "primary"
    google_calendar_access_token: str | None = Field(default=None, repr=False)
    google_calendar_api_base_url: str = "https://www.googleapis.com/calendar/v3"

    model_config = SettingsConfigDict(env_file=(REPO_ROOT / ".env", BACKEND_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore")

    @property
    def repo_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    @property
    def data_dir(self) -> Path:
        return self.repo_root / "data"

    @property
    def use_scripted_agent(self) -> bool:
        return not self.openai_api_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
