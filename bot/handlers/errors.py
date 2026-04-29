"""
Global error handler for unhandled aiogram exceptions.
"""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.types import ErrorEvent

logger = logging.getLogger(__name__)

router = Router()


@router.errors()
async def global_error_handler(event: ErrorEvent) -> bool:
    """Catch any unhandled exception and log it.

    Returns True to indicate the error was consumed.
    """
    logger.exception(
        "Unhandled error: %s",
        event.exception,
        exc_info=event.exception,
    )
    # Returning True prevents the error from propagating further.
    return True
