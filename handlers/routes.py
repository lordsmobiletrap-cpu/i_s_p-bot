import asyncio
import io
import logging
from os import getenv

import aiohttp
import aiosqlite
from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

OPENAI_API_KEY = getenv("OPENAI_KEY")
STRIPE_PAYMENT_LINK = getenv("STRIPE_PAYMENT_LINK", "https://buy.stripe.com/your_link")
DB_PATH = getenv("DB_PATH", "bot.sql")
FREE_ATTEMPTS_LIMIT = 2
REMINDER_DELAY_SECONDS = 1 * 60

# AsyncOpenAI — не блокирует event loop
client = AsyncOpenAI(api_key=OPENAI_API_KEY)
router = Router()

_reminder_tasks: dict[int, asyncio.Task] = {}
_db: aiosqlite.Connection | None = None

REMINDER_TEXT = (
    "🎙 Please start recording your answer now!\n\n"
    "You received a topic — now it's time to speak. "
    "Record your answer and send it here as a voice message. We'll give you detailed feedback right away!"
)


# ----------  Database  ----------

def get_db() -> aiosqlite.Connection:
    if _db is None:
        raise RuntimeError("Database is not initialized. Call on_startup() first.")
    return _db


async def init_db() -> None:
    global _db
    _db = await aiosqlite.connect(DB_PATH, timeout=30)
    await _db.execute("PRAGMA journal_mode=DELETE")
    await _db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            free_attempts_used INTEGER DEFAULT 0,
            subscription_active BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await _db.execute("""
        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            category TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await _db.execute("""
        CREATE TABLE IF NOT EXISTS user_topics (
            user_id INTEGER,
            topic_id INTEGER,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, topic_id),
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            FOREIGN KEY (topic_id) REFERENCES topics(id)
        )
    """)
    await _db.commit()
    logger.info("Database initialized: %s", DB_PATH)


async def close_db() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None
        logger.info("Database connection closed.")


async def get_or_create_user(user_id: int) -> tuple[int, bool]:
    """Возвращает (free_attempts_used, subscription_active)."""
    db = get_db()
    await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    await db.commit()
    async with db.execute(
        "SELECT free_attempts_used, subscription_active FROM users WHERE user_id = ?",
        (user_id,)
    ) as cursor:
        row = await cursor.fetchone()
    return row[0], bool(row[1])


async def increment_user_attempt(user_id: int) -> None:
    db = get_db()
    await db.execute(
        "UPDATE users SET free_attempts_used = free_attempts_used + 1 WHERE user_id = ?",
        (user_id,)
    )
    await db.commit()


async def get_random_unused_topic_for_user(user_id: int) -> str | None:
    """Возвращает текст случайного вопроса, который ещё не был показан пользователю."""
    db = get_db()
    async with db.execute("""
        SELECT t.id, t.text FROM topics t
        WHERE t.id NOT IN (
            SELECT topic_id FROM user_topics WHERE user_id = ?
        )
        ORDER BY RANDOM() LIMIT 1
    """, (user_id,)) as cursor:
        row = await cursor.fetchone()

    if row:
        topic_id, topic_text = row
        await db.execute(
            "INSERT INTO user_topics (user_id, topic_id) VALUES (?, ?)",
            (user_id, topic_id)
        )
        await db.commit()
        return topic_text
    return None


async def mark_user_paid(user_id: int) -> bool:
    """Ставит subscription_active=1. Возвращает True если пользователь найден."""
    db = get_db()
    async with db.execute(
        "UPDATE users SET subscription_active = 1 WHERE user_id = ?", (user_id,)
    ) as cursor:
        await db.commit()
        return cursor.rowcount > 0


# ----------  GPT Helpers  ----------

async def get_random_topic_gpt() -> str:
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an IELTS Speaking examiner. Generate one realistic IELTS Speaking Part 2 topic.\n\n"
                    "Follow this exact structure:\n\n"
                    "Title: [short phrase]\n\n"
                    "You should say:\n"
                    "- [first point]\n"
                    "- [second point]\n"
                    "- [third point]\n\n"
                    "And explain why / how [main question].\n\n"
                    "Rules: topics must be common for IELTS (people, places, events, objects, activities). "
                    "Do not add extra text. Vary the bullet points. Keep language neutral and exam-appropriate."
                )
            },
            {"role": "user", "content": "Generate one IELTS Speaking Part 2 topic."}
        ],
        temperature=0.9
    )
    content = response.choices[0].message.content
    if not content:
        raise ValueError("GPT returned an empty topic.")
    return content


async def transcribe_audio(file_url: str) -> str:
    async with aiohttp.ClientSession() as session:
        async with session.get(file_url) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Failed to download audio: HTTP {resp.status}")
            audio_bytes = await resp.read()

    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = "audio.ogg"
    transcription = await client.audio.transcriptions.create(
        model="whisper-1",
        file=audio_file,
        language="en"
    )
    return transcription.text


async def speaking_evaluation_gpt(text: str) -> str:
    prompt = """You are an experienced IELTS Speaking examiner. Your task is to provide detailed, constructive feedback on a user's spoken response based on its transcript.

IMPORTANT: You do NOT hear the audio - only the text. Therefore your assessment of Pronunciation will be limited to what can be inferred from the text:
- repeated phonetic patterns (e.g., "tree" instead of "three" may indicate a /θ/ problem)
- unnatural contractions or distortions
- filler sounds like "uh", "um" or ellipses that mimic pauses
You MUST explicitly state this limitation in your response.

Assessment rules (updated for 2026):
- Natural, spontaneous speech is valued more than memorised templates.
- Short thinking pauses and self-correction are acceptable.
- Avoid "right/wrong" judgement - instead give actionable advice.

Criteria (each of the 4 must be evaluated separately):
1. Fluency & Coherence
2. Lexical Resource
3. Grammatical Range & Accuracy
4. Pronunciation (limited based on text only)

Response format strictly as follows:

1. **Fluency and Coherence:**
   [detailed comment, 2-3 sentences]

2. **Lexical Resource:**
   [detailed comment, 2-3 sentences]

3. **Grammatical Range and Accuracy:**
   [detailed comment, 2-3 sentences]

4. **Pronunciation (approximate, text-based):**
   [comment + mandatory disclaimer about limitation]

### Indicative Score
[overall band from 0 to 9, in 0.5 increments, e.g. Band 5.0]

### Final Assessment
[2-3 sentences with key takeaways and specific advice for improvement]
    """
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": text}
        ],
        temperature=0.7
    )
    content = response.choices[0].message.content
    if not content:
        raise ValueError("GPT returned an empty evaluation.")
    return content


# ----------  Reminder  ----------

async def send_reminder(bot: Bot, chat_id: int, delay: int = REMINDER_DELAY_SECONDS) -> None:
    await asyncio.sleep(delay)
    try:
        await bot.send_message(chat_id=chat_id, text=REMINDER_TEXT)
    except Exception as e:
        logger.warning("[Reminder] Failed to send reminder to %d: %s", chat_id, e)


# ----------  Typing action loop  ----------

async def keep_typing(bot: Bot, chat_id: int, stop_event: asyncio.Event) -> None:
    """Отправляет 'typing' каждые 4 секунды пока не установлен stop_event."""
    while not stop_event.is_set():
        try:
            await bot.send_chat_action(chat_id, "typing")
        except Exception:
            break
        await asyncio.sleep(4)


# ----------  Handlers  ----------

@router.callback_query(lambda c: c.data == "to practice")
async def to_practice_inlinebtn(callback: CallbackQuery):
    await callback.answer("Here is your topic")
    await callback.message.answer("Use /practice to get a new topic.")


@router.message(Command("start"))
async def cmd_start(message: Message):
    text = (
        "Here's how to get started:\n\n"
        "1. To start a practice session, reply /practice.\n\n"
        "2. You'll receive a topic for your speaking practice.\n\n"
        "3. Take 1 minute to prepare your thoughts.\n\n"
        "4. After your preparation, send us your answer as a voice message.\n\n"
        "We will analyze your voice message and provide constructive feedback on your performance.\n\n"
        "We strongly recommend that you pin this chat at the top of your Telegram chats list, so that you can easily find it when you need to practice.\n\n"
        "If you have any questions or feedback, please message the creator's personal Telegram account: @dkuzerbay"
    )
    await message.answer(text=text, parse_mode="HTML")


@router.message(Command("support"))
async def support_cmd(message: Message):
    await cmd_start(message)


@router.message(Command("practice"))
async def cmd_practice(message: Message, bot: Bot):
    user_id = message.from_user.id
    free_used, sub_active = await get_or_create_user(user_id)

    if not sub_active and free_used >= FREE_ATTEMPTS_LIMIT:
        await message.answer(
            "❌ You've used your free trial attempts.\n\n"
            f"To continue practicing, please subscribe:\n{STRIPE_PAYMENT_LINK}",
            disable_web_page_preview=True
        )
        return

    topic_text = await get_random_unused_topic_for_user(user_id)
    if topic_text is None:
        topic_text = await get_random_topic_gpt()

    if not sub_active:
        await increment_user_attempt(user_id)

    text = (
        "Your topic for this practice session is:\n\n"
        f"{topic_text}\n"
        "---\n"
        "Use /practice to get another topic, if you didn't like this topic."
    )
    await message.answer(text=text, parse_mode="HTML")
    await message.answer(
        "You have <b>1 minute</b> to prepare your answer.\nWe'll remind you when your time is up.",
        parse_mode="HTML"
    )

    existing = _reminder_tasks.get(message.chat.id)
    if existing and not existing.done():
        existing.cancel()
    task = asyncio.create_task(send_reminder(bot=bot, chat_id=message.chat.id))
    _reminder_tasks[message.chat.id] = task


@router.message(F.voice)
async def process_audio(message: Message, bot: Bot):
    # Отменяем напоминание
    task = _reminder_tasks.pop(message.chat.id, None)
    if task and not task.done():
        task.cancel()

    file_id = message.voice.file_id
    file = await bot.get_file(file_id)
    file_url = f"https://api.telegram.org/file/bot{bot.token}/{file.file_path}"

    await message.answer("We're processing your submission. This may take up to 2 minutes. Please wait..")

    # Крутим typing пока идёт обработка
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(keep_typing(bot, message.chat.id, stop_typing))

    try:
        audio_to_text = await transcribe_audio(file_url)
        result = await speaking_evaluation_gpt(audio_to_text)
        await message.answer(result)
    except Exception as e:
        logger.error("Error processing audio for user %d: %s", message.from_user.id, e)
        await message.answer("Something went wrong while processing your audio. Please try again.")
    finally:
        stop_typing.set()
        typing_task.cancel()


# ----------  Lifecycle  ----------

async def on_startup() -> None:
    await init_db()


async def on_shutdown() -> None:
    await close_db()