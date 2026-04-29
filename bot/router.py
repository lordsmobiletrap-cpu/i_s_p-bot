"""
Root router — imports and includes all handler routers.
"""

from __future__ import annotations

from aiogram import Router

from bot.handlers import start, practice, voice, admin, text, errors

router = Router()

router.include_router(start.router)
router.include_router(practice.router)
router.include_router(voice.router)
router.include_router(admin.router)
router.include_router(text.router)
router.include_router(errors.router)
