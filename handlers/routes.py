import asyncio
import io
import logging
from os import getenv

import aiohttp
import aiosqlite
from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import (
        CallbackQuery, 
        Message,
        InlineKeyboardMarkup, 
        InlineKeyboardButton
    )
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


# ----------  Admin helpers  ----------

# Загружаем ID администраторов из переменной окружения
_ADMIN_IDS_RAW = getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(x.strip()) for x in _ADMIN_IDS_RAW.split(",") if x.strip().isdigit()]

# Обработчик для поиска пользователя по ID (ожидание текста)
_admin_waiting_for_user_id = {}

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

async def get_all_users(limit: int = 20, offset: int = 0) -> list[dict]:
    """Возвращает список пользователей с пагинацией."""
    db = get_db()
    async with db.execute(
        "SELECT user_id, free_attempts_used, subscription_active, created_at FROM users ORDER BY user_id LIMIT ? OFFSET ?",
        (limit, offset)
    ) as cursor:
        rows = await cursor.fetchall()
    return [
        {
            "user_id": row[0],
            "free_attempts_used": row[1],
            "subscription_active": bool(row[2]),
            "created_at": row[3],
        }
        for row in rows
    ]

async def get_user_by_id(user_id: int) -> dict | None:
    db = get_db()
    async with db.execute(
        "SELECT user_id, free_attempts_used, subscription_active, created_at FROM users WHERE user_id = ?",
        (user_id,)
    ) as cursor:
        row = await cursor.fetchone()
    if not row:
        return None
    return {
        "user_id": row[0],
        "free_attempts_used": row[1],
        "subscription_active": bool(row[2]),
        "created_at": row[3],
    }

async def update_subscription(user_id: int, active: bool) -> bool:
    """Устанавливает subscription_active = active. Возвращает True, если запись обновлена."""
    db = get_db()
    await db.execute(
        "UPDATE users SET subscription_active = ? WHERE user_id = ?",
        (1 if active else 0, user_id)
    )
    await db.commit()
    # Проверяем, был ли обновлён хотя бы один ряд
    async with db.execute("SELECT changes()") as cur:
        changed = await cur.fetchone()
    return changed[0] > 0



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

# ----------  Admin handlers  ----------

# def admin_only(handler):
#     """Декоратор для проверки прав администратора."""
#     async def wrapper(message: Message, *args, **kwargs):
#         if not is_admin(message.from_user.id):
#             await message.answer("⛔ У вас нет прав для этой команды.")
#             return
#         return await handler(message, *args, **kwargs)
#     return wrapper

@router.message(Command("admin"))
# @admin_only
async def admin_panel(message: Message):
    logger.info(f"Admin check: user_id={message.from_user.id}, ADMIN_IDS={ADMIN_IDS}")
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет прав для этой команды.")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Список пользователей", callback_data="admin_list_users")],
        [InlineKeyboardButton(text="🔍 Найти пользователя", callback_data="admin_find_user")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
    ])
    await message.answer("👑 Админ-панель\nВыберите действие:", reply_markup=keyboard)

@router.callback_query(lambda c: c.data == "admin_back")
async def admin_back(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Список пользователей", callback_data="admin_list_users")],
        [InlineKeyboardButton(text="🔍 Найти пользователя", callback_data="admin_find_user")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
    ])
    await callback.message.edit_text("👑 Админ-панель\nВыберите действие:", reply_markup=keyboard)
    await callback.answer()

@router.callback_query(lambda c: c.data == "admin_switch_instruction")
async def admin_switch_instruction(callback: CallbackQuery):
    await callback.answer("Нажмите кнопку 'Переключить' рядом с нужным пользователем", show_alert=True)


@router.callback_query(lambda c: c.data.startswith("admin_"))
async def admin_callback_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    if not is_admin(user_id):
        await callback.answer("Доступ запрещён", show_alert=True)
        await callback.message.delete()
        return

    data = callback.data
    if data == "admin_list_users":
        # Показываем пользователей с пагинацией (страницы по 5)
        await show_users_page(callback, offset=0)
    elif data == "admin_find_user":
        await callback.message.answer("Введите ID пользователя в цифрах:")
        # Сохраняем состояние, что ожидаем ввод ID
        # Проще: следующий хендлер на текстовые сообщения с флагом
        # Можно использовать FSM, но для простоты — глобальный dict ожиданий
        # Реализуем через простую временную переменную в кэше (например, словарь)
        _admin_waiting_for_user_id[callback.message.chat.id] = True
        await callback.answer()
    elif data == "admin_stats":
        await show_admin_stats(callback)
    elif data.startswith("admin_page_"):
        # Формат: admin_page_<offset>
        offset = int(data.split("_")[2])
        await show_users_page(callback, offset)
    elif data.startswith("admin_toggle_"):
        # Формат: admin_toggle_<user_id>
        uid = int(data.split("_")[2])
        # Получаем текущий статус
        user = await get_user_by_id(uid)
        if user:
            new_status = not user["subscription_active"]
            await update_subscription(uid, new_status)
            await callback.answer(f"Подписка для {uid} изменена: {'активна' if new_status else 'неактивна'}")
            # Обновляем сообщение со списком пользователей, если оно было показано
            # Просто возвращаемся к списку с тем же offset, что был (нужно сохранить offset)
            # Для простоты отправим свежий список с offset=0
            await show_users_page(callback, offset=0)
        else:
            await callback.answer("Пользователь не найден", show_alert=True)
    else:
        await callback.answer("Неизвестная команда")

# Пагинация: показываем пользователей
async def show_users_page(callback: CallbackQuery, offset: int):
    users = await get_all_users(limit=5, offset=offset)
    if not users:
        text = "📭 Пользователи не найдены."
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад в админку", callback_data="admin_back")]
        ])
        await callback.message.edit_text(text, reply_markup=kb)
        return

    text = "👥 *Список пользователей:*\n\n"
    for u in users:
        status = "✅ Активна" if u["subscription_active"] else "❌ Неактивна"
        text += f"🆔 `{u['user_id']}`\n"
        text += f"   Попыток: {u['free_attempts_used']}\n"
        text += f"   Подписка: {status}\n"
        text += f"   Регистрация: {u['created_at']}\n"
        text += "   ➖➖➖➖\n"

    # Кнопки пагинации
    nav_buttons = []
    if offset > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin_page_{offset-5}"))
    # Проверяем, есть ли ещё пользователи (запросили limit+1)
    next_offset = offset + 5
    next_users = await get_all_users(limit=1, offset=next_offset)
    if next_users:
        nav_buttons.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"admin_page_{next_offset}"))
    # Кнопка "Обновить" (просто перезагрузить текущую страницу)
    nav_buttons.append(InlineKeyboardButton(text="🔄 Обновить", callback_data=f"admin_page_{offset}"))

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        nav_buttons,
        [InlineKeyboardButton(text="🏠 В админку", callback_data="admin_back")],
        [InlineKeyboardButton(text="✏️ Переключить подписку", callback_data="admin_switch_instruction")]
    ])
    # Также добавим кнопки для каждого пользователя для быстрого переключения
    # Чтобы не перегружать, можно добавить отдельную кнопку "Переключить" возле каждого пользователя в будущем
    # Сделаем отдельные кнопки для каждого пользователя (inline под каждым пользователем)
    # Для этого перестроим клавиатуру: сначала пользователи, потом пагинация
    user_buttons = []
    for u in users:
        btn_text = f"🔄 Переключить {u['user_id']}"
        user_buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"admin_toggle_{u['user_id']}")])
    if user_buttons:
        keyboard.inline_keyboard = user_buttons + keyboard.inline_keyboard

    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)

async def show_admin_stats(callback: CallbackQuery):
    db = get_db()
    async with db.execute("SELECT COUNT(*) FROM users") as cur:
        total_users = (await cur.fetchone())[0]
    async with db.execute("SELECT COUNT(*) FROM users WHERE subscription_active = 1") as cur:
        active_subs = (await cur.fetchone())[0]
    async with db.execute("SELECT SUM(free_attempts_used) FROM users") as cur:
        total_attempts = (await cur.fetchone())[0] or 0

    text = (
        f"📊 *Статистика бота*\n\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"💳 Активных подписок: {active_subs}\n"
        f"🎙️ Всего использовано попыток: {total_attempts}\n"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]
    ])
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)


@router.message(F.text & ~F.command)
async def handle_admin_find_user(message: Message):
    chat_id = message.chat.id
    if not _admin_waiting_for_user_id.get(chat_id, False):
        return
    # Проверяем админа
    if not is_admin(message.from_user.id):
        return
    # Пытаемся распарсить ID
    try:
        uid = int(message.text.strip())
    except ValueError:
        await message.answer("Некорректный ID. Введите число.")
        return

    user = await get_user_by_id(uid)
    if not user:
        await message.answer(f"❌ Пользователь с ID {uid} не найден.")
    else:
        status = "✅ активна" if user["subscription_active"] else "❌ неактивна"
        text = (
            f"🆔 ID: `{user['user_id']}`\n"
            f"🎫 Попыток: {user['free_attempts_used']}\n"
            f"💳 Подписка: {status}\n"
            f"📅 Регистрация: {user['created_at']}\n"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Переключить подписку", callback_data=f"admin_toggle_{uid}")],
            [InlineKeyboardButton(text="◀️ Назад в админку", callback_data="admin_back")]
        ])
        await message.answer(text, parse_mode="Markdown", reply_markup=kb)
    # Сбрасываем ожидание
    _admin_waiting_for_user_id.pop(chat_id, None)






async def on_startup() -> None:
    await init_db()


async def on_shutdown() -> None:
    await close_db()
