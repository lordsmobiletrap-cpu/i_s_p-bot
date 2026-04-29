"""
IELTS Speaking Practice Bot — entry point.

Launches the aiogram polling bot together with the Stripe webhook
server (aiohttp) in a single asyncio event loop.

Usage:
    python main.py
"""

from __future__ import annotations

import asyncio
import logging

from config import get_settings
from bot.di import create_bot_and_dispatcher
from webhook.server import run_webhook_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Initialise services and run bot + webhook concurrently."""
    settings = get_settings()
    bot, dp, services = create_bot_and_dispatcher(settings)

    # Lifecycle: connect DB
    await services.db.connect()
    await services.db.init_schema()

    logger.info(
        "Starting bot (polling) + webhook (%s:%s)...",
        settings.webhook_host,
        settings.webhook_port,
    )

    async def polling() -> None:
        """Run aiogram long-polling."""
        await dp.start_polling(bot)

    async def webhook_server() -> None:
        """Run Stripe webhook aiohttp server."""
        await run_webhook_server(
            webhook_host=settings.webhook_host,
            webhook_port=settings.webhook_port,
            stripe_webhook_secret=settings.stripe_webhook_secret,
            payment_service=services.payment,
        )

    try:
        # Run both concurrently
        await asyncio.gather(polling(), webhook_server())
    finally:
        await services.db.close()
        await bot.session.close()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    asyncio.run(main())
