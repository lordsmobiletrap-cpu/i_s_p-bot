"""
OpenAI service — GPT topic generation, Whisper transcription, IELTS evaluation.

Encapsulates all OpenAI API calls in a single class.
"""

from __future__ import annotations

import io
import logging

import aiohttp
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

TOPIC_GENERATION_PROMPT = (
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

EVALUATION_PROMPT = """You are an experienced IELTS Speaking examiner. Your task is to provide detailed, constructive feedback on a user's spoken response based on its transcript.

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


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class OpenAIService:
    """Handles all OpenAI interactions for the bot.

    Usage::

        openai = OpenAIService(api_key="sk-...")
        topic = await openai.generate_topic()
        transcript = await openai.transcribe_audio(file_url)
        feedback = await openai.evaluate_speaking(transcript)
    """

    def __init__(self, api_key: str) -> None:
        if not api_key:
            logger.warning("OpenAIService initialized with empty API key")
        self._client = AsyncOpenAI(api_key=api_key)

    async def generate_topic(self) -> str:
        """Generate an IELTS Speaking Part 2 topic via GPT-4o-mini."""
        response = await self._client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": TOPIC_GENERATION_PROMPT},
                {"role": "user", "content": "Generate one IELTS Speaking Part 2 topic."},
            ],
            temperature=0.9,
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("GPT returned an empty topic.")
        return content

    async def transcribe_audio(self, file_url: str) -> str:
        """Download audio from ``file_url`` and transcribe with Whisper.

        Args:
            file_url: Direct download URL for the audio file.

        Returns:
            Transcribed text.
        """
        async with aiohttp.ClientSession() as session:
            async with session.get(file_url) as resp:
                if resp.status != 200:
                    raise RuntimeError(
                        f"Failed to download audio: HTTP {resp.status}"
                    )
                audio_bytes = await resp.read()

        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = "audio.ogg"
        transcription = await self._client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language="en",
        )
        return transcription.text

    async def evaluate_speaking(self, text: str) -> str:
        """Evaluate a spoken transcript against IELTS criteria.

        Args:
            text: The transcribed user speech.

        Returns:
            Formatted feedback string.
        """
        response = await self._client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": EVALUATION_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0.2,
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("GPT returned an empty evaluation.")
        return content
