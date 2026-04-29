"""
Reminder service — schedule / cancel delayed reminder messages.

Replaces the global ``_reminder_tasks: dict`` with an encapsulated class.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot

from config import REMINDER_DELAY_SECONDS, REMINDER_TEXT

logger = logging.getLogger(__name__)


class ReminderService:
    """Manages per-chat reminder tasks.

    Usage::

        reminder = ReminderService()
        reminder.schedule(bot, chat_id=12345)
        reminder.cancel(chat_id=12345)
    """

    def __init__(self) -> None:
        self._tasks: dict[int, asyncio.Task] = {}

    def schedule(
        self, bot: Bot, chat_id: int, delay: int = REMINDER_DELAY_SECONDS
    ) -> None:
        """Schedule or reschedule a reminder for ``chat_id``.

        Any existing reminder for the same chat is cancelled first.
        """
        self.cancel(chat_id)
        task = asyncio.create_task(self._send_after_delay(bot, chat_id, delay))
        self._tasks[chat_id] = task
        logger.debug("Reminder scheduled for chat %d in %ds", chat_id, delay)

    def cancel(self, chat_id: int) -> None:
        """Cancel a pending reminder for ``chat_id`` (if any)."""
        task = self._tasks.pop(chat_id, None)
        if task is not None and not task.done():
            task.cancel()
            logger.debug("Reminder cancelled for chat %d", chat_id)

    async def _send_after_delay(
        self, bot: Bot, chat_id: int, delay: int
    ) -> None:
        """Wait ``delay`` seconds, then send the reminder."""
        await asyncio.sleep(delay)
        try:
            await bot.send_message(chat_id=chat_id, text=REMINDER_TEXT)
            logger.info("Reminder sent to chat %d", chat_id)
        except Exception as e:
            logger.warning("Failed to send reminder to %d: %s", chat_id, e)
