"""
Common (non-admin) keyboard factories.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def practice_start_keyboard() -> InlineKeyboardMarkup:
    """Keyboard shown on /start to quickly begin practice."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎤 Start Practice",
                    callback_data="to_practice",
                )
            ],
        ]
    )
