from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_env: str = "development"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000"

    # Supabase
    supabase_url: str = ""
    supabase_project_ref: str = ""
    supabase_jwt_secret: str = ""
    supabase_jwt_alg: str = "HS256"
    supabase_jwks_url: str = ""

    # Database
    database_url: str = ""
    # Pre-warm several connections so parallel (asyncio.gather) queries reuse warm
    # connections instead of paying a cold TLS+auth open on the hot path.
    db_pool_min: int = 6
    db_pool_max: int = 16
    db_schema: str = "mock_db"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Rate limiting
    rate_limit_otp_per_hour: int = 5
    rate_limit_answer_per_minute: int = 120

    # Storage
    storage_bucket: str = "exam-media"
    signed_url_ttl: int = 3600

    # OpenRouter (AI insight pipeline). Dormant until a key is set.
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # Fast/cheap model for high-volume per-answer grading (concept + error type):
    openrouter_model_grade: str = "anthropic/claude-3.5-haiku"
    # Best-reasoning model for the per-attempt + student-profile narrative:
    openrouter_model_synth: str = "anthropic/claude-opus-4.1"
    openrouter_app_title: str = "MockExam Insights"

    @property
    def ai_enabled(self) -> bool:
        return bool(self.openrouter_api_key)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"production", "prod"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
