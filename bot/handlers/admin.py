"""
Admin panel — FSM-based user management.

Replaces the old ``_admin_waiting_for_user_id`` global dictionary with
proper aiogram FSM states.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from config import ADMIN_PAGE_SIZE, get_settings
from services.database import UserRepository

logger = logging.getLogger(__name__)

router = Router()

# ---------------------------------------------------------------------------
# FSM States
# ---------------------------------------------------------------------------


class AdminFindUser(StatesGroup):
    """FSM for the 'Find User' admin flow."""

    waiting_for_user_id = State()


# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------


def _is_admin(user_id: int) -> bool:
    """Check if ``user_id`` belongs to an admin."""
    return user_id in get_settings().admin_ids


# ---------------------------------------------------------------------------
# /admin — main menu
# ---------------------------------------------------------------------------


@router.message(Command("admin"))
async def admin_panel(message: Message) -> None:
    """Show the admin panel main menu."""
    logger.info(
        "Admin check: user_id=%s, ADMIN_IDS=%s",
        message.from_user.id,
        get_settings().admin_ids,
    )
    if not _is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет прав для этой команды.")
        return

    from bot.keyboards.admin_kb import admin_main_menu

    await message.answer(
        "👑 Админ-панель\nВыберите действие:",
        reply_markup=admin_main_menu(),
    )


# ---------------------------------------------------------------------------
# Back to main menu
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data == "admin_back")
async def admin_back(callback: CallbackQuery) -> None:
    """Return to the admin main menu."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён")
        return

    from bot.keyboards.admin_kb import admin_main_menu

    await callback.message.edit_text(
        "👑 Админ-панель\nВыберите действие:",
        reply_markup=admin_main_menu(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Find user (FSM)
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data == "admin_find_user")
async def admin_find_user_start(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Start the 'find user' FSM flow."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён")
        return

    await callback.message.answer("Введите ID пользователя в цифрах:")
    await state.set_state(AdminFindUser.waiting_for_user_id)
    await callback.answer()


@router.message(AdminFindUser.waiting_for_user_id, F.text)
async def admin_find_user_process(
    message: Message,
    state: FSMContext,
    user_repo: UserRepository,
) -> None:
    """Process the user ID input and show user details."""
    try:
        uid = int(message.text.strip())
    except ValueError:
        await message.answer("Некорректный ID. Введите число.")
        return

    user = await user_repo.get_by_id(uid)

    if user is None:
        await message.answer(f"❌ Пользователь с ID {uid} не найден.")
    else:
        status = "✅ активна" if user.subscription_active else "❌ неактивна"
        text = (
            f"🆔 ID: `{user.user_id}`\n"
            f"🎫 Попыток: {user.free_attempts_used}\n"
            f"💳 Подписка: {status}\n"
            f"📅 Регистрация: {user.created_at}\n"
        )

        from bot.keyboards.admin_kb import admin_user_detail

        await message.answer(
            text,
            parse_mode="Markdown",
            reply_markup=admin_user_detail(uid),
        )

    await state.clear()


# ---------------------------------------------------------------------------
# List users (paginated)
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data == "admin_list_users")
async def admin_list_users_cmd(
    callback: CallbackQuery,
    user_repo: UserRepository,
) -> None:
    """Show the first page of users."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён")
        return

    await _show_users_page(callback, 0, user_repo)


@router.callback_query(lambda c: c.data.startswith("admin_page_"))
async def admin_list_users_page(
    callback: CallbackQuery,
    user_repo: UserRepository,
) -> None:
    """Handle pagination: go to a specific page."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён")
        return

    offset = int(callback.data.split("_")[2])
    await _show_users_page(callback, offset, user_repo)


async def _show_users_page(
    callback: CallbackQuery,
    offset: int,
    user_repo: UserRepository,
) -> None:
    """Render a single page of the user list."""
    users = await user_repo.get_all(limit=ADMIN_PAGE_SIZE, offset=offset)

    if not users:
        text = "📭 Пользователи не найдены."
        from bot.keyboards.admin_kb import admin_back_button

        await callback.message.edit_text(text, reply_markup=admin_back_button())
        return

    # Build user list text
    text = "👥 *Список пользователей:*\n\n"
    for u in users:
        status = "✅ Активна" if u["subscription_active"] else "❌ Неактивна"
        text += (
            f"🆔 `{u['user_id']}`\n"
            f"   Попыток: {u['free_attempts_used']}\n"
            f"   Подписка: {status}\n"
            f"   Регистрация: {u['created_at']}\n"
            "   ➖➖➖➖\n"
        )

    # Check for next page
    next_users = await user_repo.get_all(
        limit=1, offset=offset + ADMIN_PAGE_SIZE
    )

    from bot.keyboards.admin_kb import admin_user_list

    await callback.message.edit_text(
        text,
        parse_mode="Markdown",
        reply_markup=admin_user_list(users, offset, bool(next_users)),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Toggle subscription
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data.startswith("admin_toggle_"))
async def admin_toggle_subscription(
    callback: CallbackQuery,
    user_repo: UserRepository,
) -> None:
    """Toggle subscription_active for a specific user."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён")
        return

    uid = int(callback.data.split("_")[2])
    user = await user_repo.get_by_id(uid)

    if user is None:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    new_status = not user.subscription_active
    await user_repo.set_subscription(uid, new_status)
    await callback.answer(
        f"Подписка для {uid} изменена: "
        f"{'активна' if new_status else 'неактивна'}"
    )

    # Refresh the user list (first page)
    await _show_users_page(callback, 0, user_repo)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data == "admin_stats")
async def admin_show_stats(
    callback: CallbackQuery,
    user_repo: UserRepository,
) -> None:
    """Show aggregate bot statistics."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён")
        return

    stats = await user_repo.get_stats()
    text = (
        f"📊 *Статистика бота*\n\n"
        f"👥 Всего пользователей: {stats['total_users']}\n"
        f"💳 Активных подписок: {stats['active_subs']}\n"
        f"🎙️ Всего использовано попыток: {stats['total_attempts']}\n"
    )

    from bot.keyboards.admin_kb import admin_back_button

    await callback.message.edit_text(
        text, parse_mode="Markdown", reply_markup=admin_back_button()
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Instruction popup
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data == "admin_switch_instruction")
async def admin_switch_instruction(callback: CallbackQuery) -> None:
    """Show a short how-to for toggling subscriptions."""
    await callback.answer(
        "Нажмите кнопку 'Переключить' рядом с нужным пользователем",
        show_alert=True,
    )
