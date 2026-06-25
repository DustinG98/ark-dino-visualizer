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
from .commands import register_commands, set_client
from .config import Config, load_config


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
    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)
    backend = BackendClient(config.backend_url)
    cache = Cache(backend)

    set_client(backend)

    register_commands(tree, cache)

    @client.event
    async def on_ready() -> None:
        health.disk_ready = True
        log.info("discord ready as %s (id=%s)", client.user, client.user.id if client.user else "?")

        try:
            await cache.warm_up()
            health.cache_warm = True
        except Exception as exc:
            log.error("cache warm-up failed: %s", exc)

        await cache.start_background_refresh()

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