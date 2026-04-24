import asyncio
import logging
from os import getenv

from aiogram import Bot, Dispatcher
from dotenv import load_dotenv

from handlers.routes import router, on_startup, on_shutdown

# load_dotenv только здесь — единственная точка входа
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

TOKEN = getenv("BOT_TOKEN")

dp = Dispatcher()
dp.include_router(router=router)


async def main():
    bot = Bot(token=str(TOKEN))
    await on_startup()
    logging.info("Bot started.")
    try:
        await dp.start_polling(bot)
    finally:
        await on_shutdown()
        await bot.session.close()
        logging.info("Bot stopped.")


if __name__ == "__main__":
    asyncio.run(main())