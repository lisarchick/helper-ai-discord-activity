"""
AI Service for Helper AI.
Gemini answers in concise spoken Russian, each answer tagged with an emotion
from the 9-expression sprite pack:
neutral, joy, laugh, sad, surprise, angry, thinking, wink, embarrassed.
"""

import re
import time
import logging
from collections import deque
from dataclasses import dataclass
from typing import Dict, Deque, Tuple
from google import genai
from google.genai import types

from config import config

logger = logging.getLogger("helper_bot.ai")

EMOTIONS = (
    "neutral",
    "joy",
    "laugh",
    "sad",
    "surprise",
    "angry",
    "thinking",
    "wink",
    "embarrassed",
)

_TAG_RE = re.compile(r"^\s*\[(\w+)\]\s*", re.IGNORECASE)


@dataclass
class AIResponseResult:
    answer: str
    emotion: str
    latency_ms: int
    model_used: str


DEFAULT_SYSTEM_PROMPT = (
    "Ты — Хелпер, живой русскоязычный голосовой AI-ассистент внутри Discord. "
    "С тобой говорят голосом, ответы озвучиваются синтезом речи.\n"
    "ПРАВИЛА ОТВЕТА:\n"
    "1. Отвечай на русском, естественно и разговорно, 1–3 предложения по умолчанию.\n"
    "2. Никакого markdown, списков и блоков кода — текст читается вслух.\n"
    "3. ОЧЕНЬ ВАЖНО: начинай каждый ответ с эмоции в квадратных скобках, "
    "ровно одна из: [neutral] [joy] [laugh] [sad] [surprise] [angry] "
    "[thinking] [wink] [embarrassed]. Выбирай эмоцию по смыслу и настроению "
    "вопроса. После тега сразу идёт текст ответа. Пример: [joy] Привет! "
    "Рада тебя слышать.\n"
    "4. Будь тёплой, живой, с лёгким характером."
)


def strip_emotion_tag(text: str) -> Tuple[str, str]:
    match = _TAG_RE.match(text)
    if match and match.group(1).lower() in EMOTIONS:
        return text[match.end():].strip(), match.group(1).lower()
    return text.strip(), "neutral"


class HelperAIService:
    def __init__(self) -> None:
        self.client = genai.Client(api_key=config.gemini_api_key)
        self.guild_histories: Dict[int, Deque[Tuple[str, str]]] = {}
        self.guild_personas: Dict[int, str] = {}

    def get_persona(self, guild_id: int) -> str:
        return self.guild_personas.get(guild_id, DEFAULT_SYSTEM_PROMPT)

    def set_persona(self, guild_id: int, persona_prompt: str) -> None:
        self.guild_personas[guild_id] = persona_prompt.strip() or DEFAULT_SYSTEM_PROMPT

    def clear_history(self, guild_id: int) -> int:
        if guild_id in self.guild_histories:
            count = len(self.guild_histories[guild_id])
            self.guild_histories[guild_id].clear()
            return count
        return 0

    async def ask_question(
        self, guild_id: int, user_display_name: str, question: str
    ) -> AIResponseResult:
        start_ts = time.perf_counter()
        history = self.guild_histories.setdefault(
            guild_id, deque(maxlen=config.max_history_turns)
        )

        context_lines = [
            f"{speaker}: {utterance}" for speaker, utterance in history
        ]
        context_lines.append(f"{user_display_name}: {question}")
        full_prompt = "\n".join(context_lines)

        try:
            response = await self.client.aio.models.generate_content(
                model=config.gemini_model,
                contents=full_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=self.get_persona(guild_id),
                    temperature=0.6,
                ),
            )
            answer_text = (response.text or "").strip()
            if not answer_text:
                answer_text = "Я услышала вопрос, но не смогу сейчас ответить. Попробуй ещё раз."
        except Exception as exc:
            logger.exception("Error querying Gemini API: %s", exc)
            answer_text = "Прости, у меня неполадки с доступом к мозгам. Попробуй через минуту."

        clean_answer, emotion = strip_emotion_tag(answer_text)

        history.append((user_display_name, question))
        history.append(("Хелпер", clean_answer))

        elapsed_ms = int((time.perf_counter() - start_ts) * 1000)
        return AIResponseResult(
            answer=clean_answer,
            emotion=emotion,
            latency_ms=elapsed_ms,
            model_used=config.gemini_model,
        )
