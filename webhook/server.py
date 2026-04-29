"""
aiohttp webhook server for Stripe.

Can be run alongside the bot via ``asyncio.gather()`` or as a
standalone process via ``run_webhook_server()``.
"""

from __future__ import annotations

import asyncio
import logging

from aiohttp import web

from services.payment import PaymentService
from webhook.stripe_handler import create_stripe_webhook_handler

logger = logging.getLogger(__name__)


async def run_webhook_server(
    webhook_host: str = "0.0.0.0",
    webhook_port: int = 8080,
    stripe_webhook_secret: str = "",
    payment_service: PaymentService | None = None,
) -> None:
    """Start the Stripe webhook aiohttp server.

    This function runs forever (or until cancelled). Intended to be
    launched inside ``asyncio.gather()`` alongside ``dp.start_polling()``.
    """
    app = web.Application()

    if stripe_webhook_secret and payment_service:
        handler = create_stripe_webhook_handler(
            stripe_webhook_secret, payment_service
        )
        app.router.add_post("/webhook/stripe", handler)
        logger.info(
            "Webhook route registered: POST /webhook/stripe"
        )
    else:
        logger.warning(
            "Webhook server started without stripe secret or payment service — "
            "endpoint will return 404"
        )

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, webhook_host, webhook_port)
    await site.start()
    logger.info(
        "Webhook server listening on http://%s:%s/webhook/stripe",
        webhook_host,
        webhook_port,
    )

    # Keep alive forever
    await asyncio.Event().wait()
