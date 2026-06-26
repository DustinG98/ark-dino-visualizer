import asyncio
import logging
import random
from datetime import datetime, timezone

import discord

from .backend_client import BackendClient, BackendError
from .views.giveaway import make_enter_view, make_cancel_view, enter_custom_id, cancel_custom_id
from .views.giveaway_exchange import ClaimView, ExchangeView, make_claim_view


log = logging.getLogger(__name__)


SWEEP_SECONDS = 60


class GiveawayScheduler:
    def __init__(self, client: discord.Client, backend: BackendClient):
        self._client = client
        self._backend = backend
        self._tasks: dict[str, asyncio.Task] = {}
        self._registered_ids: set[str] = set()
        self._ending_ids: set[str] = set()
        self._sweep_task: asyncio.Task | None = None
        self._stopped = asyncio.Event()

    @property
    def client(self) -> discord.Client:
        return self._client

    @property
    def backend(self) -> BackendClient:
        return self._backend

    def is_registered(self, giveaway_id: str) -> bool:
        return giveaway_id in self._registered_ids

    def register_views(self, giveaway_id: str) -> None:
        if giveaway_id in self._registered_ids:
            return
        try:
            self._client.add_view(make_enter_view(giveaway_id))
            self._client.add_view(make_cancel_view(giveaway_id))
            self._registered_ids.add(giveaway_id)
        except Exception as exc:
            log.warning("failed to register giveaway views for %s: %s", giveaway_id, exc)

    def register_claim_view(
        self,
        giveaway_id: str,
        winner_ids: list[int] | None = None,
        winner_labels: dict[int, str] | None = None,
    ) -> None:
        key = f"claim:{giveaway_id}"
        if key in self._registered_ids:
            return
        winners = winner_ids or []
        try:
            self._client.add_view(make_claim_view(giveaway_id, winners, winner_labels))
            self._registered_ids.add(key)
        except Exception as exc:
            log.warning("failed to register claim view for %s: %s", giveaway_id, exc)

    def schedule_end(self, giveaway_id: str, end_at: datetime) -> None:
        existing = self._tasks.get(giveaway_id)
        if existing is not None and not existing.done():
            return

        async def _runner() -> None:
            try:
                now = datetime.now(timezone.utc)
                delay = (end_at - now).total_seconds()
                if delay > 0:
                    await asyncio.sleep(delay)
                await self._end_giveaway(giveaway_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.exception("giveaway end task crashed for %s: %s", giveaway_id, exc)

        self._tasks[giveaway_id] = asyncio.create_task(_runner(), name=f"giveaway-end-{giveaway_id}")

    def cancel_task(self, giveaway_id: str) -> None:
        task = self._tasks.pop(giveaway_id, None)
        if task is not None and not task.done():
            task.cancel()

    async def on_ready_sweep(self) -> None:
        try:
            giveaways = await self._backend.list_active_giveaways_for_sweep()
        except BackendError as exc:
            log.warning("initial sweep fetch failed: %s", exc)
            return
        except Exception as exc:
            log.warning("initial sweep fetch error: %s", exc)
            return

        now = datetime.now(timezone.utc)
        for g in giveaways:
            gid = g.get("id") or g.get("giveaway_id")
            if not gid:
                continue
            self.register_views(gid)
            end_at = _parse_end_at(g.get("end_at"))
            if end_at is None:
                continue
            if end_at <= now:
                asyncio.create_task(self._end_giveaway(gid))
            else:
                self.schedule_end(gid, end_at)

        try:
            unposted = await self._backend.list_ended_unposted()
        except Exception as exc:
            log.warning("initial unposted fetch failed: %s", exc)
            return
        for g in unposted:
            gid = g.get("id") or g.get("giveaway_id")
            if not gid:
                continue
            winner_ids = [int(x) for x in (g.get("winner_ids") or [])]
            self.register_claim_view(gid, winner_ids)
            asyncio.create_task(self._post_winners_retry(gid, g))

    async def start(self) -> None:
        if self._sweep_task is not None:
            return
        await load_admin_panel_state_from_db(self._client, self._backend)
        await load_public_panel_state_from_db(self._client, self._backend)
        await self.on_ready_sweep()
        await self._register_admin_panel_views()
        await self._register_public_panel_views()
        await self.refresh_admin_panels(full=True)
        await self.refresh_public_panels(full=True)
        self._sweep_task = asyncio.create_task(self._sweep_loop(), name="giveaway-sweep")

    async def _register_admin_panel_views(self) -> None:
        from .views.admin_panel import make_admin_panel_view
        for guild_id in list_known_panel_guilds():
            try:
                self._client.add_view(make_admin_panel_view(guild_id))
            except Exception as exc:
                log.warning("failed to register admin panel view for %s: %s", guild_id, exc)

    async def refresh_admin_panels(self, *, full: bool = False) -> None:
        """Ensure every configured admin panel message still exists. Does not
        re-edit the embed on every sweep — the embed is static. If `full=True`
        (startup), also reattach the View in case the message lost it.
        """
        from .commands.admin.giveaway import _admin_panel_embed
        from .views.admin_panel import ENABLE_BTN_ID, make_admin_panel_view

        for guild_id, (channel_id, message_id) in list(_admin_panel_messages.items()):
            guild = self._client.get_guild(int(guild_id))
            if guild is None:
                continue
            channel = guild.get_channel(int(channel_id))
            if not isinstance(channel, discord.TextChannel):
                continue

            if not message_id:
                recovered = await self._recover_panel_message(channel, guild_id)
                if recovered is not None:
                    await register_and_persist_admin_panel_message(
                        self._backend, guild_id, channel_id, recovered
                    )
                    log.info("admin panel: recovered existing message id %s in channel %s", recovered, channel_id)
                else:
                    try:
                        new_msg = await channel.send(embed=_admin_panel_embed(), view=make_admin_panel_view(guild_id))
                        await register_and_persist_admin_panel_message(
                            self._backend, guild_id, channel_id, new_msg.id
                        )
                        log.info("admin panel: posted fresh in channel %s for guild %s", channel_id, guild_id)
                    except discord.HTTPException as exc:
                        log.warning("admin panel: post failed for guild %s channel %s: %s", guild_id, channel_id, exc)
                continue

            try:
                msg = await channel.fetch_message(int(message_id))
            except discord.NotFound:
                await self._repost_panel(channel, guild_id, channel_id)
                continue
            except discord.HTTPException as exc:
                log.debug("admin panel: fetch failed for guild %s: %s", guild_id, exc)
                continue

            if not full:
                continue

            try:
                await msg.edit(embed=_admin_panel_embed(), view=make_admin_panel_view(guild_id))
            except discord.HTTPException as exc:
                log.warning("admin panel: edit failed (will repost): %s", exc)
                await self._repost_panel(channel, guild_id, channel_id)

    async def _recover_panel_message(self, channel: discord.TextChannel, guild_id: int) -> int | None:
        """Find an existing admin-panel message in the channel by matching button custom_ids.
        Returns the message id, or None if no matching message is found.
        """
        try:
            prefix = f"{ENABLE_BTN_ID}:{guild_id}"
            async for msg in channel.history(limit=25):
                if msg.author.id != self._client.user.id:
                    continue
                for comp in msg.components:
                    for child in comp.children:
                        cid = getattr(child, "custom_id", None)
                        if isinstance(cid, str) and cid.startswith(prefix):
                            return msg.id
        except discord.HTTPException as exc:
            log.warning("admin panel: recovery scan failed: %s", exc)
        return None

    async def _repost_panel(self, channel: discord.TextChannel, guild_id: int, channel_id: int) -> None:
        from .commands.admin.giveaway import _admin_panel_embed
        from .views.admin_panel import make_admin_panel_view
        try:
            new_msg = await channel.send(embed=_admin_panel_embed(), view=make_admin_panel_view(guild_id))
            await register_and_persist_admin_panel_message(self._backend, guild_id, channel_id, new_msg.id)
            log.info("admin panel: reposted in channel %s for guild %s", channel_id, guild_id)
        except discord.HTTPException as exc:
            log.warning("admin panel: repost failed for guild %s channel %s: %s", guild_id, channel_id, exc)

    async def refresh_public_panels(self, *, full: bool = False) -> None:
        """Mirror of refresh_admin_panels for the public panel. Sweep checks
        existence and recovers; only edits on startup (`full=True`).
        """
        from .views.public_giveaway_panel import (
            _public_panel_embed,
            PUBLIC_PANEL_BTN_PREFIX,
            make_public_panel_view,
        )

        for guild_id, (channel_id, message_id) in list(_public_panel_messages.items()):
            guild = self._client.get_guild(int(guild_id))
            if guild is None:
                continue
            channel = guild.get_channel(int(channel_id))
            if not isinstance(channel, discord.TextChannel):
                continue

            if not message_id:
                recovered = await self._recover_public_panel_message(channel)
                if recovered is not None:
                    await register_and_persist_public_panel_message(
                        self._backend, guild_id, channel_id, recovered
                    )
                    log.info("public panel: recovered existing message id %s in channel %s", recovered, channel_id)
                else:
                    try:
                        new_msg = await channel.send(embed=_public_panel_embed(), view=make_public_panel_view())
                        await register_and_persist_public_panel_message(
                            self._backend, guild_id, channel_id, new_msg.id
                        )
                        log.info("public panel: posted fresh in channel %s for guild %s", channel_id, guild_id)
                    except discord.HTTPException as exc:
                        log.warning("public panel: post failed for guild %s channel %s: %s", guild_id, channel_id, exc)
                continue

            try:
                msg = await channel.fetch_message(int(message_id))
            except discord.NotFound:
                await self._repost_public_panel(channel, guild_id, channel_id)
                continue
            except discord.HTTPException as exc:
                log.debug("public panel: fetch failed for guild %s: %s", guild_id, exc)
                continue

            if not full:
                continue

            try:
                await msg.edit(embed=_public_panel_embed(), view=make_public_panel_view())
            except discord.HTTPException as exc:
                log.warning("public panel: edit failed (will repost): %s", exc)
                await self._repost_public_panel(channel, guild_id, channel_id)

    async def _recover_public_panel_message(self, channel: discord.TextChannel) -> int | None:
        """Find an existing public-panel message in the channel by matching button custom_ids."""
        from .views.public_giveaway_panel import PUBLIC_PANEL_BTN_PREFIX

        try:
            async for msg in channel.history(limit=25):
                if msg.author.id != self._client.user.id:
                    continue
                for comp in msg.components:
                    for child in comp.children:
                        cid = getattr(child, "custom_id", None)
                        if isinstance(cid, str) and cid.startswith(PUBLIC_PANEL_BTN_PREFIX):
                            return msg.id
        except discord.HTTPException as exc:
            log.warning("public panel: recovery scan failed: %s", exc)
        return None

    async def _repost_public_panel(self, channel: discord.TextChannel, guild_id: int, channel_id: int) -> None:
        from .views.public_giveaway_panel import _public_panel_embed, make_public_panel_view
        try:
            new_msg = await channel.send(embed=_public_panel_embed(), view=make_public_panel_view())
            await register_and_persist_public_panel_message(self._backend, guild_id, channel_id, new_msg.id)
            log.info("public panel: reposted in channel %s for guild %s", channel_id, guild_id)
        except discord.HTTPException as exc:
            log.warning("public panel: repost failed for guild %s channel %s: %s", guild_id, channel_id, exc)

    async def _register_public_panel_views(self) -> None:
        from .views.public_giveaway_panel import make_public_panel_view
        # Public panel doesn't need a per-guild View (no guild-specific state in buttons),
        # but client.add_view with the same instance works for all guilds.
        try:
            self._client.add_view(make_public_panel_view())
        except Exception as exc:
            log.warning("failed to register public panel view: %s", exc)

    async def stop(self) -> None:
        self._stopped.set()
        if self._sweep_task is not None:
            self._sweep_task.cancel()
            try:
                await self._sweep_task
            except asyncio.CancelledError:
                pass
            self._sweep_task = None
        for task in list(self._tasks.values()):
            task.cancel()
        for task in list(self._tasks.values()):
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks.clear()

    async def _sweep_loop(self) -> None:
        try:
            while not self._stopped.is_set():
                try:
                    await asyncio.wait_for(self._stopped.wait(), timeout=SWEEP_SECONDS)
                    return
                except asyncio.TimeoutError:
                    pass
                await self._sweep_once()
        except asyncio.CancelledError:
            return

    async def _sweep_once(self) -> None:
        try:
            giveaways = await self._backend.list_active_giveaways_for_sweep()
        except Exception as exc:
            log.warning("sweep fetch failed: %s", exc)
            giveaways = []

        now = datetime.now(timezone.utc)
        for g in giveaways:
            gid = g.get("id") or g.get("giveaway_id")
            if not gid:
                continue
            self.register_views(gid)
            end_at = _parse_end_at(g.get("end_at"))
            if end_at is None:
                continue
            if end_at <= now:
                if gid not in self._tasks or self._tasks[gid].done():
                    asyncio.create_task(self._end_giveaway(gid))
            else:
                self.schedule_end(gid, end_at)

        try:
            unposted = await self._backend.list_ended_unposted()
        except Exception as exc:
            log.warning("ended-unposted fetch failed: %s", exc)
            unposted = []
        for g in unposted:
            gid = g.get("id") or g.get("giveaway_id")
            if not gid:
                continue
            if gid in self._ending_ids:
                continue
            winner_ids = [int(x) for x in (g.get("winner_ids") or [])]
            self.register_claim_view(gid, winner_ids)
            asyncio.create_task(self._post_winners_retry(gid, g))

        await self.refresh_admin_panels()
        await self.refresh_public_panels()

    async def _end_giveaway(self, giveaway_id: str) -> None:
        if giveaway_id in self._ending_ids:
            return
        self._ending_ids.add(giveaway_id)
        try:
            try:
                data = await self._backend.get_giveaway(giveaway_id)
            except BackendError as exc:
                log.warning("end: failed to fetch %s: %s", giveaway_id, exc)
                return

            if data is None:
                self._tasks.pop(giveaway_id, None)
                return

            status = data.get("status", "active")
            if status != "active":
                self._tasks.pop(giveaway_id, None)
                return

            winner_count = int(data.get("winner_count") or 1)
            entries: list[int] = [int(e) for e in (data.get("entries") or [])]
            winners = _pick_winners(entries, winner_count)

            try:
                await self._backend.end_giveaway(giveaway_id, winners)
            except BackendError as exc:
                log.warning("end: failed to mark %s ended: %s", giveaway_id, exc)
                return

            await self._post_winners_safe(data, winners)
        finally:
            self._ending_ids.discard(giveaway_id)
            self._tasks.pop(giveaway_id, None)
            self._registered_ids.discard(giveaway_id)

    async def _post_winners_safe(self, data: dict, winners: list[int]) -> None:
        gid = data.get("id") or data.get("giveaway_id")
        labels = await _resolve_winner_labels(self._client, data.get("guild_id"), winners)
        if gid:
            self.register_claim_view(gid, winners, labels)
        try:
            await _post_winners(self._client, data, winners, labels)
        except Exception as exc:
            log.warning("end: failed to post winners for %s: %s", gid, exc)
            return
        if not gid:
            return
        try:
            await self._backend.mark_winners_posted(gid)
        except Exception as exc:
            log.warning("end: failed to mark winners_posted for %s: %s", gid, exc)

    async def _post_winners_retry(self, giveaway_id: str, data: dict) -> None:
        if giveaway_id in self._ending_ids:
            return
        self._ending_ids.add(giveaway_id)
        try:
            raw_winners = data.get("winner_ids")
            if isinstance(raw_winners, str):
                winner_ids = [int(x) for x in raw_winners.split(",") if x]
            elif isinstance(raw_winners, list):
                winner_ids = [int(x) for x in raw_winners if x]
            else:
                winner_ids = []
            if not winner_ids:
                log.warning("retry: giveaway %s has no winner_ids stored", giveaway_id)
                return
            await self._post_winners_safe(data, winner_ids)
        finally:
            self._ending_ids.discard(giveaway_id)


_winners_message_cache: dict[str, int] = {}
_admin_panel_messages: dict[int, tuple[int, int]] = {}
_public_panel_messages: dict[int, tuple[int, int]] = {}


def _store_winners_message_id(giveaway_id: str, winner_ids: list[int], message_id: int) -> None:
    _winners_message_cache[giveaway_id] = message_id


def get_winners_message_id(giveaway_id: str) -> int | None:
    return _winners_message_cache.get(giveaway_id)


def register_admin_panel_message(guild_id: int, channel_id: int, message_id: int) -> None:
    _admin_panel_messages[guild_id] = (int(channel_id), int(message_id))


def get_admin_panel_message(guild_id: int) -> tuple[int, int] | None:
    return _admin_panel_messages.get(guild_id)


def forget_admin_panel_message(guild_id: int) -> None:
    _admin_panel_messages.pop(guild_id, None)


def list_known_panel_guilds() -> list[int]:
    return list(_admin_panel_messages.keys())


async def register_and_persist_admin_panel_message(
    backend: BackendClient, guild_id: int, channel_id: int, message_id: int
) -> None:
    """Update in-memory cache and persist message id to the DB."""
    register_admin_panel_message(guild_id, channel_id, message_id)
    try:
        await backend.update_giveaway_admin_panel_message(guild_id, message_id)
    except Exception as exc:
        log.warning("failed to persist admin panel message id for guild %s: %s", guild_id, exc)


async def load_admin_panel_state_from_db(client: discord.Client, backend: BackendClient) -> None:
    """Populate the in-memory cache from persistent storage on bot start.

    Iterates the bot's currently-visible guilds (cheap — already cached) and fetches
    each guild's persisted settings. Guilds the bot hasn't seen yet (cache warming)
    will be picked up on the first sweep after they connect.
    """
    for guild in client.guilds:
        try:
            settings = await backend.get_giveaway_settings(guild.id)
        except BackendError as exc:
            log.warning("failed to fetch admin panel settings for guild %s: %s", guild.id, exc)
            continue
        except Exception as exc:
            log.warning("unexpected error fetching admin panel settings for guild %s: %s", guild.id, exc)
            continue
        if settings is None:
            continue
        channel_id = settings.get("admin_panel_channel_id")
        message_id = settings.get("admin_panel_message_id")
        if channel_id and message_id:
            _admin_panel_messages[guild.id] = (int(channel_id), int(message_id))
        elif channel_id:
            _admin_panel_messages[guild.id] = (int(channel_id), 0)


def register_public_panel_message(guild_id: int, channel_id: int, message_id: int) -> None:
    _public_panel_messages[guild_id] = (int(channel_id), int(message_id))


def get_public_panel_message(guild_id: int) -> tuple[int, int] | None:
    return _public_panel_messages.get(guild_id)


def forget_public_panel_message(guild_id: int) -> None:
    _public_panel_messages.pop(guild_id, None)


def list_known_public_panel_guilds() -> list[int]:
    return list(_public_panel_messages.keys())


async def register_and_persist_public_panel_message(
    backend: BackendClient, guild_id: int, channel_id: int, message_id: int
) -> None:
    """Update in-memory cache and persist message id to the DB."""
    register_public_panel_message(guild_id, channel_id, message_id)
    try:
        await backend.update_giveaway_public_panel_message(guild_id, message_id)
    except Exception as exc:
        log.warning("failed to persist public panel message id for guild %s: %s", guild_id, exc)


async def load_public_panel_state_from_db(client: discord.Client, backend: BackendClient) -> None:
    """Populate the public panel in-memory cache from persistent storage on bot start."""
    for guild in client.guilds:
        try:
            settings = await backend.get_giveaway_settings(guild.id)
        except BackendError as exc:
            log.warning("failed to fetch public panel settings for guild %s: %s", guild.id, exc)
            continue
        except Exception as exc:
            log.warning("unexpected error fetching public panel settings for guild %s: %s", guild.id, exc)
            continue
        if settings is None:
            continue
        channel_id = settings.get("public_panel_channel_id")
        message_id = settings.get("public_panel_message_id")
        if channel_id and message_id:
            _public_panel_messages[guild.id] = (int(channel_id), int(message_id))
        elif channel_id:
            _public_panel_messages[guild.id] = (int(channel_id), 0)


_scheduler: GiveawayScheduler | None = None


def init_scheduler(client: discord.Client, backend: BackendClient) -> GiveawayScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = GiveawayScheduler(client, backend)
    return _scheduler


def get_scheduler() -> GiveawayScheduler | None:
    return _scheduler


async def cancel_giveaway_now(client: discord.Client, giveaway_id: str, requested_by: int | None = None) -> None:
    backend = _get_backend()
    try:
        data = await backend.get_giveaway(giveaway_id)
    except BackendError as exc:
        log.warning("cancel: failed to fetch %s: %s", giveaway_id, exc)
        raise

    if data is None:
        return

    status = data.get("status", "active")
    if status != "active":
        return

    try:
        await backend.cancel_giveaway(giveaway_id)
    except BackendError as exc:
        log.warning("cancel: backend rejected %s: %s", giveaway_id, exc)
        raise

    sched = get_scheduler()
    if sched is not None:
        sched.cancel_task(giveaway_id)

    channel_id = data.get("channel_id")
    message_id = data.get("message_id")
    guild_id = data.get("guild_id")
    if channel_id and message_id:
        guild = client.get_guild(int(guild_id)) if guild_id else None
        channel = guild.get_channel(int(channel_id)) if guild else None
        if channel is not None:
            try:
                msg = await channel.fetch_message(int(message_id))
                await msg.delete()
            except discord.NotFound:
                pass
            except discord.HTTPException as exc:
                log.warning("cancel: failed to delete message: %s", exc)


def _get_backend() -> BackendClient:
    from .bot_commands import _get_client
    return _get_client()


def _parse_end_at(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            text = str(value).replace("Z", "+00:00")
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _pick_winners(entries: list[int], count: int) -> list[int]:
    if not entries or count <= 0:
        return []
    if count >= len(entries):
        return list(entries)
    return random.sample(entries, count)


async def _resolve_winner_labels(client: discord.Client, guild_id, winner_ids: list[int]) -> dict[int, str]:
    labels: dict[int, str] = {}
    guild = client.get_guild(int(guild_id)) if guild_id else None
    for wid in winner_ids:
        iwid = int(wid)
        name: str | None = None
        if guild is not None:
            member = guild.get_member(iwid)
            if member is not None:
                name = member.display_name
        if not name:
            try:
                user = await client.fetch_user(iwid)
                name = user.name
            except Exception:
                name = None
        labels[iwid] = name or str(iwid)
    return labels


async def _post_winners(client: discord.Client, data: dict, winner_ids: list[int], winner_labels: dict[int, str] | None = None) -> None:
    giveaway_channel_id = data.get("channel_id")
    message_id = data.get("message_id")
    guild_id = data.get("guild_id")
    title = data.get("title", "Giveaway")
    giveaway_id = data.get("id") or data.get("giveaway_id") or ""

    guild = client.get_guild(int(guild_id)) if guild_id else None
    if guild is None:
        log.warning("winners: guild %s not found", guild_id)
        return

    backend = _get_backend()
    master_channel: discord.TextChannel | None = None
    try:
        settings = await backend.get_giveaway_settings(int(guild_id)) if guild_id else None
    except BackendError as exc:
        log.warning("winners: failed to fetch settings: %s", exc)
        settings = None
    cfg_id = settings.get("channel_id") if settings else None
    if cfg_id:
        ch = guild.get_channel(int(cfg_id))
        if isinstance(ch, discord.TextChannel):
            master_channel = ch
    if master_channel is None:
        log.warning("winners: master channel not configured for guild %s", guild_id)
        return

    creator_id = data.get("creator_id")
    embed = discord.Embed(
        title=f"🎉 {title} — Winners!",
        color=discord.Color.gold(),
    )
    if creator_id:
        embed.add_field(name="Host", value=f"<@{creator_id}>", inline=True)
    embed.add_field(name="Entries", value=str(len(data.get("entries") or [])), inline=True)
    if winner_ids:
        mentions = " ".join(f"<@{uid}>" for uid in winner_ids)
        embed.add_field(name="Winners", value=mentions, inline=False)
        embed.add_field(
            name="Claim your prize",
            value="Each winner has their own Claim button below. Click yours to open a private exchange channel with the host.",
            inline=False,
        )
    else:
        embed.add_field(name="Winners", value="_No entries — no winners._", inline=False)

    if winner_ids:
        labels = winner_labels or await _resolve_winner_labels(client, guild_id, winner_ids)
        view = make_claim_view(giveaway_id, winner_ids, labels)
    else:
        view = None

    content = " ".join(f"<@{uid}>" for uid in winner_ids) if winner_ids else None
    try:
        winners_msg = await master_channel.send(content=content, embed=embed, view=view)
        if giveaway_id and winners_msg is not None:
            _store_winners_message_id(giveaway_id, winner_ids, winners_msg.id)
    except discord.HTTPException as exc:
        log.warning("winners: send failed: %s", exc)

    if message_id and giveaway_channel_id:
        try:
            giveaway_channel = guild.get_channel(int(giveaway_channel_id))
            if isinstance(giveaway_channel, discord.TextChannel):
                msg = await giveaway_channel.fetch_message(int(message_id))
                new_embed = discord.Embed(
                    title=f"{title} — Ended",
                    color=discord.Color.greyple(),
                    description=(msg.embeds[0].description if msg.embeds else "") or "",
                )
                for f in (msg.embeds[0].fields if msg.embeds else []):
                    new_embed.add_field(name=f.name, value=f.value, inline=f.inline)
                new_embed.add_field(name="Status", value="Ended", inline=False)
                await msg.edit(embed=new_embed, view=None)
        except discord.NotFound:
            pass
        except discord.HTTPException as exc:
            log.warning("winners: edit original failed: %s", exc)

    if giveaway_channel_id and giveaway_channel_id != master_channel.id:
        try:
            giveaway_channel = guild.get_channel(int(giveaway_channel_id))
            if isinstance(giveaway_channel, discord.TextChannel):
                await giveaway_channel.delete(reason=f"Giveaway {giveaway_id} ended")
                log.info("deleted per-giveaway channel %s for %s", giveaway_channel_id, giveaway_id)
        except discord.NotFound:
            pass
        except discord.HTTPException as exc:
            log.warning("winners: failed to delete per-giveaway channel %s: %s", giveaway_channel_id, exc)
