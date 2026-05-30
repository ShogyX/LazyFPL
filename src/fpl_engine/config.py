"""Per-environment configuration and secrets.

Secrets are typed as ``SecretStr`` so they never appear in logs, tracebacks,
or ``repr()`` output. Settings load from environment variables (prefix ``FPL_``)
and, in dev, from a local ``.env`` file.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings. All fields overridable via ``FPL_*`` env vars."""

    model_config = SettingsConfigDict(
        env_prefix="FPL_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # Treat empty env vars (e.g. the blank `FPL_FPL_ENTRY_ID=` shipped in
        # .env.example) as unset, so they fall back to defaults instead of
        # failing int/typed parsing at startup.
        env_ignore_empty=True,
    )

    env: str = "dev"
    database_url: str = "postgresql+psycopg2://fpl:fpl@localhost:5432/fpl"
    log_level: str = "INFO"
    log_json: bool = True

    # Operator FPL auth
    fpl_entry_id: int | None = None
    fpl_session_cookie: SecretStr | None = None

    # Odds-API keys (free tiers)
    sharpapi_key: SecretStr | None = None
    sgo_key: SecretStr | None = None
    oddspapi_key: SecretStr | None = None
    oddsapi_io_key: SecretStr | None = None
    api_football_key: SecretStr | None = None

    # Betfair Exchange (Delayed App Key)
    betfair_app_key: SecretStr | None = None
    betfair_username: SecretStr | None = None
    betfair_password: SecretStr | None = None

    # Notifications
    pushover_token: SecretStr | None = None
    pushover_user: SecretStr | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: SecretStr | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str | None = None
    smtp_to: str | None = None

    def secret_values(self) -> list[str]:
        """Return the plaintext of every populated secret.

        Used only by the logging redaction filter so these strings can be
        scrubbed from any log line as defence-in-depth.
        """
        out: list[str] = []
        for name in self.model_fields:
            value = getattr(self, name)
            if isinstance(value, SecretStr):
                plain = value.get_secret_value()
                if plain:
                    out.append(plain)
        return out


@lru_cache
def get_settings() -> Settings:
    """Process-wide cached settings instance."""
    return Settings()
