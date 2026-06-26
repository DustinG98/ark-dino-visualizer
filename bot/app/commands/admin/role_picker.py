import logging

import discord
from discord import app_commands, Interaction


log = logging.getLogger(__name__)


def _get_client():
    from ...bot_commands import _get_client
    return _get_client()


async def run_rp_add_role(
    guild_id: int,
    role_id: int,
    label: str,
    emoji: str | None = None,
    description: str | None = None,
) -> tuple[bool, str]:
    backend = _get_client()
    try:
        await backend.add_role_picker_role(
            guild_id=guild_id,
            role_id=role_id,
            label=label,
            emoji=emoji,
            description=description,
        )
    except Exception as exc:
        msg = getattr(exc, "message", str(exc))
        return False, f"Failed to add role: {msg}"
    try:
        await _refresh_public_panel(guild_id)
    except Exception as exc:
        log.warning("failed to refresh public panel after add: %s", exc)
    try:
        await _refresh_admin_panel(guild_id)
    except Exception as exc:
        log.warning("failed to refresh admin panel after add: %s", exc)
    return True, f"Role **{label}** added."


async def run_rp_edit_role(
    guild_id: int,
    position: int,
    label: str | None = None,
    emoji: str | None = None,
    description: str | None = None,
    role_id: int | None = None,
) -> tuple[bool, str]:
    backend = _get_client()
    try:
        await backend.edit_role_picker_role(
            guild_id=guild_id,
            position=position,
            label=label,
            emoji=emoji,
            description=description,
        )
    except Exception as exc:
        msg = getattr(exc, "message", str(exc))
        return False, f"Failed to edit role: {msg}"
    try:
        await _refresh_public_panel(guild_id)
    except Exception as exc:
        log.warning("failed to refresh public panel after edit: %s", exc)
    try:
        await _refresh_admin_panel(guild_id)
    except Exception as exc:
        log.warning("failed to refresh admin panel after edit: %s", exc)
    return True, f"Role updated."


async def run_rp_remove_role(guild_id: int, position: int) -> tuple[bool, str]:
    backend = _get_client()
    try:
        await backend.remove_role_picker_role(guild_id, position)
    except Exception as exc:
        msg = getattr(exc, "message", str(exc))
        return False, f"Failed to remove role: {msg}"
    try:
        await _refresh_public_panel(guild_id)
    except Exception as exc:
        log.warning("failed to refresh public panel after remove: %s", exc)
    try:
        await _refresh_admin_panel(guild_id)
    except Exception as exc:
        log.warning("failed to refresh admin panel after remove: %s", exc)
    return True, "Role removed."


async def run_rp_view_roles(guild_id: int) -> tuple[list[dict], str | None]:
    backend = _get_client()
    try:
        roles = await backend.get_role_picker_roles(guild_id)
    except Exception as exc:
        return [], f"Failed to fetch roles: {exc}"
    return roles, None


async def run_rp_set_public_channel(guild_id: int, channel_id: int | None) -> dict:
    backend = _get_client()
    try:
        await backend.update_role_picker_public_panel_channel(guild_id, channel_id)
    except Exception as exc:
        return {"ok": False, "message": str(exc)}
    return {"ok": True}


async def run_rp_disable(client: discord.Client, guild_id: int) -> tuple[bool, str]:
    backend = _get_client()
    guild = client.get_guild(int(guild_id))

    entry = None
    try:
        from ...role_picker_scheduler import get_public_panel_message
        entry = get_public_panel_message(guild_id)
    except Exception:
        pass

    if entry and guild is not None:
        channel_id, message_id = entry
        channel = guild.get_channel(int(channel_id))
        if isinstance(channel, discord.TextChannel) and message_id:
            try:
                msg = await channel.fetch_message(int(message_id))
                await msg.delete()
            except (discord.NotFound, discord.HTTPException):
                pass

    try:
        await backend.update_role_picker_public_panel_channel(guild_id, None)
        await backend.update_role_picker_public_panel_message(guild_id, None)
    except Exception as exc:
        return False, f"Failed to disable: {exc}"

    try:
        from ...role_picker_scheduler import forget_public_panel_message
        forget_public_panel_message(guild_id)
    except Exception as exc:
        log.warning("failed to clear public panel cache: %s", exc)

    return True, "Role picker public panel disabled."


async def _refresh_public_panel(guild_id: int) -> None:
    sched = _get_scheduler()
    if sched is not None:
        await sched.refresh_public_panel_for_guild(guild_id)


async def _refresh_admin_panel(guild_id: int) -> None:
    sched = _get_scheduler()
    if sched is not None:
        await sched.refresh_admin_panel_for_guild(guild_id)


def _get_scheduler():
    from ...role_picker_scheduler import get_scheduler
    return get_scheduler()


async def post_admin_panel(client: discord.Client, guild: discord.Guild, channel_id: int) -> int | None:
    from ...views.role_picker_admin import _build_admin_embed, make_admin_view
    channel = guild.get_channel(int(channel_id))
    if channel is None or not isinstance(channel, discord.TextChannel):
        log.warning("role picker admin panel: channel %s not found in guild %s", channel_id, guild.id)
        return None
    bot_member = guild.me
    if bot_member is None:
        return None
    perms = channel.permissions_for(bot_member)
    if not (perms.view_channel and perms.send_messages):
        log.warning("role picker admin panel: bot lacks perms in channel %s", channel_id)
        return None
    backend = _get_client()
    try:
        settings = await backend.get_role_picker_settings(guild.id)
    except Exception as exc:
        log.warning("role picker admin panel: failed to fetch settings: %s", exc)
        settings = None
    roles = []
    public_channel_id = None
    if settings:
        roles = settings.get("roles", [])
        public_channel_id = settings.get("public_panel_channel_id")
    try:
        view = make_admin_view(guild.id)
        msg = await channel.send(embed=_build_admin_embed(guild.id, roles, public_channel_id), view=view)
        return msg.id
    except discord.HTTPException as exc:
        log.warning("role picker admin panel: failed to post in channel %s: %s", channel_id, exc)
        return None


async def post_public_panel(client: discord.Client, guild: discord.Guild, channel_id: int) -> int | None:
    from ...views.role_picker_public import _build_public_embed, make_public_view
    channel = guild.get_channel(int(channel_id))
    if channel is None or not isinstance(channel, discord.TextChannel):
        log.warning("role picker public panel: channel %s not found in guild %s", channel_id, guild.id)
        return None
    bot_member = guild.me
    if bot_member is None:
        return None
    perms = channel.permissions_for(bot_member)
    if not (perms.view_channel and perms.send_messages):
        log.warning("role picker public panel: bot lacks perms in channel %s", channel_id)
        return None
    backend = _get_client()
    try:
        roles = await backend.get_role_picker_roles(guild.id)
    except Exception as exc:
        log.warning("role picker public panel: failed to fetch roles: %s", exc)
        roles = []
    try:
        view = make_public_view(guild.id, roles)
        msg = await channel.send(embed=_build_public_embed(roles), view=view)
        return msg.id
    except discord.HTTPException as exc:
        log.warning("role picker public panel: failed to post in channel %s: %s", channel_id, exc)
        return None


def register_role_picker_admin_commands(admin_group: app_commands.Group) -> None:

    @admin_group.command(
        name="role-picker-admin-panel",
        description="Post or move the persistent role picker admin panel.",
    )
    @app_commands.describe(channel="Channel where the admin panel should live.")
    async def role_picker_admin_panel(interaction: Interaction, channel: discord.TextChannel):
        guild_id = interaction.guild_id
        if guild_id is None:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return

        backend = _get_client()
        try:
            await backend.update_role_picker_admin_panel_channel(guild_id, channel.id)
        except Exception as exc:
            await interaction.response.send_message(f"Failed to save channel: {exc}", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        message_id = await post_admin_panel(interaction.client, interaction.guild, channel.id)
        if message_id is None:
            await interaction.followup.send(
                f"Channel saved as {channel.mention}, but I couldn't post there. "
                "Check that I have View + Send Messages in that channel.",
                ephemeral=True,
            )
            return

        try:
            await backend.update_role_picker_admin_panel_message(guild_id, message_id)
        except Exception as exc:
            log.warning("failed to persist admin panel message id: %s", exc)

        from ...role_picker_scheduler import register_and_persist_admin_panel_message
        await register_and_persist_admin_panel_message(backend, guild_id, channel.id, message_id)

        await interaction.followup.send(
            f"Admin panel posted in {channel.mention}. It will auto-recover if deleted.",
            ephemeral=True,
        )

    @admin_group.command(
        name="role-picker-public-panel",
        description="Post or move the persistent public role picker panel.",
    )
    @app_commands.describe(channel="Channel where the public panel should live.")
    async def role_picker_public_panel(interaction: Interaction, channel: discord.TextChannel):
        guild_id = interaction.guild_id
        if guild_id is None:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return

        backend = _get_client()
        try:
            await backend.update_role_picker_public_panel_channel(guild_id, channel.id)
        except Exception as exc:
            await interaction.response.send_message(f"Failed to save channel: {exc}", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        message_id = await post_public_panel(interaction.client, interaction.guild, channel.id)
        if message_id is None:
            await interaction.followup.send(
                f"Channel saved as {channel.mention}, but I couldn't post there. "
                "Check that I have View + Send Messages in that channel.",
                ephemeral=True,
            )
            return

        try:
            await backend.update_role_picker_public_panel_message(guild_id, message_id)
        except Exception as exc:
            log.warning("failed to persist public panel message id: %s", exc)

        from ...role_picker_scheduler import register_and_persist_public_panel_message
        await register_and_persist_public_panel_message(backend, guild_id, channel.id, message_id)

        await interaction.followup.send(
            f"Public panel posted in {channel.mention}. It will auto-recover if deleted.",
            ephemeral=True,
        )
