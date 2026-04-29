"""
Inline keyboard factories for the admin panel.
"""

from __future__ import annotations

from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def admin_main_menu() -> InlineKeyboardMarkup:
    """Main admin panel menu."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📋 Список пользователей",
                    callback_data="admin_list_users",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔍 Найти пользователя",
                    callback_data="admin_find_user",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📊 Статистика",
                    callback_data="admin_stats",
                )
            ],
        ]
    )


def admin_user_list(
    users: list[dict[str, Any]],
    offset: int,
    has_next: bool,
) -> InlineKeyboardMarkup:
    """User list page with per-user toggle buttons + pagination."""
    # Per-user toggle buttons
    user_buttons = [
        [
            InlineKeyboardButton(
                text=f"🔄 Переключить {u['user_id']}",
                callback_data=f"admin_toggle_{u['user_id']}",
            )
        ]
        for u in users
    ]

    # Navigation row
    nav_buttons = []
    if offset > 0:
        nav_buttons.append(
            InlineKeyboardButton(
                text="◀️ Назад",
                callback_data=f"admin_page_{offset - 5}",
            )
        )
    if has_next:
        nav_buttons.append(
            InlineKeyboardButton(
                text="Вперёд ▶️",
                callback_data=f"admin_page_{offset + 5}",
            )
        )
    nav_buttons.append(
        InlineKeyboardButton(
            text="🔄 Обновить",
            callback_data=f"admin_page_{offset}",
        )
    )

    # Bottom action buttons
    bottom_buttons = [
        [
            InlineKeyboardButton(
                text="🏠 В админку", callback_data="admin_back"
            )
        ],
        [
            InlineKeyboardButton(
                text="✏️ Переключить подписку",
                callback_data="admin_switch_instruction",
            )
        ],
    ]

    return InlineKeyboardMarkup(
        inline_keyboard=user_buttons + [nav_buttons] + bottom_buttons
    )


def admin_user_detail(uid: int) -> InlineKeyboardMarkup:
    """Single user detail view with toggle + back."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Переключить подписку",
                    callback_data=f"admin_toggle_{uid}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="◀️ Назад в админку",
                    callback_data="admin_back",
                )
            ],
        ]
    )


def admin_back_button() -> InlineKeyboardMarkup:
    """Simple 'Back to admin' button."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="◀️ Назад в админку",
                    callback_data="admin_back",
                )
            ],
        ]
    )
