from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    CallbackQuery
)
from dotenv import load_dotenv
from openai import OpenAI
import aiohttp, aiosqlite
from os import getenv
import io
import asyncio
from aiogram import Bot


from gtts import gTTS


load_dotenv()
OPENAI_API_KEY = getenv("OPENAI_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)
router = Router()
speaking_topic = ""
promp_for_ecomony = """Generate one IELTS Speaking Part 2 topic. Format exactly:

Title: ...
You should say:
- ...
- ...
- ...
And explain why ...
Do not add extra words."""

REMINDER_DELAY_SECONDS = 1 * 60  # 1 минута

# Хранилище фоновых задач напоминания: chat_id -> Task
_reminder_tasks: dict[int, asyncio.Task] = {}

REMINDER_TEXT = (
    "🎙 Please start recording your answer now!\n\n"
    "You received a topic — now it's time to speak. "
    "Record your answer and send it here as a voice message. We'll give you detailed feedback right away!"
)


async def send_reminder(bot: Bot, chat_id: int, delay: int = REMINDER_DELAY_SECONDS):
    """
    Ждёт delay секунд, затем отправляет напоминание пользователю.
    Запускается как фоновая задача через asyncio.create_task().
    """
    await asyncio.sleep(delay)
    try:
        await bot.send_message(chat_id=chat_id, text=REMINDER_TEXT)
    except Exception as e:
        # Пользователь мог заблокировать бота — просто логируем
        print(f"[Reminder] Failed to send reminder to {chat_id}: {e}")


def get_practice_inlinebutton():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Practice", callback_data="to practice")]
        ]
    )


@router.callback_query(lambda c: c.data == "to practice")
async def to_practice_inlinebtn(callback: CallbackQuery):
    await callback.answer("Here is your topic")


async def get_random_topic_gpt():
    """
    Генерирует тему для IELTS Speaking Part 2
    """

    response = client.chat.completions.create(
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
            {
                "role": "user",
                "content": "Generate one IELTS Speaking Part 2 topic."
            }
        ],
        temperature=0.9
    )
    return response.choices[0].message.content


async def transcribe_audio(file_url: str, language: str = "en") -> str:
    """
    Скачивает аудио в память и отправляет в OpenAI Whisper
    """
    # скачать в память
    async with aiohttp.ClientSession() as session:
        async with session.get(file_url) as resp:
            if resp.status != 200:
                return "Ошибка скачивания аудио"

            audio_bytes = await resp.read()

    # оборачиваем в file-like объект
    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = "audio.ogg"  # важно для определения формата

    # отправка в OpenAI
    transcription = client.audio.transcriptions.create(
        model="whisper-1",
        file=audio_file,
        language="en"  # английский
    )

    return transcription.text


async def speaking_evaluation_gpt(text):
    prompt = """"
        You are an experienced IELTS Speaking examiner. Your task is to provide detailed, constructive feedback on a user's spoken response based on its transcript.

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
   - Are there logical connectors? Is the line of thought easy to follow?
   - Are there long, unjustified pauses (in the text: ellipses, repeated fillers)?
   - Does the speaker use hedging (I guess, sort of) and back-referencing?

2. Lexical Resource
   - Vocabulary range, idioms, collocations.
   - Appropriateness of words (not just "hard" words, but fitting the context).
   - Repetition of basic words (good, bad, nice, do, make)?

3. Grammatical Range & Accuracy
   - Use of different tenses, conditionals, passive, modal verbs.
   - Frequency of errors (word order, prepositions, agreement, articles).
   - Complex structures (subordinate clauses, inversions)?

4. Pronunciation (limited  based on text only)
   - Based on the text: any potential phonetic issues (e.g., "dessert" vs "desert"  stress difference)?
   - Indicators of monotone speech (lack of emotional markers)?
   - If the transcript contains "uh", "um", or repeated sounds  mark them as filler pauses.
   - MUST add: "A full pronunciation assessment requires audio, so this score is approximate."

Response format  strictly as follows:

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
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": prompt
            },
            {
                "role": "user",
                "content": text
            }
        ],
        temperature=0.7
    )
    return response.choices[0].message.content


@router.message(Command("start"))
async def cmd_starts(message: Message):
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


@router.message(Command("practice"))
async def cmd_practice(message: Message, bot: Bot):
    topic = await get_random_topic_gpt()
    text = (
        "Your topic for this practice session is:\n\n"
        f"{topic}\n"
        "---\n"
        "Use /practice to get another topic, if you didn't like this topic."
    )

    await message.answer(text=text, parse_mode="HTML")
    await message.answer(text="You have <b>1 minute</b> to prepare your answer.\nWe'll remind you when your time is up.", parse_mode="HTML")

    # Если уже есть активное напоминание — отменяем старое
    existing = _reminder_tasks.get(message.chat.id)
    if existing and not existing.done():
        existing.cancel()

    # Запускаем напоминание в фоне и сохраняем задачу
    task = asyncio.create_task(send_reminder(bot=bot, chat_id=message.chat.id))
    _reminder_tasks[message.chat.id] = task


@router.message(F.voice)
async def process_audio(message: Message, bot: Bot):
    if message.voice is None:
        await message.answer("Please send a voice message.")
        return
    file_id = message.voice.file_id
    file = await bot.get_file(file_id)
    file_url = f"https://api.telegram.org/file/bot{bot.token}/{file.file_path}"

    # Отменяем напоминание, если пользователь уже прислал голосовое
    task = _reminder_tasks.pop(message.chat.id, None)
    if task and not task.done():
        task.cancel()

    await message.answer("We're processing your submission. This may take up to 2 minutes. Please wait..")
    try:
        await bot.send_chat_action(message.chat.id, "typing")
        audio_to_text = await transcribe_audio(file_url)
        result = await speaking_evaluation_gpt(audio_to_text)
        await message.answer(f"{result}")
    except Exception as e:
        await message.answer(f"Error: {e}")
