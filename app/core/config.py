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
    db_pool_min: int = 2
    db_pool_max: int = 10
    db_schema: str = "mock_db"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Rate limiting
    rate_limit_otp_per_hour: int = 5
    rate_limit_answer_per_minute: int = 120

    # Storage
    storage_bucket: str = "exam-media"
    signed_url_ttl: int = 3600

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"production", "prod"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
