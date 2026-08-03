"""Environment-driven settings.

Nothing here has a real default that would work in production; the app should
fail loudly rather than quietly run against the wrong database.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ENV_LOCAL = "local"
ENV_PROD = "prod"


@dataclass(frozen=True)
class Settings:
    app_env: str
    database_url: str
    pages_dir: Path
    site_base_url: str
    telegram_bot_token: str | None
    telegram_chat_id: str | None

    @property
    def is_local(self) -> bool:
        return self.app_env == ENV_LOCAL

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    def page_url(self, token: str) -> str:
        return f"{self.site_base_url.rstrip('/')}/d/{token}"


def load_settings() -> Settings:
    """Read settings from the environment, loading .env first if present."""
    load_dotenv()

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set. Copy .env.example to .env")

    app_env = os.environ.get("APP_ENV", ENV_LOCAL).strip().lower()
    if app_env not in (ENV_LOCAL, ENV_PROD):
        raise RuntimeError(f"APP_ENV must be '{ENV_LOCAL}' or '{ENV_PROD}', got {app_env!r}")

    return Settings(
        app_env=app_env,
        database_url=database_url,
        pages_dir=Path(os.environ.get("PAGES_DIR", "./pages")).expanduser().resolve(),
        site_base_url=os.environ.get("SITE_BASE_URL", "http://localhost:8000").strip(),
        telegram_bot_token=(os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip() or None,
        telegram_chat_id=(os.environ.get("TELEGRAM_CHAT_ID") or "").strip() or None,
    )
