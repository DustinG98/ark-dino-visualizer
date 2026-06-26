import logging

import discord
from discord import app_commands, Interaction

from ...backend_client import BackendError


log = logging.getLogger(__name__)


def _get_client():
    from ...bot_commands import _get_client
    return _get_client()


def _admin_panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🛠️ Giveaway Admin Panel",
        color=discord.Color.blurple(),
        description=(
            "Manage giveaways for this server from the buttons below.\n"
            "Existing slash commands (`/forge admin giveaway-*`) still work as a fallback."
        ),
    )
    embed.add_field(
        name="Available actions",
        value=(
            "• **Enable / Reconfigure** — set announcement channel + category\n"
            "• **Disable** — pause giveaways (keeps settings)\n"
            "• **Set Ping Role** — choose a role to ping in new giveaway channels\n"
            "• **View Settings** — show the current configuration\n"
            "• **Set Public Panel Channel** — choose the channel for the public giveaway panel\n"
            "• **Force-Cancel a Giveaway** — pick from a list of active giveaways"
        ),
        inline=False,
    )
    embed.set_footer(text="This panel auto-recovers if the message is deleted.")
    return embed


async def run_giveaway_enable(
    guild_id: int,
    channel_id: int,
    category_id: int,
) -> dict:
    """Persist enabled + channel + category. Returns dict with 'ok' and 'message'."""
    backend = _get_client()
    try:
        await backend.set_giveaway_settings(guild_id, enabled=True, channel_id=channel_id)
    except BackendError as exc:
        return {"ok": False, "field": "channel", "message": exc.message}
    try:
        await backend.update_giveaway_category(guild_id, category_id)
    except BackendError as exc:
        return {"ok": False, "field": "category", "message": exc.message}
    return {"ok": True}


async def run_giveaway_disable(guild_id: int) -> dict:
    backend = _get_client()
    try:
        current = await backend.get_giveaway_settings(guild_id)
    except BackendError as exc:
        return {"ok": False, "message": exc.message}
    if current is None:
        return {"ok": False, "message": "Giveaways aren't configured."}
    channel_id = current.get("channel_id")
    try:
        await backend.set_giveaway_settings(
            guild_id,
            enabled=False,
            channel_id=int(channel_id) if channel_id else None,
        )
    except BackendError as exc:
        return {"ok": False, "message": exc.message}
    return {"ok": True}


async def run_giveaway_set_ping_role(guild_id: int, role_id: int | None) -> dict:
    backend = _get_client()
    try:
        await backend.update_giveaway_ping_role(guild_id, role_id)
    except BackendError as exc:
        return {"ok": False, "message": exc.message}
    return {"ok": True}


async def run_giveaway_view(guild_id: int) -> tuple[dict | None, discord.Embed | None, str | None]:
    backend = _get_client()
    try:
        current = await backend.get_giveaway_settings(guild_id)
    except BackendError as exc:
        return None, None, exc.message
    if current is None:
        return None, None, "Giveaways aren't configured. Use `/forge admin giveaway-enable`."

    channel_id = current.get("channel_id")
    channel_mention = f"<#{channel_id}>" if channel_id else "_not set_"
    category_id = current.get("category_id")
    category_mention = f"<#{category_id}>" if category_id else "_not set_"
    status = "Enabled" if current.get("enabled") else "Disabled"
    ping_role_id = current.get("ping_role_id")
    ping_role_mention = f"<@&{ping_role_id}>" if ping_role_id else "_not set_"
    panel_channel_id = current.get("admin_panel_channel_id")
    panel_mention = f"<#{panel_channel_id}>" if panel_channel_id else "_not set_"

    embed = discord.Embed(title="Giveaway Settings", color=discord.Color.blurple())
    public_panel_channel_id = current.get("public_panel_channel_id")
    public_panel_mention = f"<#{public_panel_channel_id}>" if public_panel_channel_id else "_not set_"

    embed = discord.Embed(title="Giveaway Settings", color=discord.Color.blurple())
    embed.add_field(name="Status", value=status, inline=True)
    embed.add_field(name="Channel", value=channel_mention, inline=True)
    embed.add_field(name="Category", value=category_mention, inline=True)
    embed.add_field(name="Ping role", value=ping_role_mention, inline=True)
    embed.add_field(name="Admin panel channel", value=panel_mention, inline=True)
    embed.add_field(name="Public panel channel", value=public_panel_mention, inline=True)
    return current, embed, None


async def run_giveaway_force_cancel(client: discord.Client, guild_id: int, giveaway_id: str, requested_by: int) -> dict:
    backend = _get_client()
    try:
        data = await backend.get_giveaway(giveaway_id)
    except BackendError as exc:
        return {"ok": False, "stage": "fetch", "message": exc.message}
    if data is None:
        return {"ok": False, "stage": "lookup", "message": "Giveaway not found."}
    if int(data.get("guild_id", 0)) != guild_id:
        return {"ok": False, "stage": "guild", "message": "That giveaway belongs to a different server."}

    from ...giveaway_scheduler import cancel_giveaway_now
    try:
        await cancel_giveaway_now(client, giveaway_id, requested_by=requested_by)
    except Exception as exc:
        return {"ok": False, "stage": "cancel", "message": str(exc)}
    return {"ok": True, "data": data}


async def run_giveaway_panel_set_channel(guild_id: int, channel_id: int) -> dict:
    backend = _get_client()
    try:
        await backend.update_giveaway_admin_panel_channel(guild_id, channel_id)
    except BackendError as exc:
        return {"ok": False, "message": exc.message}
    return {"ok": True}


async def run_giveaway_public_panel_set_channel(guild_id: int, channel_id: int) -> dict:
    backend = _get_client()
    try:
        await backend.update_giveaway_public_panel_channel(guild_id, channel_id)
    except BackendError as exc:
        return {"ok": False, "message": exc.message}
    return {"ok": True}


async def post_admin_panel(client: discord.Client, guild: discord.Guild, channel_id: int) -> int | None:
    """Post (or replace) the admin panel embed in the configured channel. Returns the new message id, or None on failure."""
    channel = guild.get_channel(int(channel_id))
    if channel is None or not isinstance(channel, discord.TextChannel):
        log.warning("admin panel: channel %s not found in guild %s", channel_id, guild.id)
        return None
    bot_member = guild.me
    if bot_member is None:
        return None
    perms = channel.permissions_for(bot_member)
    if not (perms.view_channel and perms.send_messages):
        log.warning("admin panel: bot lacks perms in channel %s", channel_id)
        return None

    try:
        from ...views.admin_panel import make_admin_panel_view
        view = make_admin_panel_view(guild.id)
        msg = await channel.send(embed=_admin_panel_embed(), view=view)
        return msg.id
    except discord.HTTPException as exc:
        log.warning("admin panel: failed to post in channel %s: %s", channel_id, exc)
        return None


async def post_public_panel(client: discord.Client, guild: discord.Guild, channel_id: int) -> int | None:
    """Post (or replace) the public panel embed in the configured channel. Returns the new message id, or None on failure."""
    from ...views.public_giveaway_panel import _public_panel_embed, make_public_panel_view

    channel = guild.get_channel(int(channel_id))
    if channel is None or not isinstance(channel, discord.TextChannel):
        log.warning("public panel: channel %s not found in guild %s", channel_id, guild.id)
        return None
    bot_member = guild.me
    if bot_member is None:
        return None
    perms = channel.permissions_for(bot_member)
    if not (perms.view_channel and perms.send_messages):
        log.warning("public panel: bot lacks perms in channel %s", channel_id)
        return None

    try:
        view = make_public_panel_view()
        msg = await channel.send(embed=_public_panel_embed(), view=view)
        return msg.id
    except discord.HTTPException as exc:
        log.warning("public panel: failed to post in channel %s: %s", channel_id, exc)
        return None


def register_giveaway_admin_commands(admin_group: app_commands.Group) -> None:

    @admin_group.command(name="giveaway-enable", description="Enable giveaways in this server.")
    @app_commands.describe(
        channel="Channel where new giveaways will be posted.",
        category="Category where per-giveaway and exchange channels will be created.",
    )
    async def giveaway_enable(
        interaction: Interaction,
        channel: discord.TextChannel,
        category: discord.CategoryChannel,
    ):
        guild_id = interaction.guild_id
        if guild_id is None:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return
        result = await run_giveaway_enable(guild_id, channel.id, category.id)
        if not result["ok"]:
            await interaction.response.send_message(f"Failed to save {result['field']}: `{result['message']}`", ephemeral=True)
            return
        await interaction.response.send_message(
            f"Giveaways enabled. Announcements go in {channel.mention}; per-giveaway and exchange channels will be created in {category.mention}.",
            ephemeral=True,
        )

    @admin_group.command(name="giveaway-disable", description="Disable giveaways in this server.")
    async def giveaway_disable(interaction: Interaction):
        guild_id = interaction.guild_id
        if guild_id is None:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return
        result = await run_giveaway_disable(guild_id)
        if not result["ok"]:
            await interaction.response.send_message(f"Failed: `{result['message']}`", ephemeral=True)
            return
        await interaction.response.send_message("Giveaways disabled.", ephemeral=True)

    @admin_group.command(name="giveaway-ping-role", description="Set the role pinged when a new giveaway opens (in the per-giveaway channel).")
    @app_commands.describe(role="Role to ping (or leave empty to clear).")
    async def giveaway_ping_role(interaction: Interaction, role: discord.Role | None = None):
        guild_id = interaction.guild_id
        if guild_id is None:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return
        role_id = role.id if role is not None else None
        result = await run_giveaway_set_ping_role(guild_id, role_id)
        if not result["ok"]:
            await interaction.response.send_message(f"Failed to save: `{result['message']}`", ephemeral=True)
            return
        if role is None:
            await interaction.response.send_message("Giveaway ping role cleared.", ephemeral=True)
        else:
            await interaction.response.send_message(
                f"{role.mention} will be pinged when a new giveaway is created.", ephemeral=True
            )

    @admin_group.command(name="giveaway-view", description="View giveaway settings.")
    async def giveaway_view(interaction: Interaction):
        guild_id = interaction.guild_id
        if guild_id is None:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return
        _, embed, err = await run_giveaway_view(guild_id)
        if err is not None:
            await interaction.response.send_message(err, ephemeral=True)
            return
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @admin_group.command(name="giveaway-cancel", description="Force-cancel a giveaway by id.")
    @app_commands.describe(giveaway_id="The giveaway id.")
    async def giveaway_force_cancel(interaction: Interaction, giveaway_id: str):
        guild_id = interaction.guild_id
        if guild_id is None:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        result = await run_giveaway_force_cancel(interaction.client, guild_id, giveaway_id, interaction.user.id)
        if not result["ok"]:
            await interaction.followup.send(f"Failed at {result['stage']}: `{result['message']}`", ephemeral=True)
            return
        await interaction.followup.send(f"Giveaway `{giveaway_id}` cancelled.", ephemeral=True)

    @admin_group.command(name="giveaway-panel", description="Post or move the persistent admin giveaway panel.")
    @app_commands.describe(channel="Channel where the admin panel should live.")
    async def giveaway_panel(interaction: Interaction, channel: discord.TextChannel):
        guild_id = interaction.guild_id
        if guild_id is None:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return

        result = await run_giveaway_panel_set_channel(guild_id, channel.id)
        if not result["ok"]:
            await interaction.response.send_message(f"Failed to save: `{result['message']}`", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        message_id = await post_admin_panel(interaction.client, interaction.guild, channel.id)
        if message_id is None:
            await interaction.followup.send(
                f"Panel channel saved as {channel.mention}, but I couldn't post there. "
                "Check that I have View + Send Messages in that channel.",
                ephemeral=True,
            )
            return

        from ...giveaway_scheduler import register_and_persist_admin_panel_message
        await register_and_persist_admin_panel_message(_get_client(), guild_id, channel.id, message_id)

        await interaction.followup.send(
            f"Admin panel posted in {channel.mention}. It will auto-recover if deleted.",
            ephemeral=True,
        )

    @admin_group.command(name="giveaway-public-panel", description="Post or move the persistent public giveaway panel.")
    @app_commands.describe(channel="Channel where the public panel should live.")
    async def giveaway_public_panel(interaction: Interaction, channel: discord.TextChannel):
        guild_id = interaction.guild_id
        if guild_id is None:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return

        result = await run_giveaway_public_panel_set_channel(guild_id, channel.id)
        if not result["ok"]:
            await interaction.response.send_message(f"Failed to save: `{result['message']}`", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        message_id = await post_public_panel(interaction.client, interaction.guild, channel.id)
        if message_id is None:
            await interaction.followup.send(
                f"Panel channel saved as {channel.mention}, but I couldn't post there. "
                "Check that I have View + Send Messages in that channel.",
                ephemeral=True,
            )
            return

        from ...giveaway_scheduler import register_and_persist_public_panel_message
        await register_and_persist_public_panel_message(_get_client(), guild_id, channel.id, message_id)

        await interaction.followup.send(
            f"Public panel posted in {channel.mention}. It will auto-recover if deleted.",
            ephemeral=True,
        )
