"""
Stripe Webhook — aiohttp сервер.

Запуск отдельно от бота:
    python webhook.py

Или вместе с ботом через asyncio.gather() в main.py:
    await asyncio.gather(dp.start_polling(bot), run_webhook_server())

Переменные окружения (.env):
    STRIPE_WEBHOOK_SECRET  — секрет из Stripe Dashboard → Webhooks
    WEBHOOK_HOST           — хост для прослушивания (default: 0.0.0.0)
    WEBHOOK_PORT           — порт (default: 8080)
    BOT_TOKEN              — токен бота (чтобы уведомить пользователя)

Важно — передача user_id в Stripe:
    Используйте динамический Checkout Session (не статичную Payment Link),
    чтобы передать telegram user_id в metadata:

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{"price": "price_xxx", "quantity": 1}],
        mode="subscription",  # или "payment"
        success_url="https://t.me/your_bot",
        cancel_url="https://t.me/your_bot",
        metadata={"user_id": str(telegram_user_id)},
        client_reference_id=str(telegram_user_id),
    )

    Вебхук читает metadata["user_id"] из события checkout.session.completed.
"""

import asyncio
import json
from os import getenv

import aiosqlite
import stripe
from aiohttp import web
from aiogram import Bot
from dotenv import load_dotenv

load_dotenv()

STRIPE_WEBHOOK_SECRET = getenv("STRIPE_WEBHOOK_SECRET", "")
DB_PATH = getenv("DB_PATH", "bot.db")
BOT_TOKEN = getenv("BOT_TOKEN", "")
WEBHOOK_HOST = getenv("WEBHOOK_HOST", "0.0.0.0")
WEBHOOK_PORT = int(getenv("WEBHOOK_PORT", "8080"))


# ---------------------------------------------------------------------------
# БД
# ---------------------------------------------------------------------------

async def mark_user_paid(user_id: int) -> bool:
    """Ставит is_paid=1. Возвращает True если пользователь найден."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE users SET is_paid = 1 WHERE user_id = ?", (user_id,)
        )
        await db.commit()
        return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Уведомление пользователя
# ---------------------------------------------------------------------------

async def notify_user(user_id: int) -> None:
    if not BOT_TOKEN:
        return
    bot = Bot(token=BOT_TOKEN)
    try:
        await bot.send_message(
            chat_id=user_id,
            text=(
                "🎉 Payment confirmed! You now have full access.\n\n"
                "Use /practice to start your next session — unlimited topics await!"
            )
        )
    except Exception as e:
        print(f"[Webhook] Could not notify user {user_id}: {e}")
    finally:
        await bot.session.close()


# ---------------------------------------------------------------------------
# Обработчик вебхука
# ---------------------------------------------------------------------------

async def stripe_webhook(request: web.Request) -> web.Response:
    payload = await request.read()
    sig_header = request.headers.get("Stripe-Signature", "")

    # Верификация подписи Stripe
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except stripe.errors.SignatureVerificationError:
        print("[Webhook] Invalid Stripe signature")
        return web.Response(status=400, text="Invalid signature")
    except Exception as e:
        print(f"[Webhook] Error constructing event: {e}")
        return web.Response(status=400, text="Bad request")

    # Обрабатываем только успешную оплату
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]

        # Читаем telegram user_id из metadata или client_reference_id
        user_id_str = (
            session.get("metadata", {}).get("user_id")
            or session.get("client_reference_id")
        )

        if not user_id_str:
            print("[Webhook] checkout.session.completed — user_id not found in metadata")
            return web.Response(status=200, text="ok")

        try:
            user_id = int(user_id_str)
        except ValueError:
            print(f"[Webhook] Invalid user_id value: {user_id_str}")
            return web.Response(status=200, text="ok")

        found = await mark_user_paid(user_id)
        if found:
            print(f"[Webhook] User {user_id} marked as paid")
            await notify_user(user_id)
        else:
            print(f"[Webhook] User {user_id} not found in DB — payment recorded but user unknown")

    else:
        # Остальные события игнорируем
        print(f"[Webhook] Unhandled event type: {event['type']}")

    return web.Response(status=200, text="ok")


# ---------------------------------------------------------------------------
# Запуск сервера
# ---------------------------------------------------------------------------

async def run_webhook_server() -> None:
    app = web.Application()
    app.router.add_post("/webhook/stripe", stripe_webhook)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, WEBHOOK_HOST, WEBHOOK_PORT)
    await site.start()
    print(f"[Webhook] Listening on http://{WEBHOOK_HOST}:{WEBHOOK_PORT}/webhook/stripe")

    # Держим сервер живым
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(run_webhook_server())
