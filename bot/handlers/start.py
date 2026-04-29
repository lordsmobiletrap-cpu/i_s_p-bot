"""
Handlers for /start and /support commands.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()

START_TEXT = (
    "Here's how to get started:\n\n"
    "1. To start a practice session, reply /practice.\n\n"
    "2. You'll receive a topic for your speaking practice.\n\n"
    "3. Take 1 minute to prepare your thoughts.\n\n"
    "4. After your preparation, send us your answer as a voice message.\n\n"
    "We will analyze your voice message and provide constructive feedback on your performance.\n\n"
    "We strongly recommend that you pin this chat at the top of your Telegram chats list, "
    "so that you can easily find it when you need to practice.\n\n"
    "If you have any questions or feedback, "
    "please message the creator's personal Telegram account: @dkuzerbay"
)


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    """Send welcome message with instructions."""
    await message.answer(text=START_TEXT)


@router.message(Command("support"))
async def cmd_support(message: Message) -> None:
    """Redirect to /start handler (same welcome text)."""
    await cmd_start(message)
