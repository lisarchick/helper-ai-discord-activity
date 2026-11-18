"""
Helper Voice Cog — core voice AI assistant, minimal command surface.

Only two slash commands remain: /join and /leave. Everything else lives in the
Discord Activity UI (voice selection, subtitles, history, stop button).

Interaction rules (per spec):
- While Helper is speaking (is_speaking = True) ALL new input — voice and text —
  is ignored entirely: nothing enters history or the generation queue.
- The only accepted input during speech is the stop word: said out loud or
  written in chat ("стоп" / "stop"). It instantly stops playback, resets the
  avatar to idle and re-enables listening.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional

import discord
from discord import app_commands
from discord.ext import commands, voice_recv

from config import config
from cogs.admin_logs import AdminLogsCog, admin_only
from services.ai_service import HelperAIService
from services.audio_pipeline import (
    AudioSpeechService,
    VoiceIntentType,
    is_stop_command,
    parse_spoken_phrase,
)
from services.activity_bridge import bridge

logger = logging.getLogger("helper_bot.voice")


@dataclass
class GuildVoiceSession:
    guild_id: int
    channel_id: int
    channel_name: str
    combat_mode_active: bool = False
    active_speaker_id: Optional[int] = None
    combat_timeout_task: Optional[asyncio.Task] = None
    questions_answered: int = 0
    is_speaking: bool = False
    is_thinking: bool = False
    voice_override: Optional[str] = None
    volume_pct: int = 80
    history: list = field(default_factory=list)  # [{role, text, ts}]


class VoiceHelperCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.ai_service = HelperAIService()
        self.audio_service = AudioSpeechService()
        self.sessions: Dict[int, GuildVoiceSession] = {}
        bridge.on_control = self._on_activity_control
        bridge.state["voice"] = config.tts_voice

    # ------------------------------------------------------------- helpers

    def _get_logger_cog(self) -> Optional[AdminLogsCog]:
        cog = self.bot.get_cog("AdminLogsCog")
        return cog if isinstance(cog, AdminLogsCog) else None

    async def _log_event(self, guild, event_title, user=None, voice_channel_name="",
                         spoken_query=None, ai_answer=None, status="INFO",
                         latency_ms=None, extra_note=None) -> None:
        log_cog = self._get_logger_cog()
        if log_cog:
            await log_cog.send_realtime_log(
                guild=guild, event_title=event_title, user=user,
                voice_channel_name=voice_channel_name, spoken_query=spoken_query,
                ai_answer=ai_answer, status=status, latency_ms=latency_ms,
                extra_note=extra_note,
            )

    def _get_session(self, guild: discord.Guild) -> Optional[GuildVoiceSession]:
        return self.sessions.get(guild.id)

    # ---------------------------------------------------- activity controls

    async def _on_activity_control(self, msg: dict) -> None:
        """Handle control messages from the Activity UI."""
        mtype = msg.get("type")
        if mtype == "stop":
            # Stop button in the Activity — same as spoken/written stop word.
            for session in self.sessions.values():
                await self._do_stop(session)
            await bridge.set_status("idle")
            return
        if mtype == "set_voice":
            voice = str(msg.get("value", "")).strip()
            if not voice:
                return
            for session in self.sessions.values():
                session.voice_override = voice
            await bridge.set_voice(voice)
            logger.info("TTS voice switched via Activity UI: %s", voice)
            return
        if mtype == "set_volume":
            try:
                pct = int(msg.get("value", 80))
            except (TypeError, ValueError):
                return
            for session in self.sessions.values():
                session.volume_pct = max(0, min(100, pct))
            logger.info("TTS volume via Activity UI: %d%%", pct)
            return
        if mtype == "clear_memory":
            for gid in list(self.sessions.keys()):
                self.ai_service.clear_history(gid)
                self.sessions[gid].history.clear()
            await bridge.broadcast({"type": "history", "items": []})
            return

    # ------------------------------------------------------------ commands

    @app_commands.command(
        name="join",
        description="Позвать Хелпер в голосовой канал (можно из любого места)",
    )
    @app_commands.describe(
        channel="Голосовой канал (пусто = канал, в котором ты сейчас)"
    )
    @admin_only()
    async def join(
        self,
        interaction: discord.Interaction,
        channel: Optional[discord.VoiceChannel] = None,
    ) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Эту команду нужно использовать внутри сервера.", ephemeral=True
            )
            return

        # Канал из параметра команды; иначе — канал, где сейчас пользователь
        target_channel = channel
        if target_channel is None:
            if interaction.user.voice and interaction.user.voice.channel:
                target_channel = interaction.user.voice.channel
            else:
                await interaction.response.send_message(
                    "Выбери голосовой канал в параметре команды "
                    "или сам зайди в него.", ephemeral=True,
                )
                return

        await interaction.response.defer(ephemeral=True)

        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.is_connected():
            await voice_client.move_to(target_channel)
        else:
            voice_client = await target_channel.connect(cls=voice_recv.VoiceRecvClient)

        session = GuildVoiceSession(
            guild_id=interaction.guild.id,
            channel_id=target_channel.id,
            channel_name=target_channel.name,
        )
        self.sessions[interaction.guild.id] = session
        await bridge.set_status("listening")

        self._attach_voice_listener(interaction.guild, voice_client)

        greeting = "Привет! Я на связи. Скажи Хелпер и задай вопрос."
        await self._speak_answer(interaction.guild, session, greeting, "joy")

        await interaction.followup.send(
            f"Подключилась к **{target_channel.name}**. "
            f"Скажи **«{config.wake_word}»** и вопрос. "
            f"Сказать **«стоп»** — прервать ответ.",
            ephemeral=True,
        )
        await self._log_event(
            guild=interaction.guild,
            event_title="Подключение к голосовому каналу (/join)",
            user=interaction.user,
            voice_channel_name=target_channel.name,
            ai_answer=greeting,
        )

    @app_commands.command(
        name="leave",
        description="Отключить Хелпер от голосового канала",
    )
    @admin_only()
    async def leave(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return

        voice_client = interaction.guild.voice_client
        if not voice_client or not voice_client.is_connected():
            await interaction.response.send_message(
                "Я сейчас не подключена к голосовому каналу.", ephemeral=True
            )
            return

        channel_name = (
            voice_client.channel.name if voice_client.channel else "Unknown"
        )
        session = self.sessions.pop(interaction.guild.id, None)
        if session and session.combat_timeout_task:
            session.combat_timeout_task.cancel()
        if voice_client.is_playing():
            voice_client.stop()

        await voice_client.disconnect(force=True)
        await bridge.set_status("idle")

        await interaction.response.send_message(
            f"Отключилась от **{channel_name}**. Зови через /join, когда понадоблюсь.",
            ephemeral=True,
        )
        await self._log_event(
            guild=interaction.guild,
            event_title="Отключение от голосового (/leave)",
            user=interaction.user,
            voice_channel_name=channel_name,
        )

    # ------------------------------------------------------------ listening

    def _attach_voice_listener(
        self, guild: discord.Guild, voice_client: discord.VoiceClient
    ) -> None:
        if not isinstance(voice_client, voice_recv.VoiceRecvClient):
            return

        loop = asyncio.get_running_loop()

        def on_user_audio(user, data: voice_recv.VoiceData) -> None:
            if not user or user.bot or not data.pcm:
                return
            asyncio.run_coroutine_threadsafe(
                self._process_pcm_chunk(guild, user, data.pcm), loop
            )

        voice_client.listen(voice_recv.BasicSink(on_user_audio))

    async def _process_pcm_chunk(
        self, guild: discord.Guild, member: discord.Member, pcm_bytes: bytes
    ) -> None:
        session = self._get_session(guild)
        if not session:
            return
        # HARD BARRIER: while speaking, only the stop word gets through.
        if session.is_speaking or session.is_thinking:
            transcript = await self.audio_service.transcribe_wav_bytes(pcm_bytes)
            if transcript and is_stop_command(transcript):
                await self._do_stop(session)
            return

        transcript = await self.audio_service.transcribe_wav_bytes(pcm_bytes)
        if transcript:
            await self.handle_transcribed_speech(guild, member, transcript)

    # ------------------------------------------------------------ text chat

    async def _handle_chat_message(self, message: discord.Message) -> None:
        """Text chat: stop word always works; questions accepted when idle."""
        if message.author.bot:
            return
        content = message.content.strip()
        if not content:
            return
        session = self._get_session(message.guild)
        if not session:
            return

        if is_stop_command(content):
            await self._do_stop(session)
            await bridge.set_status("listening")
            return

        # While speaking/thinking: text input is fully ignored (not even queued).
        if session.is_speaking or session.is_thinking:
            return

        # Accept a plain text question only if explicitly addressing the
        # assistant ("helper, ..." at the start) to avoid eating normal chat.
        lowered = content.lower()
        wake = next(
            (w for w in [config.wake_word, *config.wake_aliases] if lowered.startswith(w)),
            None,
        )
        if not wake:
            return
        question = content[len(wake):].strip(" ,:!?")
        if len(question) < 2:
            return

        await self._answer_question(message.guild, session, message.author, question)

    # ------------------------------------------------------------ core logic

    async def _do_stop(self, session: GuildVoiceSession) -> None:
        """Instantly interrupt speech, reset to idle, re-enable listening."""
        session.is_speaking = False
        session.is_thinking = False
        session.combat_mode_active = False
        if session.combat_timeout_task:
            session.combat_timeout_task.cancel()
            session.combat_timeout_task = None

        guild = self.bot.get_guild(session.guild_id)
        voice_client = guild.voice_client if guild else None
        if voice_client and voice_client.is_playing():
            voice_client.stop()

        await bridge.broadcast({"type": "stop"})
        await bridge.broadcast({"type": "emotion", "value": "neutral"})
        await bridge.set_status("stopped")
        logger.info("STOP: playback interrupted, back to idle")

    async def _speak_answer(
        self,
        guild: discord.Guild,
        session: GuildVoiceSession,
        text: str,
        emotion: str,
    ) -> None:
        """Emit answer_start + word timings, play audio, emit answer_end."""
        voice_client = guild.voice_client
        if not voice_client or not voice_client.is_connected():
            return

        session.is_speaking = True
        await bridge.broadcast(
            {"type": "answer_start", "text": text, "emotion": emotion}
        )
        await bridge.set_status("speaking")

        async def _on_word(timings) -> None:
            await bridge.broadcast(
                {
                    "type": "words",
                    "items": [
                        {
                            "offset_ms": w.offset_ms,
                            "duration_ms": w.duration_ms,
                            "word": w.word,
                        }
                        for w in timings
                    ],
                }
            )

        try:
            await self.audio_service.speak_text(
                voice_client,
                text,
                voice_override=session.voice_override,
                volume_pct=session.volume_pct,
                on_word=_on_word,
            )
        finally:
            # If a stop arrived, is_speaking was already reset by _do_stop.
            if session.is_speaking:
                session.is_speaking = False
                await bridge.broadcast({"type": "answer_end"})
                await bridge.broadcast({"type": "emotion", "value": "neutral"})
                await bridge.set_status("listening")

    async def _answer_question(
        self,
        guild: discord.Guild,
        session: GuildVoiceSession,
        speaker,
        question_text: str,
    ) -> None:
        question_text = question_text.strip()
        if len(question_text) < 2:
            await self._speak_answer(guild, session, config.unrecognized_message, "embarrassed")
            return

        session.is_thinking = True
        await bridge.set_status("thinking")
        await bridge.broadcast({"type": "emotion", "value": "thinking"})

        ai_result = await self.ai_service.ask_question(
            guild_id=guild.id,
            user_display_name=speaker.display_name if speaker else "Гость",
            question=question_text,
        )
        session.is_thinking = False
        session.questions_answered += 1

        await bridge.push_history("user", question_text)
        await bridge.push_history("alisa", ai_result.answer)

        await self._log_event(
            guild=guild,
            event_title="Голосовой вопрос отвечен",
            user=speaker if hasattr(speaker, "display_name") else None,
            voice_channel_name=session.channel_name,
            spoken_query=question_text,
            ai_answer=ai_result.answer,
            status="ANSWERED",
            latency_ms=ai_result.latency_ms,
        )

        await self._speak_answer(guild, session, ai_result.answer, ai_result.emotion)

    async def handle_transcribed_speech(
        self, guild: discord.Guild, speaker: discord.Member, transcript: str
    ) -> None:
        session = self._get_session(guild)
        voice_client = guild.voice_client
        if not session or not voice_client or not voice_client.is_connected():
            return

        parsed = parse_spoken_phrase(
            transcript=transcript,
            is_combat_listening=session.combat_mode_active,
        )

        if parsed.intent == VoiceIntentType.IGNORE:
            return

        if parsed.intent == VoiceIntentType.STOP:
            await self._do_stop(session)
            await bridge.set_status("listening")
            return

        if parsed.intent == VoiceIntentType.WAKE_ONLY_NO_QUESTION:
            session.combat_mode_active = True
            session.active_speaker_id = speaker.id
            await bridge.set_status("listening")

            if session.combat_timeout_task:
                session.combat_timeout_task.cancel()

            async def _wait_for_question_timeout() -> None:
                try:
                    await asyncio.sleep(config.listen_timeout_seconds)
                    if session.combat_mode_active:
                        session.combat_mode_active = False
                        await self._speak_answer(
                            guild, session, config.unrecognized_message, "embarrassed"
                        )
                except asyncio.CancelledError:
                    pass

            session.combat_timeout_task = asyncio.create_task(
                _wait_for_question_timeout()
            )
            return

        if parsed.intent in (
            VoiceIntentType.WAKE_WITH_QUESTION,
            VoiceIntentType.DIRECT_QUESTION_IN_ACTIVE_MODE,
        ):
            if session.combat_timeout_task:
                session.combat_timeout_task.cancel()
                session.combat_timeout_task = None
            session.combat_mode_active = False
            await self._answer_question(guild, session, speaker, parsed.extracted_question)

    # ---------------------------------------------------------------- cog IO

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild and not message.author.bot:
            await self._handle_chat_message(message)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VoiceHelperCog(bot))
