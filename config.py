"""
Configuration module — Pydantic Settings.

Single source of truth for all environment variables.
Replaces scattered `os.getenv()` calls across the project.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from dotenv import load_dotenv

# Load .env immediately so Settings() reads them
load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (not from env)
# ---------------------------------------------------------------------------

FREE_ATTEMPTS_LIMIT: int = 2
"""How many free attempts a user gets before requiring payment."""

REMINDER_DELAY_SECONDS: int = 60
"""Seconds before a reminder is sent after /practice."""

ADMIN_PAGE_SIZE: int = 5
"""Number of users shown per page in the admin panel."""

REMINDER_TEXT: str = (
    "🎙 Please start recording your answer now!\n\n"
    "You received a topic — now it's time to speak. "
    "Record your answer and send it here as a voice message. "
    "We'll give you detailed feedback right away!"
)
"""Text sent as a reminder to the user."""


# ---------------------------------------------------------------------------
# Settings (from .env)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Settings:
    """Immutable settings container loaded from environment variables.

    Usage::

        settings = get_settings()
        print(settings.bot_token)
    """

    bot_token: str = ""
    openai_key: str = ""
    stripe_payment_link: str = "https://buy.stripe.com/your_link"
    stripe_webhook_secret: str = ""
    db_path: str = "ielts_bot.db"
    admin_ids: list[int] = field(default_factory=list)
    webhook_host: str = "0.0.0.0"
    webhook_port: int = 8080

    @classmethod
    def from_env(cls) -> Settings:
        """Build Settings by reading environment variables."""
        import os

        raw_admin = os.getenv("ADMIN_IDS", "")
        admin_ids = [
            int(x.strip())
            for x in raw_admin.split(",")
            if x.strip().isdigit()
        ]

        return cls(
            bot_token=os.getenv("BOT_TOKEN", ""),
            openai_key=os.getenv("OPENAI_KEY", ""),
            stripe_payment_link=os.getenv(
                "STRIPE_PAYMENT_LINK",
                "https://buy.stripe.com/your_link",
            ),
            stripe_webhook_secret=os.getenv("STRIPE_WEBHOOK_SECRET", ""),
            db_path=os.getenv("DB_PATH", "ielts_bot.db"),
            admin_ids=admin_ids,
            webhook_host=os.getenv("WEBHOOK_HOST", "0.0.0.0"),
            webhook_port=int(os.getenv("WEBHOOK_PORT", "8080")),
        )


# ---------------------------------------------------------------------------
# Module-level cache (singleton)
# ---------------------------------------------------------------------------

_settings: Settings | None = None


def get_settings() -> Settings:
    """Return cached Settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
        logger.info("Settings loaded: db_path=%s, admin_ids=%s", _settings.db_path, _settings.admin_ids)
    return _settings
