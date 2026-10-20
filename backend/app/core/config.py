"""Process settings, read once from the environment (and an optional .env file).

Only bootstrap secrets live here. Everything a user configures (API tokens, bot keys,
sync intervals, the Claude key) is stored encrypted in the database and edited in the panel.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Telegram Ads Manager"
    app_version: str = Field("dev", alias="APP_VERSION")

    data_dir: Path = Field(BACKEND_DIR / "data", alias="DATA_DIR")
    frontend_dist: Path = Field(BACKEND_DIR.parent / "frontend" / "dist", alias="FRONTEND_DIST")

    admin_password: SecretStr = Field(SecretStr(""), alias="ADMIN_PASSWORD")
    session_secret: SecretStr = Field(SecretStr(""), alias="SESSION_SECRET")
    encryption_key: SecretStr = Field(SecretStr(""), alias="ENCRYPTION_KEY")
    cookie_secure: bool = Field(True, alias="COOKIE_SECURE")

    # External API bases are overridable so tests can point at local mocks.
    telegram_ads_api_base: str = Field("https://promoteapi.telegram.org", alias="TG_ADS_API_BASE")
    anthropic_api_base: str = Field("https://api.anthropic.com", alias="ANTHROPIC_API_BASE")

    # Telegram refuses to withdraw budget from an ad that was active in the last 10 minutes.
    withdraw_delay_seconds: int = Field(660, alias="WITHDRAW_DELAY_SECONDS")
    scheduler_enabled: bool = Field(True, alias="SCHEDULER_ENABLED")
    # Lower bound for every sync interval a user can set; tests lower it.
    min_sync_seconds: int = Field(10, alias="MIN_SYNC_SECONDS")

    # One-time import of the token used by v1 (psychonet-ads) installs.
    legacy_tg_ads_token: SecretStr = Field(SecretStr(""), alias="LEGACY_TG_ADS_TOKEN")

    log_level: str = Field("INFO", alias="LOG_LEVEL")

    @property
    def database_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.database_path}"

    @property
    def sync_database_url(self) -> str:
        return f"sqlite:///{self.database_path}"

    def problems(self) -> list[str]:
        """Configuration errors shown on the login page instead of starting half-configured."""
        out = []
        if len(self.admin_password.get_secret_value()) < 8:
            out.append("ADMIN_PASSWORD باید دست‌کم ۸ کاراکتر باشد.")
        if len(self.session_secret.get_secret_value()) < 32:
            out.append("SESSION_SECRET باید دست‌کم ۳۲ کاراکتر تصادفی باشد.")
        if not self.encryption_key.get_secret_value():
            out.append("ENCRYPTION_KEY تنظیم نشده است.")
        return out


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    return s
