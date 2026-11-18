"""
Audio Pipeline for Helper AI.
- Russian wake/stop phrase parsing (bare "стоп"/"stop" interrupts speech).
- STT via SpeechRecognition (ru-RU).
- TTS via edge-tts STREAMING: collects mp3 audio + WordBoundary timings,
  then plays through Discord voice while emitting word timings to the
  Activity bridge for lipsync.
"""

import asyncio
import io
import os
import re
import tempfile
import logging
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

import discord
import edge_tts
import speech_recognition as sr

from config import config

logger = logging.getLogger("helper_bot.audio")


class VoiceIntentType(Enum):
    IGNORE = "ignore"
    STOP = "stop"
    WAKE_ONLY_NO_QUESTION = "wake_only_no_question"
    WAKE_WITH_QUESTION = "wake_with_question"
    DIRECT_QUESTION_IN_ACTIVE_MODE = "direct_question_in_active_mode"


@dataclass
class ParsedVoiceIntent:
    intent: VoiceIntentType
    raw_transcript: str
    extracted_question: str = ""


@dataclass
class WordTiming:
    offset_ms: int
    duration_ms: int
    word: str


def _normalize(text: str) -> str:
    normalized = re.sub(r"[^\w\s]", " ", text.lower(), flags=re.UNICODE)
    return re.sub(r"\s+", " ", normalized).strip()


_WAKE_WORDS = None


def _wake_words() -> list:
    global _WAKE_WORDS
    if _WAKE_WORDS is None:
        _WAKE_WORDS = [config.wake_word] + [
            w for w in config.wake_aliases if w and w != config.wake_word
        ]
    return _WAKE_WORDS


def is_stop_command(text: str) -> bool:
    """A stop command is the bare stop word (optionally with the wake word)."""
    normalized = _normalize(text)
    if not normalized:
        return False
    words = normalized.split()
    # strip leading wake word: "helper стоп" == "стоп"
    if words and words[0] in _wake_words():
        words = words[1:]
    if len(words) == 0:
        return False
    return words[0] in config.stop_words and len(words) <= 2


def parse_spoken_phrase(
    transcript: str,
    is_combat_listening: bool = False,
) -> ParsedVoiceIntent:
    cleaned = transcript.strip()
    if not cleaned:
        return ParsedVoiceIntent(intent=VoiceIntentType.IGNORE, raw_transcript="")

    if is_stop_command(cleaned):
        return ParsedVoiceIntent(intent=VoiceIntentType.STOP, raw_transcript=cleaned)

    match = None
    for ww in _wake_words():
        wake_pattern = re.compile(rf"\b{re.escape(ww)}\b[,:\-\s]*(.*)", re.IGNORECASE)
        match = wake_pattern.search(cleaned)
        if match:
            break

    if match:
        remainder = match.group(1).strip(" .,?!;:-")
        if not remainder:
            return ParsedVoiceIntent(
                intent=VoiceIntentType.WAKE_ONLY_NO_QUESTION,
                raw_transcript=cleaned,
            )
        return ParsedVoiceIntent(
            intent=VoiceIntentType.WAKE_WITH_QUESTION,
            raw_transcript=cleaned,
            extracted_question=remainder,
        )

    if is_combat_listening:
        return ParsedVoiceIntent(
            intent=VoiceIntentType.DIRECT_QUESTION_IN_ACTIVE_MODE,
            raw_transcript=cleaned,
            extracted_question=cleaned,
        )

    return ParsedVoiceIntent(intent=VoiceIntentType.IGNORE, raw_transcript=cleaned)


class AudioSpeechService:
    def __init__(self) -> None:
        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold = 300
        self.recognizer.dynamic_energy_threshold = True

    async def transcribe_wav_bytes(self, wav_bytes: bytes) -> str:
        def _sync_recognize() -> str:
            with sr.AudioFile(io.BytesIO(wav_bytes)) as source:
                audio_data = self.recognizer.record(source)
            try:
                return self.recognizer.recognize_google(
                    audio_data, language=config.stt_language
                )
            except sr.UnknownValueError:
                return ""
            except sr.RequestError as exc:
                logger.error("STT service error: %s", exc)
                return ""

        return await asyncio.to_thread(_sync_recognize)

    async def synthesize_with_timings(
        self,
        text: str,
        voice_override: Optional[str] = None,
        volume_pct: Optional[int] = None,
    ) -> "tuple[bytes, List[WordTiming]]":
        """Stream edge-tts, return (mp3_bytes, word_timings)."""
        tts_voice = voice_override or config.tts_voice
        # volume_pct: 0..100 slider from the Activity UI -> edge-tts gain
        volume = config.tts_volume
        if volume_pct is not None:
            volume = f"{max(-100, min(100, int(volume_pct) - 80))}%"
        communicate = edge_tts.Communicate(
            text=text,
            voice=tts_voice,
            rate=config.tts_rate,
            volume=volume,
            boundary="WordBoundary",
        )
        audio_chunks: List[bytes] = []
        timings: List[WordTiming] = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_chunks.append(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                timings.append(
                    WordTiming(
                        offset_ms=int(chunk["offset"] / 10_000),  # 100ns -> ms
                        duration_ms=int(chunk["duration"] / 10_000),
                        word=chunk["text"],
                    )
                )
        return b"".join(audio_chunks), timings

    async def speak_text(
        self,
        voice_client: discord.VoiceClient,
        text: str,
        voice_override: Optional[str] = None,
        volume_pct: Optional[int] = None,
        on_word=None,
    ) -> None:
        """Synthesize and play; calls on_word(timings) once before playback starts."""
        if not voice_client or not voice_client.is_connected():
            return

        if voice_client.is_playing():
            voice_client.stop()

        mp3_bytes, timings = await self.synthesize_with_timings(
            text, voice_override, volume_pct
        )
        if not mp3_bytes:
            logger.warning("TTS produced no audio for: %s", text[:80])
            return

        if on_word is not None:
            try:
                await on_word(timings)
            except Exception:
                logger.exception("on_word callback failed")

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_file:
            tmp_file.write(mp3_bytes)
            tmp_path = tmp_file.name

        try:
            play_finished = asyncio.Event()
            loop = asyncio.get_running_loop()

            def _after_playback(error: Optional[Exception]) -> None:
                if error:
                    logger.error("Voice playback error: %s", error)
                loop.call_soon_threadsafe(play_finished.set)

            audio_source = discord.FFmpegPCMAudio(
                tmp_path,
                options="-loglevel warning",
            )
            voice_client.play(audio_source, after=_after_playback)
            await play_finished.wait()
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
