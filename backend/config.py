"""
Configuration for Alisa AI Discord Activity backend.
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Set
from dotenv import load_dotenv

ENV_FILE_PATH = Path(__file__).resolve().parent / "env" / ".env"
load_dotenv(dotenv_path=ENV_FILE_PATH, override=True)


def _parse_id_set(raw_value: str) -> Set[int]:
    result: set = set()
    for part in raw_value.split(","):
        cleaned = part.strip()
        if cleaned.isdigit():
            result.add(int(cleaned))
    return result


@dataclass(frozen=True)
class BotConfig:
    discord_token: str = field(
        default_factory=lambda: os.getenv("DISCORD_BOT_TOKEN", "").strip()
    )
    guild_id: int = field(
        default_factory=lambda: int(os.getenv("DISCORD_GUILD_ID", "0").strip() or "0")
    )
    admin_role_ids: Set[int] = field(
        default_factory=lambda: _parse_id_set(os.getenv("ADMIN_ROLE_IDS", ""))
    )
    admin_user_ids: Set[int] = field(
        default_factory=lambda: _parse_id_set(os.getenv("ADMIN_USER_IDS", ""))
    )
    default_log_channel_id: int = field(
        default_factory=lambda: int(
            os.getenv("DEFAULT_LOG_CHANNEL_ID", "0").strip() or "0"
        )
    )
    gemini_api_key: str = field(
        default_factory=lambda: os.getenv("GEMINI_API_KEY", "").strip()
    )
    gemini_model: str = field(
        default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
    )
    wake_word: str = field(
        default_factory=lambda: os.getenv("WAKE_WORD", "helper").strip().lower()
    )
    # STT may transliterate "helper" as "хелпер" — accept both
    wake_aliases: Set[str] = field(
        default_factory=lambda: {
            w.strip().lower()
            for w in os.getenv("WAKE_ALIASES", "хелпер").split(",")
            if w.strip()
        }
    )
    # Stop words: spoken or written. Bare "стоп" / "stop" always interrupts speech.
    stop_words: Set[str] = field(
        default_factory=lambda: {
            w.strip().lower()
            for w in os.getenv("STOP_WORDS", "стоп,stop,стоп алиса").split(",")
            if w.strip()
        }
    )
    unrecognized_message: str = field(
        default_factory=lambda: os.getenv(
            "UNRECOGNIZED_MESSAGE",
            "Прости, я не расслышала вопрос. Повтори, пожалуйста.",
        ).strip()
    )
    tts_voice: str = field(
        default_factory=lambda: os.getenv("TTS_VOICE", "ru-RU-SvetlanaNeural").strip()
    )
    tts_rate: str = field(
        default_factory=lambda: os.getenv("TTS_RATE", "+4%").strip()
    )
    tts_volume: str = field(
        default_factory=lambda: os.getenv("TTS_VOLUME", "+0%").strip()
    )
    stt_language: str = field(
        default_factory=lambda: os.getenv("STT_LANGUAGE", "ru-RU").strip()
    )
    listen_timeout_seconds: float = field(
        default_factory=lambda: float(os.getenv("LISTEN_TIMEOUT_SECONDS", "7.0"))
    )
    max_history_turns: int = field(
        default_factory=lambda: int(os.getenv("MAX_HISTORY_TURNS", "12"))
    )
    # FastAPI/WebSocket bridge for the Discord Activity frontend
    bridge_host: str = field(
        default_factory=lambda: os.getenv("BRIDGE_HOST", "127.0.0.1").strip()
    )
    bridge_port: int = field(
        default_factory=lambda: int(os.getenv("BRIDGE_PORT", "8765"))
    )

    def validate(self) -> None:
        if not self.discord_token or self.discord_token.startswith("PASTE_"):
            raise ValueError(
                "DISCORD_BOT_TOKEN is not configured in ./env/.env."
            )
        if not self.gemini_api_key or self.gemini_api_key.startswith("PASTE_"):
            raise ValueError(
                "GEMINI_API_KEY is not configured in ./env/.env."
            )


config = BotConfig()
