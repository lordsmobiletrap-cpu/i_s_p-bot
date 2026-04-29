"""
Fallback handler for plain text messages that are not commands.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

router = Router()


@router.message(F.text & ~F.command)
async def handle_unknown_text(message: Message) -> None:
    """Ignore unrecognised text messages silently.

    In the future this can be replaced with a helpful hint.
    """
    # Currently no-op — the bot only responds to commands and voice messages.
    pass
