"""Application settings, read from environment variables (and an optional .env file).

Every setting has one name, one type and one default, so the app no longer calls os.getenv in
scattered places and a typo in a variable name is easy to spot.
"""
from datetime import timedelta

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_DEFAULT_KEY = "dev-only-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    secret_key: str = INSECURE_DEFAULT_KEY
    database_url: str = "sqlite:///tylonerp.db"
    cookie_secure: bool = True
    admin_email: str = "admin@erp.co.zw"
    admin_password: str | None = None

    db_pool_size: int = Field(10, ge=1)
    db_max_overflow: int = Field(20, ge=0)

    # Set ENV=production, or run on Railway (RAILWAY_ENVIRONMENT is injected), to enforce production rules.
    env: str = "development"
    railway_environment: str | None = None

    login_rate_limit: str = "10 per minute"
    ratelimit_enabled: bool = True
    ratelimit_storage_uri: str = "memory://"
    session_days: int = Field(30, ge=1)

    @field_validator("database_url")
    @classmethod
    def _normalise_database_url(cls, url: str) -> str:
        # Railway and Heroku hand out postgres://, SQLAlchemy needs postgresql://
        return url.replace("postgres://", "postgresql://", 1) if url.startswith("postgres://") else url

    @property
    def is_production(self) -> bool:
        return self.env.lower() == "production" or bool(self.railway_environment)

    @property
    def session_lifetime(self) -> timedelta:
        return timedelta(days=self.session_days)

    def validate_for_runtime(self) -> list[str]:
        """Raise on settings that make a production deployment unsafe; return softer warnings."""
        warnings: list[str] = []
        if self.is_production and self.secret_key == INSECURE_DEFAULT_KEY:
            raise RuntimeError("SECRET_KEY is not set. Refusing to start in production with the built-in dev key.")
        if self.is_production and len(self.secret_key) < 32:
            warnings.append("SECRET_KEY is shorter than 32 characters; use a long random value.")
        if self.is_production and self.database_url.startswith("sqlite"):
            warnings.append("Using SQLite in production: data is lost on redeploy unless a volume is mounted. "
                            "Set DATABASE_URL to a Postgres service.")
        if self.is_production and not self.cookie_secure:
            warnings.append("COOKIE_SECURE is off in production; session cookies can travel over http.")
        return warnings


def load_settings(**overrides) -> Settings:
    return Settings(**overrides)
