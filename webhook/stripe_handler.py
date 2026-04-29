"""
Stripe webhook event handler.

Validates Stripe-Signature and calls ``PaymentService`` on
``checkout.session.completed`` events.

Note: ``stripe`` is imported lazily so that the bot works even
when the stripe package is not installed.
"""

from __future__ import annotations

import logging
from importlib import import_module

from aiohttp import web

from services.payment import PaymentService

logger = logging.getLogger(__name__)


def _get_stripe():
    """Lazy import of the ``stripe`` module."""
    return import_module("stripe")


def create_stripe_webhook_handler(
    stripe_webhook_secret: str,
    payment_service: PaymentService,
):
    """Create an aiohttp handler for Stripe webhook events.

    Usage::

        handler = create_stripe_webhook_handler(secret, payment_service)
        app.router.add_post("/webhook/stripe", handler)
    """

    async def handler(request: web.Request) -> web.Response:
        payload = await request.read()
        sig_header = request.headers.get("Stripe-Signature", "")

        # Verify signature
        try:
            stripe = _get_stripe()
            event = stripe.Webhook.construct_event(
                payload, sig_header, stripe_webhook_secret
            )
        except ImportError:
            logger.error("stripe package is not installed")
            return web.Response(status=500, text="stripe not installed")
        except stripe.errors.SignatureVerificationError:
            logger.warning("Invalid Stripe signature")
            return web.Response(status=400, text="Invalid signature")
        except Exception as e:
            logger.error("Error constructing Stripe event: %s", e)
            return web.Response(status=400, text="Bad request")

        # Handle only successful checkouts
        if event["type"] == "checkout.session.completed":
            session = event["data"]["object"]

            # Extract telegram user_id from metadata or client_reference_id
            user_id_str = (
                session.get("metadata", {}).get("user_id")
                or session.get("client_reference_id")
            )

            if not user_id_str:
                logger.warning(
                    "checkout.session.completed — user_id not found in metadata"
                )
                return web.Response(status=200, text="ok")

            try:
                user_id = int(user_id_str)
            except ValueError:
                logger.warning("Invalid user_id value: %s", user_id_str)
                return web.Response(status=200, text="ok")

            await payment_service.activate_subscription(user_id)

        else:
            logger.debug("Unhandled event type: %s", event["type"])

        return web.Response(status=200, text="ok")

    return handler
