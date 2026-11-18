"""
Helper AI — main entry point.
Runs the discord.py bot AND the FastAPI WebSocket bridge (for the Discord
Activity frontend) in a single asyncio event loop.
"""

import asyncio
import logging

import discord
import uvicorn
from discord.ext import commands

from config import config
from services.activity_bridge import bridge

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger("helper_bot")


class HelperBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        intents.members = True
        intents.guilds = True

        super().__init__(command_prefix="!", intents=intents, help_command=None)

    async def setup_hook(self) -> None:
        await self.load_extension("cogs.admin_logs")
        await self.load_extension("cogs.voice_helper")

        if config.guild_id:
            guild_obj = discord.Object(id=config.guild_id)
            self.tree.copy_global_to(guild=guild_obj)
            synced = await self.tree.sync(guild=guild_obj)
            logger.info(
                "Synced %d slash commands to guild %d", len(synced), config.guild_id
            )
        else:
            synced = await self.tree.sync()
            logger.info("Synced %d global slash commands", len(synced))

    async def on_ready(self) -> None:
        if not self.user:
            return
        logger.info("=" * 52)
        logger.info("Helper AI online: %s (ID: %d)", self.user, self.user.id)
        logger.info(
            "Wake: '%s' | Stop words: %s", config.wake_word, sorted(config.stop_words)
        )
        logger.info(
            "Activity bridge: ws://%s:%d/ws", config.bridge_host, config.bridge_port
        )
        logger.info("=" * 52)
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name=f"'{config.wake_word}' в голосе | /join",
            )
        )


async def main() -> None:
    config.validate()
    bot = HelperBot()

    server = uvicorn.Server(
        uvicorn.Config(
            bridge.app,
            host=config.bridge_host,
            port=config.bridge_port,
            log_level="warning",
        )
    )

    async with bot:
        await bot.start(config.discord_token, reconnect=True)


def run() -> None:
    config.validate()
    bot = HelperBot()
    server = uvicorn.Server(
        uvicorn.Config(
            bridge.app,
            host=config.bridge_host,
            port=config.bridge_port,
            log_level="warning",
        )
    )
    try:
        asyncio.run(_run_both(bot, server))
    except KeyboardInterrupt:
        logger.info("Helper AI shut down cleanly.")


async def _run_both(bot: HelperBot, server: uvicorn.Server) -> None:
    api_task = asyncio.create_task(server.serve())
    bot_task = asyncio.create_task(bot.start(config.discord_token))
    done, pending = await asyncio.wait(
        {api_task, bot_task}, return_when=asyncio.FIRST_COMPLETED
    )
    for task in pending:
        task.cancel()
    for task in done:
        exc = task.exception()
        if exc:
            raise exc


if __name__ == "__main__":
    run()
