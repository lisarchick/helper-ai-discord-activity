"""
Логирование в реальном времени (/log_helper) и проверки прав.
Админ сервера один раз пишет /log_helper в текстовом канале — и туда
стримятся все голосовые вопросы, ответы ИИ, срабатывания wake-слова,
остановки и ошибки.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import discord
from discord import app_commands
from discord.ext import commands

from config import config

STATE_FILE = Path(__file__).resolve().parent.parent / "env" / "log_channels.json"


def is_user_admin(interaction: discord.Interaction) -> bool:
    if interaction.user.id in config.admin_user_ids:
        return True

    if isinstance(interaction.user, discord.Member):
        if interaction.user.guild_permissions.administrator:
            return True
        user_role_ids = {role.id for role in interaction.user.roles}
        if user_role_ids.intersection(config.admin_role_ids):
            return True

    return False


def admin_only():
    async def predicate(interaction: discord.Interaction) -> bool:
        if not is_user_admin(interaction):
            await interaction.response.send_message(
                "Доступ запрещён. Команды Алисы доступны только администраторам сервера.",
                ephemeral=True,
            )
            return False
        return True

    return app_commands.check(predicate)


class AdminLogsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.guild_log_channels: Dict[int, int] = self._load_log_channels()

    def _load_log_channels(self) -> Dict[int, int]:
        mapping: Dict[int, int] = {}
        if config.guild_id and config.default_log_channel_id:
            mapping[config.guild_id] = config.default_log_channel_id

        if STATE_FILE.exists():
            try:
                raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                for k, v in raw.items():
                    mapping[int(k)] = int(v)
            except Exception:
                pass
        return mapping

    def _save_log_channels(self) -> None:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(
            json.dumps({str(k): v for k, v in self.guild_log_channels.items()}, indent=2),
            encoding="utf-8",
        )

    @app_commands.command(
        name="log_helper",
        description="[Только админ] Включить логи Алисы в реальном времени в этом канале.",
    )
    @admin_only()
    async def log_helper(self, interaction: discord.Interaction) -> None:
        if not interaction.guild_id or not interaction.channel_id:
            await interaction.response.send_message(
                "Эту команду нужно использовать в текстовом канале на сервере.",
                ephemeral=True,
            )
            return

        self.guild_log_channels[interaction.guild_id] = interaction.channel_id
        self._save_log_channels()

        stop_words = " / ".join(sorted(config.stop_words))
        embed = discord.Embed(
            title="Логи Алисы подключены",
            description=(
                f"Этот канал (<#{interaction.channel_id}>) теперь привязан как постоянный "
                "**журнал голосового ИИ Алисы**.\n\n"
                "Здесь в реальном времени будут появляться все голосовые вопросы, "
                "ответы ИИ, задержки и административные действия."
            ),
            color=discord.Color.from_rgb(16, 185, 129),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Wake-слово", value=f"`{config.wake_word}`", inline=True)
        embed.add_field(name="Стоп-слова", value=f"`{stop_words}`", inline=True)
        embed.add_field(name="Админ", value=interaction.user.mention, inline=True)
        await interaction.response.send_message(embed=embed)

    async def send_realtime_log(
        self,
        guild: discord.Guild,
        event_title: str,
        user: Optional[discord.abc.User],
        voice_channel_name: str,
        spoken_query: Optional[str] = None,
        ai_answer: Optional[str] = None,
        status: str = "INFO",
        latency_ms: Optional[int] = None,
        extra_note: Optional[str] = None,
    ) -> None:
        channel_id = self.guild_log_channels.get(guild.id)
        if not channel_id:
            return

        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        color_map = {
            "ANSWERED": discord.Color.from_rgb(16, 185, 129),
            "COMBAT_MODE": discord.Color.from_rgb(99, 102, 241),
            "STOPPED": discord.Color.from_rgb(245, 158, 11),
            "UNRECOGNIZED": discord.Color.from_rgb(239, 68, 68),
            "INFO": discord.Color.from_rgb(59, 130, 246),
        }

        embed = discord.Embed(
            title=f"Хелпер · {event_title}",
            color=color_map.get(status, discord.Color.blurple()),
            timestamp=datetime.now(timezone.utc),
        )

        if user:
            embed.add_field(name="Спикер / Админ", value=f"{user.mention} (`{user.id}`)", inline=True)
        embed.add_field(name="Голосовой канал", value=f"`{voice_channel_name}`", inline=True)
        if latency_ms is not None:
            embed.add_field(name="Задержка ИИ", value=f"`{latency_ms} мс`", inline=True)

        if spoken_query:
            embed.add_field(name="Распознанный вопрос (STT)", value=f"```text\n{spoken_query}\n```", inline=False)
        if ai_answer:
            embed.add_field(name="Ответ Алисы (TTS)", value=f"```text\n{ai_answer}\n```", inline=False)
        if extra_note:
            embed.add_field(name="Подробности", value=extra_note, inline=False)

        embed.set_footer(text=f"Модель: {config.gemini_model} · Голос: {config.tts_voice}")

        try:
            await channel.send(embed=embed)
        except discord.DiscordException:
            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminLogsCog(bot))
