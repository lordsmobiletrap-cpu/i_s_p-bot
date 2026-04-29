"""
Handler for voice messages — transcribe, evaluate, reply.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.types import Message

from services.openai_service import OpenAIService
from services.reminder import ReminderService

logger = logging.getLogger(__name__)

router = Router()


async def _keep_typing(bot: Bot, chat_id: int, stop_event: asyncio.Event) -> None:
    """Send 'typing' chat action every 4 seconds until ``stop_event`` is set."""
    while not stop_event.is_set():
        try:
            await bot.send_chat_action(chat_id, "typing")
        except Exception:
            break
        await asyncio.sleep(4)


@router.message(F.voice)
async def process_audio(
    message: Message,
    bot: Bot,
    openai_service: OpenAIService,
    reminder: ReminderService,
) -> None:
    """Transcribe the voice message, evaluate it, and return feedback."""
    # Cancel any pending reminder
    reminder.cancel(message.chat.id)

    # Get file URL
    file_id = message.voice.file_id
    file = await bot.get_file(file_id)
    file_url = f"https://api.telegram.org/file/bot{bot.token}/{file.file_path}"

    await message.answer(
        "We're processing your submission. This may take up to 2 minutes. Please wait..."
    )

    # Show typing indicator during processing
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(
        _keep_typing(bot, message.chat.id, stop_typing)
    )

    try:
        transcript = await openai_service.transcribe_audio(file_url)
        evaluation = await openai_service.evaluate_speaking(transcript)
        await message.answer(evaluation)
    except Exception as e:
        logger.error(
            "Error processing audio for user %d: %s",
            message.from_user.id,
            e,
        )
        await message.answer(
            "Something went wrong while processing your audio. Please try again."
        )
    finally:
        stop_typing.set()
        typing_task.cancel()
