"""Application settings, read once from environment variables / the project-root .env file.

Secrets (DATABASE_URL, SESSION_SECRET, NVIDIA_API_KEY) are held here and never logged:
`Settings.__repr__` is overridden and the secret fields use SecretStr.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = Path(__file__).resolve().parents[2]


class ConfigError(RuntimeError):
    """Raised at startup when required configuration is missing or unsafe."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(PROJECT_ROOT / ".env"), str(BACKEND_ROOT / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = Field(default="development", pattern="^(development|production|test)$")
    app_version: str = "dev"

    database_url: SecretStr | None = None
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_sslmode: str | None = None  # default: require for remote hosts, disable for local sockets

    session_secret: SecretStr | None = None
    session_ttl_days: int = 7
    session_max_age_days: int = 30
    cookie_secure: bool | None = None

    ai_provider: str = Field(default="nvidia", pattern="^(nvidia|fake)$")
    nvidia_api_key: SecretStr | None = None
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_model: str | None = None
    nvidia_enable_thinking: bool = False
    nvidia_structured_output: str = Field(default="json_object", pattern="^(json_object|json_schema|none)$")
    llm_timeout_seconds: float = 30.0

    ai_hourly_limit: int = 30
    ai_daily_limit: int = 150
    ai_global_daily_limit: int = 3000

    max_upload_mb: int = 5
    max_pdf_pages: int = 5
    pii_redaction_enabled: bool = True
    rate_limit_enabled: bool = True
    log_level: str = "INFO"
    default_timezone: str = "Asia/Kolkata"
    static_dir: str = str(PROJECT_ROOT / "frontend" / "dist")

    @field_validator("nvidia_model", "app_version", mode="before")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def _production_safety(self) -> "Settings":
        if self.app_env == "production":
            if self.ai_provider == "fake":
                raise ConfigError("AI_PROVIDER=fake is refused when APP_ENV=production.")
            if not self.pii_redaction_enabled:
                raise ConfigError("PII_REDACTION_ENABLED cannot be false in production.")
        return self

    # ---- derived values -------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def secure_cookies(self) -> bool:
        return self.cookie_secure if self.cookie_secure is not None else self.is_production

    @property
    def ai_configured(self) -> bool:
        if self.ai_provider == "fake":
            return True
        return bool(self.nvidia_api_key and self.nvidia_api_key.get_secret_value().strip() and self.nvidia_model)

    def require_session_secret(self) -> bytes:
        if not self.session_secret or len(self.session_secret.get_secret_value()) < 32:
            raise ConfigError(
                "SESSION_SECRET is missing or shorter than 32 characters. "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        return self.session_secret.get_secret_value().encode()

    def sqlalchemy_url(self) -> str:
        if not self.database_url or not self.database_url.get_secret_value().strip():
            raise ConfigError(
                "DATABASE_URL is not set. Add your Supabase Postgres connection string to .env "
                "(Supabase dashboard → Connect → Session pooler)."
            )
        raw = self.database_url.get_secret_value().strip()
        parts = urlsplit(raw)
        scheme = parts.scheme.split("+")[0]
        if scheme not in ("postgresql", "postgres"):
            raise ConfigError("DATABASE_URL must be a PostgreSQL connection string (postgresql://…).")
        return urlunsplit(("postgresql+psycopg",) + tuple(parts[1:]))

    def db_connect_args(self) -> dict:
        url = urlsplit(self.sqlalchemy_url())
        host = url.hostname or ""
        local = host in ("", "localhost", "127.0.0.1") or "host=/" in url.query
        args: dict = {"connect_timeout": 15}
        sslmode = self.db_sslmode or ("disable" if local else "require")
        if "sslmode" not in url.query:
            args["sslmode"] = sslmode
        if url.port == 6543:  # Supabase transaction pooler cannot keep prepared statements
            args["prepare_threshold"] = None
        return args

    def __repr__(self) -> str:  # never print secrets
        return f"Settings(app_env={self.app_env!r}, ai_configured={self.ai_configured})"

    __str__ = __repr__


@lru_cache
def get_settings() -> Settings:
    return Settings()
