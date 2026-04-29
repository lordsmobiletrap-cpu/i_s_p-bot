"""
Payment service — activate subscriptions and notify users.

Used by both the admin panel (manual toggle) and the Stripe webhook.
Replaces the separate DB + Bot logic in the old ``files/webhook.py``.
"""

from __future__ import annotations

import logging

from aiogram import Bot

from services.database import UserRepository

logger = logging.getLogger(__name__)


class PaymentService:
    """Handles subscription activation and user notification.

    Usage::

        payment = PaymentService(user_repo, bot_token)
        await payment.activate_subscription(user_id=12345)
    """

    def __init__(self, user_repo: UserRepository, bot_token: str) -> None:
        self._user_repo = user_repo
        self._bot_token = bot_token

    async def activate_subscription(self, user_id: int) -> bool:
        """Activate subscription for ``user_id`` and notify them.

        Returns:
            True if the user was found and updated.
        """
        success = await self._user_repo.set_subscription(user_id, True)
        if success:
            logger.info("Subscription activated for user %d", user_id)
            await self._notify_user(user_id)
        else:
            logger.warning("User %d not found — subscription not activated", user_id)
        return success

    async def _notify_user(self, user_id: int) -> None:
        """Send a confirmation message via Telegram."""
        if not self._bot_token:
            logger.warning("Cannot notify user %d: bot token is empty", user_id)
            return
        bot = Bot(token=self._bot_token)
        try:
            await bot.send_message(
                chat_id=user_id,
                text=(
                    "🎉 Payment confirmed! You now have full access.\n\n"
                    "Use /practice to start your next session — unlimited topics await!"
                ),
            )
        except Exception as e:
            logger.error("Could not notify user %d: %s", user_id, e)
        finally:
            await bot.session.close()
