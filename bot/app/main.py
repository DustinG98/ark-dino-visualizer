import asyncio
import logging
import signal
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import discord
from discord import app_commands

from .backend_client import BackendClient
from .cache import Cache
from .bot_commands import register_commands, set_client
from .config import Config, load_config
from .giveaway_scheduler import init_scheduler as init_giveaway_scheduler
from .role_picker_scheduler import init_scheduler as init_role_picker_scheduler


log = logging.getLogger(__name__)


class HealthState:
    def __init__(self) -> None:
        self.disk_ready = False
        self.cache_warm = False


class _HealthHandler(BaseHTTPRequestHandler):
    state: HealthState = HealthState()

    def do_GET(self) -> None:
        if self.path == "/healthz":
            if self.state.disk_ready and self.state.cache_warm:
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"ok")
            else:
                self.send_response(503)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"starting")
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return


def start_healthcheck_server(host: str, port: int, state: HealthState) -> Thread:
    _HealthHandler.state = state
    server = ThreadingHTTPServer((host, port), _HealthHandler)
    thread = Thread(target=server.serve_forever, name="healthcheck", daemon=True)
    thread.start()
    log.info("healthcheck listening on %s:%d", host, port)
    return thread


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("discord").setLevel(level)
    logging.getLogger("httpx").setLevel(logging.WARNING)


async def run_bot(config: Config, health: HealthState) -> None:
    intents = discord.Intents.default()
    intents.members = True
    log.info("discord.py version: %s", discord.__version__)
    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)

    @tree.error
    async def _on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.CheckFailure):
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(str(error) or "You don't have permission to use this command.", ephemeral=True)
                else:
                    await interaction.response.send_message(str(error) or "You don't have permission to use this command.", ephemeral=True)
            except Exception:
                pass
            return
        log.exception("unhandled app command error for %s by %s", interaction.command, interaction.user)
        try:
            if interaction.response.is_done():
                await interaction.followup.send("An unexpected error occurred.", ephemeral=True)
            else:
                await interaction.response.send_message("An unexpected error occurred.", ephemeral=True)
        except Exception:
            pass
    backend = BackendClient(config.backend_url)
    cache = Cache(backend)
    giveaway_scheduler = init_giveaway_scheduler(client, backend)
    role_picker_scheduler = init_role_picker_scheduler(client, backend)

    set_client(backend)

    register_commands(tree, cache)

    @client.event
    async def on_ready() -> None:
        health.disk_ready = True
        log.info("discord ready as %s (id=%s)", client.user, client.user.id if client.user else "?")

        async def warm_up_async() -> None:
            try:
                await cache.warm_up()
                health.cache_warm = True
                log.info("cache warm-up complete")
            except Exception as exc:
                log.error("cache warm-up failed: %s", exc)

        asyncio.create_task(warm_up_async())
        await cache.start_background_refresh()

        try:
            await giveaway_scheduler.start()
        except Exception as exc:
            log.error("giveaway scheduler start failed: %s", exc)

        try:
            await role_picker_scheduler.start()
        except Exception as exc:
            log.error("role picker scheduler start failed: %s", exc)

        if config.guild_id is not None:
            guild = discord.Object(id=config.guild_id)
            try:
                synced = await tree.sync(guild=guild)
                log.info("synced %d commands to guild %s", len(synced), config.guild_id)
            except Exception as exc:
                log.error("guild sync failed: %s", exc)
        else:
            try:
                synced = await tree.sync()
                log.info("synced %d commands globally", len(synced))
            except Exception as exc:
                log.error("global sync failed: %s", exc)

    @client.event
    async def on_resumed() -> None:
        log.info("discord session resumed")

    @client.event
    async def on_member_join(member: discord.Member) -> None:
        if member.guild is None:
            return

        guild_id = member.guild.id

        try:
            settings = await backend.get_welcome_settings(guild_id)
        except Exception as exc:
            log.warning("failed to fetch welcome settings for guild %s: %s", guild_id, exc)
            return

        if settings is None:
            return

        if not settings.get("enabled", False):
            return

        channel = member.guild.get_channel(settings["channel_id"])
        if channel is None:
            log.warning("welcome channel %s not found in guild %s", settings["channel_id"], guild_id)
            return

        message_template = settings["message"]
        message = message_template.replace("{member.mention}", member.mention)
        message = message.replace("{member.name}", member.name)
        message = message.replace("{server.name}", member.guild.name)

        import re
        for match in re.finditer(r"\{channel\.([^}]+)\}", message_template):
            channel_name = match.group(1)
            found = discord.utils.get(member.guild.text_channels, name=channel_name)
            if found:
                message = message.replace(match.group(0), f"<#{found.id}>")
            else:
                message = message.replace(match.group(0), f"#{channel_name}")

        try:
            await channel.send(message)
        except Exception as exc:
            log.warning("failed to send welcome message in guild %s: %s", guild_id, exc)

    stop_event = asyncio.Event()

    def _on_signal() -> None:
        log.info("signal received; shutting down")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig_name in ("SIGINT", "SIGTERM"):
        if hasattr(signal, sig_name):
            try:
                loop.add_signal_handler(getattr(signal, sig_name), _on_signal)
            except NotImplementedError:
                pass

    async def runner() -> None:
        try:
            await client.start(config.discord_bot_token)
        finally:
            await giveaway_scheduler.stop()
            await role_picker_scheduler.stop()
            await cache.stop()
            await backend.close()

    runner_task = asyncio.create_task(runner(), name="discord-runner")

    await stop_event.wait()

    log.info("closing discord client")
    await client.close()
    runner_task.cancel()
    try:
        await runner_task
    except (asyncio.CancelledError, Exception):
        pass


def main() -> None:
    config = load_config()
    configure_logging(config.log_level)
    health = HealthState()
    start_healthcheck_server(config.healthcheck_host, config.healthcheck_port, health)
    try:
        asyncio.run(run_bot(config, health))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()