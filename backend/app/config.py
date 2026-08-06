from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TIMEME_", extra="ignore")

    # Where the SQLite file lives. In the container this is a mounted volume.
    db_path: str = "/data/timeme.db"

    # Signs the session JWT. Changing it logs everybody out.
    secret_key: str = "dev-insecure-change-me"

    # One timezone for the whole instance: all day boundaries are drawn in it.
    timezone: str = "Europe/Berlin"

    # Session lifetime in hours.
    session_hours: int = 24 * 14

    # Nominal hours a newly created user gets, in minutes.
    default_nominal_minutes: int = 7 * 60

    # Set false when running behind plain HTTP (local dev).
    cookie_secure: bool = True

    # Static SPA build served by the API. Empty disables static serving.
    static_dir: str = "/app/static"

    @property
    def tz(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise RuntimeError(f"Unknown TIMEME_TIMEZONE {self.timezone!r}") from exc


@lru_cache
def get_settings() -> Settings:
    return Settings()
