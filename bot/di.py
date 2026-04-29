"""
Dependency Injection — factory that creates Bot, Dispatcher, and all services.

All dependencies are registered in the Dispatcher so that handlers can
receive them via type-annotated parameters.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from aiogram import Bot, Dispatcher

from bot.router import router
from config import Settings
from services.database import Database, UserRepository, TopicRepository
from services.openai_service import OpenAIService
from services.payment import PaymentService
from services.reminder import ReminderService

logger = logging.getLogger(__name__)


@dataclass
class Services:
    """Container for all service instances."""

    settings: Settings
    db: Database
    user_repo: UserRepository
    topic_repo: TopicRepository
    openai: OpenAIService
    reminder: ReminderService
    payment: PaymentService


def create_bot_and_dispatcher(
    settings: Settings | None = None,
) -> tuple[Bot, Dispatcher, Services]:
    """Factory — build Bot, Dispatcher and all services.

    Args:
        settings: Optional Settings instance. Loaded from env if not provided.

    Returns:
        A tuple of (Bot, Dispatcher, Services).
    """
    if settings is None:
        from config import get_settings

        settings = get_settings()

    bot = Bot(token=settings.bot_token)

    # --- Services ---
    db = Database(settings.db_path)
    user_repo = UserRepository(db)
    topic_repo = TopicRepository(db)
    openai = OpenAIService(settings.openai_key)
    reminder = ReminderService()
    payment = PaymentService(user_repo, settings.bot_token)

    services = Services(
        settings=settings,
        db=db,
        user_repo=user_repo,
        topic_repo=topic_repo,
        openai=openai,
        reminder=reminder,
        payment=payment,
    )

    # --- Dispatcher with DI ---
    dp = Dispatcher()

    # Register services as global DI dependencies
    dp["services"] = services
    dp["db"] = db
    dp["user_repo"] = user_repo
    dp["topic_repo"] = topic_repo
    dp["openai"] = openai  # injected via name "openai_service" → needs alias
    dp["openai_service"] = openai
    dp["reminder"] = reminder
    dp["payment"] = payment
    dp["admin_ids"] = settings.admin_ids

    dp.include_router(router)

    logger.info(
        "Bot and services created. DB: %s, Admins: %s",
        settings.db_path,
        settings.admin_ids,
    )

    return bot, dp, services
