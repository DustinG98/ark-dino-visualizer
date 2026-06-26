import asyncio
import logging

import discord


log = logging.getLogger(__name__)


SWEEP_SECONDS = 60


_admin_panel_messages: dict[int, tuple[int, int]] = {}
_public_panel_messages: dict[int, tuple[int, int]] = {}


def register_admin_panel_message(guild_id: int, channel_id: int, message_id: int) -> None:
    _admin_panel_messages[guild_id] = (int(channel_id), int(message_id))


def get_admin_panel_message(guild_id: int) -> tuple[int, int] | None:
    return _admin_panel_messages.get(guild_id)


def forget_admin_panel_message(guild_id: int) -> None:
    _admin_panel_messages.pop(guild_id, None)


def list_known_admin_panel_guilds() -> list[int]:
    return list(_admin_panel_messages.keys())


async def register_and_persist_admin_panel_message(
    backend, guild_id: int, channel_id: int, message_id: int
) -> None:
    register_admin_panel_message(guild_id, channel_id, message_id)
    try:
        await backend.update_role_picker_admin_panel_message(guild_id, message_id)
    except Exception as exc:
        log.warning("failed to persist role picker admin panel message id for guild %s: %s", guild_id, exc)


def register_public_panel_message(guild_id: int, channel_id: int, message_id: int) -> None:
    _public_panel_messages[guild_id] = (int(channel_id), int(message_id))


def get_public_panel_message(guild_id: int) -> tuple[int, int] | None:
    return _public_panel_messages.get(guild_id)


def forget_public_panel_message(guild_id: int) -> None:
    _public_panel_messages.pop(guild_id, None)


def list_known_public_panel_guilds() -> list[int]:
    return list(_public_panel_messages.keys())


async def register_and_persist_public_panel_message(
    backend, guild_id: int, channel_id: int, message_id: int
) -> None:
    register_public_panel_message(guild_id, channel_id, message_id)
    try:
        await backend.update_role_picker_public_panel_message(guild_id, message_id)
    except Exception as exc:
        log.warning("failed to persist role picker public panel message id for guild %s: %s", guild_id, exc)


async def load_state_from_db(client: discord.Client, backend) -> None:
    for guild in client.guilds:
        try:
            settings = await backend.get_role_picker_settings(guild.id)
        except Exception as exc:
            log.warning("failed to fetch role picker settings for guild %s: %s", guild.id, exc)
            continue
        if settings is None:
            continue
        admin_channel = settings.get("admin_panel_channel_id")
        admin_message = settings.get("admin_panel_message_id")
        if admin_channel and admin_message:
            _admin_panel_messages[guild.id] = (int(admin_channel), int(admin_message))
        elif admin_channel:
            _admin_panel_messages[guild.id] = (int(admin_channel), 0)
        public_channel = settings.get("public_panel_channel_id")
        public_message = settings.get("public_panel_message_id")
        if public_channel and public_message:
            _public_panel_messages[guild.id] = (int(public_channel), int(public_message))
        elif public_channel:
            _public_panel_messages[guild.id] = (int(public_channel), 0)


class RolePickerScheduler:
    def __init__(self, client: discord.Client, backend):
        self._client = client
        self._backend = backend
        self._sweep_task: asyncio.Task | None = None
        self._stopped = asyncio.Event()

    @property
    def client(self) -> discord.Client:
        return self._client

    async def start(self) -> None:
        await load_state_from_db(self._client, self._backend)
        await self._register_views()
        await self.refresh_panels(full=True)
        self._sweep_task = asyncio.create_task(self._sweep_loop(), name="role-picker-sweep")

    async def _register_views(self) -> None:
        from .views.role_picker_admin import make_admin_view
        from .views.role_picker_public import make_public_view
        for guild_id in list_known_admin_panel_guilds():
            try:
                self._client.add_view(make_admin_view(guild_id))
            except Exception as exc:
                log.warning("failed to register admin panel view for %s: %s", guild_id, exc)
        for guild_id in list_known_public_panel_guilds():
            try:
                roles = await self._backend.get_role_picker_roles(guild_id)
                self._client.add_view(make_public_view(guild_id, roles))
            except Exception as exc:
                log.warning("failed to register public panel view for %s: %s", guild_id, exc)

    async def refresh_panels(self, *, full: bool = False) -> None:
        await self._refresh_admin_panels(full=full)
        await self._refresh_public_panels(full=full)

    async def refresh_admin_panel_for_guild(self, guild_id: int) -> None:
        from .commands.admin.role_picker import post_admin_panel
        from .views.role_picker_admin import _build_admin_embed, make_admin_view

        entry = _admin_panel_messages.get(guild_id)
        if entry is None:
            return
        channel_id, message_id = entry
        guild = self._client.get_guild(int(guild_id))
        if guild is None:
            return
        channel = guild.get_channel(int(channel_id))
        if not isinstance(channel, discord.TextChannel):
            return

        settings = None
        try:
            settings = await self._backend.get_role_picker_settings(guild_id)
        except Exception as exc:
            log.debug("admin panel: settings fetch failed for guild %s: %s", guild_id, exc)
        roles = settings.get("roles", []) if settings else []
        public_channel_id = settings.get("public_panel_channel_id") if settings else None

        if message_id:
            try:
                msg = await channel.fetch_message(int(message_id))
                await msg.edit(embed=_build_admin_embed(guild_id, roles, public_channel_id), view=make_admin_view(guild_id))
                self._client.add_view(make_admin_view(guild_id))
                return
            except discord.NotFound:
                pass
            except discord.HTTPException as exc:
                log.debug("admin panel edit failed for guild %s: %s", guild_id, exc)

        try:
            new_msg = await channel.send(embed=_build_admin_embed(guild_id, roles, public_channel_id), view=make_admin_view(guild_id))
            await register_and_persist_admin_panel_message(self._backend, guild_id, channel_id, new_msg.id)
            log.info("role picker admin panel: reposted in channel %s for guild %s", channel_id, guild_id)
        except discord.HTTPException as exc:
            log.warning("role picker admin panel: post failed for guild %s channel %s: %s", guild_id, channel_id, exc)

    async def refresh_public_panel_for_guild(self, guild_id: int) -> None:
        from .commands.admin.role_picker import post_public_panel
        from .views.role_picker_public import _build_public_embed, make_public_view

        entry = _public_panel_messages.get(guild_id)
        if entry is None:
            return
        channel_id, message_id = entry
        guild = self._client.get_guild(int(guild_id))
        if guild is None:
            return
        channel = guild.get_channel(int(channel_id))
        if not isinstance(channel, discord.TextChannel):
            return

        roles = await self._backend.get_role_picker_roles(guild_id)
        if message_id:
            try:
                msg = await channel.fetch_message(int(message_id))
                await msg.edit(embed=_build_public_embed(roles), view=make_public_view(guild_id, roles))
                self._client.add_view(make_public_view(guild_id, roles))
                return
            except discord.NotFound:
                pass
            except discord.HTTPException as exc:
                log.debug("public panel edit failed for guild %s: %s", guild_id, exc)

        try:
            new_msg = await channel.send(embed=_build_public_embed(roles), view=make_public_view(guild_id, roles))
            await register_and_persist_public_panel_message(self._backend, guild_id, channel_id, new_msg.id)
            log.info("role picker public panel: reposted in channel %s for guild %s", channel_id, guild_id)
        except discord.HTTPException as exc:
            log.warning("role picker public panel: post failed for guild %s channel %s: %s", guild_id, channel_id, exc)

    async def _refresh_admin_panels(self, *, full: bool = False) -> None:
        from .commands.admin.role_picker import post_admin_panel
        from .views.role_picker_admin import _build_admin_embed, make_admin_view

        for guild_id, (channel_id, message_id) in list(_admin_panel_messages.items()):
            guild = self._client.get_guild(int(guild_id))
            if guild is None:
                continue
            channel = guild.get_channel(int(channel_id))
            if not isinstance(channel, discord.TextChannel):
                continue

            settings = None
            try:
                settings = await self._backend.get_role_picker_settings(guild_id)
            except Exception as exc:
                log.debug("admin panel: settings fetch failed for guild %s: %s", guild_id, exc)
            roles = settings.get("roles", []) if settings else []
            public_channel_id = settings.get("public_panel_channel_id") if settings else None

            if not message_id:
                recovered = await self._recover_admin_panel_message(channel, guild_id)
                if recovered is not None:
                    await register_and_persist_admin_panel_message(self._backend, guild_id, channel_id, recovered)
                    log.info("role picker admin panel: recovered message id %s in channel %s", recovered, channel_id)
                else:
                    try:
                        new_msg = await channel.send(
                            embed=_build_admin_embed(guild_id, roles, public_channel_id),
                            view=make_admin_view(guild_id),
                        )
                        await register_and_persist_admin_panel_message(self._backend, guild_id, channel_id, new_msg.id)
                        log.info("role picker admin panel: posted fresh in channel %s for guild %s", channel_id, guild_id)
                    except discord.HTTPException as exc:
                        log.warning("role picker admin panel: post failed for guild %s channel %s: %s", guild_id, channel_id, exc)
                continue

            try:
                msg = await channel.fetch_message(int(message_id))
            except discord.NotFound:
                await self._repost_admin_panel(channel, guild_id, channel_id, roles, public_channel_id)
                continue
            except discord.HTTPException as exc:
                log.debug("role picker admin panel: fetch failed for guild %s: %s", guild_id, exc)
                continue

            if not full:
                continue

            try:
                await msg.edit(
                    embed=_build_admin_embed(guild_id, roles, public_channel_id),
                    view=make_admin_view(guild_id),
                )
            except discord.HTTPException as exc:
                log.warning("role picker admin panel: edit failed (will repost): %s", exc)
                await self._repost_admin_panel(channel, guild_id, channel_id, roles, public_channel_id)

    async def _refresh_public_panels(self, *, full: bool = False) -> None:
        from .views.role_picker_public import _build_public_embed, make_public_view

        for guild_id, (channel_id, message_id) in list(_public_panel_messages.items()):
            guild = self._client.get_guild(int(guild_id))
            if guild is None:
                continue
            channel = guild.get_channel(int(channel_id))
            if not isinstance(channel, discord.TextChannel):
                continue

            roles = []
            try:
                roles = await self._backend.get_role_picker_roles(guild_id)
            except Exception as exc:
                log.debug("role picker public panel: roles fetch failed for guild %s: %s", guild_id, exc)

            if not message_id:
                recovered = await self._recover_public_panel_message(channel)
                if recovered is not None:
                    await register_and_persist_public_panel_message(self._backend, guild_id, channel_id, recovered)
                    log.info("role picker public panel: recovered message id %s in channel %s", recovered, channel_id)
                else:
                    try:
                        new_msg = await channel.send(
                            embed=_build_public_embed(roles),
                            view=make_public_view(guild_id, roles),
                        )
                        await register_and_persist_public_panel_message(self._backend, guild_id, channel_id, new_msg.id)
                        log.info("role picker public panel: posted fresh in channel %s for guild %s", channel_id, guild_id)
                    except discord.HTTPException as exc:
                        log.warning("role picker public panel: post failed for guild %s channel %s: %s", guild_id, channel_id, exc)
                continue

            try:
                msg = await channel.fetch_message(int(message_id))
            except discord.NotFound:
                await self._repost_public_panel(channel, guild_id, channel_id, roles)
                continue
            except discord.HTTPException as exc:
                log.debug("role picker public panel: fetch failed for guild %s: %s", guild_id, exc)
                continue

            if not full:
                continue

            try:
                await msg.edit(
                    embed=_build_public_embed(roles),
                    view=make_public_view(guild_id, roles),
                )
            except discord.HTTPException as exc:
                log.warning("role picker public panel: edit failed (will repost): %s", exc)
                await self._repost_public_panel(channel, guild_id, channel_id, roles)

    async def _recover_admin_panel_message(self, channel: discord.TextChannel, guild_id: int) -> int | None:
        from .views.role_picker_admin import make_admin_view
        prefix = f"rp_admin:set_public_channel:{guild_id}"
        try:
            async for msg in channel.history(limit=25):
                if msg.author.id != self._client.user.id:
                    continue
                for comp in msg.components:
                    for child in comp.children:
                        cid = getattr(child, "custom_id", None)
                        if isinstance(cid, str) and cid.startswith(prefix):
                            return msg.id
        except discord.HTTPException as exc:
            log.warning("role picker admin panel: recovery scan failed: %s", exc)
        return None

    async def _repost_admin_panel(
        self, channel: discord.TextChannel, guild_id: int, channel_id: int, roles: list[dict], public_channel_id: int | None
    ) -> None:
        from .commands.admin.role_picker import post_admin_panel
        try:
            new_msg = await post_admin_panel(self._client, channel.guild, channel_id)
            if new_msg is not None:
                await register_and_persist_admin_panel_message(self._backend, guild_id, channel_id, new_msg)
                log.info("role picker admin panel: reposted in channel %s for guild %s", channel_id, guild_id)
        except discord.HTTPException as exc:
            log.warning("role picker admin panel: repost failed for guild %s channel %s: %s", guild_id, channel_id, exc)

    async def _recover_public_panel_message(self, channel: discord.TextChannel) -> int | None:
        from .views.role_picker_public import TOGGLE_PREFIX
        try:
            async for msg in channel.history(limit=25):
                if msg.author.id != self._client.user.id:
                    continue
                for comp in msg.components:
                    for child in comp.children:
                        cid = getattr(child, "custom_id", None)
                        if isinstance(cid, str) and cid.startswith(TOGGLE_PREFIX):
                            return msg.id
        except discord.HTTPException as exc:
            log.warning("role picker public panel: recovery scan failed: %s", exc)
        return None

    async def _repost_public_panel(self, channel: discord.TextChannel, guild_id: int, channel_id: int, roles: list[dict]) -> None:
        from .commands.admin.role_picker import post_public_panel
        try:
            new_msg = await post_public_panel(self._client, channel.guild, channel_id)
            if new_msg is not None:
                await register_and_persist_public_panel_message(self._backend, guild_id, channel_id, new_msg)
                log.info("role picker public panel: reposted in channel %s for guild %s", channel_id, guild_id)
        except discord.HTTPException as exc:
            log.warning("role picker public panel: repost failed for guild %s channel %s: %s", guild_id, channel_id, exc)

    async def stop(self) -> None:
        self._stopped.set()
        if self._sweep_task is not None:
            self._sweep_task.cancel()
            try:
                await self._sweep_task
            except asyncio.CancelledError:
                pass
            self._sweep_task = None

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
        await self._register_views()
        await self.refresh_panels()


_scheduler: RolePickerScheduler | None = None


def init_scheduler(client: discord.Client, backend) -> RolePickerScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = RolePickerScheduler(client, backend)
    return _scheduler


def get_scheduler() -> RolePickerScheduler | None:
    return _scheduler
