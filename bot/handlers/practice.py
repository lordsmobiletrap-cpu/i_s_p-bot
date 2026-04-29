"""
Handlers for /practice command and the "to practice" callback.
"""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from config import FREE_ATTEMPTS_LIMIT
from services.database import UserRepository, TopicRepository
from services.openai_service import OpenAIService
from services.reminder import ReminderService

router = Router()


@router.callback_query(lambda c: c.data == "to practice")
async def to_practice_callback(callback: CallbackQuery) -> None:
    """Legacy callback button → remind user to use /practice."""
    await callback.answer("Here is your topic")
    await callback.message.answer("Use /practice to get a new topic.")


@router.message(Command("practice"))
async def cmd_practice(
    message: Message,
    bot: Bot,
    user_repo: UserRepository,
    topic_repo: TopicRepository,
    openai_service: OpenAIService,
    reminder: ReminderService,
) -> None:
    """Start a practice session: give a topic, check limits, schedule reminder."""
    user_id = message.from_user.id
    free_used, sub_active = await _get_attempt_status(user_repo, user_id)

    # Check free-trial limit
    if not sub_active and free_used >= FREE_ATTEMPTS_LIMIT:
        await _send_limit_reached(message)
        return

    # Grab a topic
    topic_text = await topic_repo.get_random_unused(user_id)
    if topic_text is None:
        topic_text = await openai_service.generate_topic()

    # Track usage for free users
    if not sub_active:
        await user_repo.increment_attempts(user_id)

    # Send topic
    text = (
        "Your topic for this practice session is:\n\n"
        f"{topic_text}\n"
        "---\n"
        "Use /practice to get another topic, if you didn't like this topic."
    )
    await message.answer(text=text)
    await message.answer(
        "You have <b>1 minute</b> to prepare your answer.\n"
        "We'll remind you when your time is up.",
        parse_mode="HTML",
    )

    # Schedule reminder
    reminder.schedule(bot=bot, chat_id=message.chat.id)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_attempt_status(
    user_repo: UserRepository, user_id: int
) -> tuple[int, bool]:
    """Return (free_attempts_used, subscription_active)."""
    user = await user_repo.get_or_create(user_id)
    return user.free_attempts_used, user.subscription_active


async def _send_limit_reached(message: Message) -> None:
    """Inform the user that their free attempts are exhausted."""
    from config import get_settings

    settings = get_settings()
    await message.answer(
        "❌ You've used your free trial attempts.\n\n"
        "To continue practicing, you'll need to purchase our premium plan, "
        "which offers lifetime unlimited access for a one-time payment of $5.\n\n"
        "This plan will give you unlimited practice sessions, "
        "allowing you to improve your speaking skills for the IELTS test.\n\n"
        f"Click here to purchase: {settings.stripe_payment_link}\n\n"
        "If you have any questions or feedback, "
        "please message the creator's personal Telegram account: @dkuzerbay",
        disable_web_page_preview=True,
    )
