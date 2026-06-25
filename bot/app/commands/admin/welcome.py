import discord
from discord import app_commands, Interaction

from ...views.welcome import WelcomeMessageModal, SetMessageView
from ...backend_client import BackendError


def _get_client():
    from ...bot_commands import _get_client
    return _get_client()


def register_welcome_commands(admin_group: app_commands.Group) -> None:

    @admin_group.command(name="welcome-set-channel", description="Set the channel for welcome messages.")
    @app_commands.describe(channel="The channel to send welcome messages to")
    async def welcome_set_channel(interaction: Interaction, channel: discord.TextChannel):
        guild_id = interaction.guild_id
        if guild_id is None:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return

        try:
            current = await _get_client().get_welcome_settings(guild_id)
        except BackendError as exc:
            await interaction.response.send_message(f"Failed to fetch settings: `{exc.message}`", ephemeral=True)
            return

        message = current["message"] if current else "Welcome to {server.name}, {member.mention}!"
        enabled = current.get("enabled", False) if current else False

        try:
            await _get_client().set_welcome_settings(guild_id, channel.id, message, enabled=enabled)
        except BackendError as exc:
            await interaction.response.send_message(f"Failed to save: `{exc.message}`", ephemeral=True)
            return

        await interaction.response.send_message(
            f"Welcome channel set to {channel.mention}.", ephemeral=True
        )

    @admin_group.command(name="welcome-set-message", description="Set the welcome message (supports multiline).")
    async def welcome_set_message(interaction: Interaction):
        guild_id = interaction.guild_id
        if guild_id is None:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return

        try:
            current = await _get_client().get_welcome_settings(guild_id)
        except BackendError as exc:
            await interaction.response.send_message(f"Failed to fetch settings: `{exc.message}`", ephemeral=True)
            return

        if current is None:
            await interaction.response.send_message(
                "No welcome channel set yet. Use `/forge admin welcome-set-channel` first.",
                ephemeral=True,
            )
            return

        current_message = current.get("message", "") if current else ""
        view = SetMessageView(current_message, WelcomeMessageModal)
        embed = discord.Embed(
            title="Welcome Message Editor",
            description="Click the button below to edit your welcome message.\n\n"
                       f"**Current message:**\n{current_message or '_not set_'}",
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @admin_group.command(name="welcome-view", description="View current welcome settings.")
    async def welcome_view(interaction: Interaction):
        guild_id = interaction.guild_id
        if guild_id is None:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return

        try:
            current = await _get_client().get_welcome_settings(guild_id)
        except BackendError as exc:
            await interaction.response.send_message(f"Failed to fetch settings: `{exc.message}`", ephemeral=True)
            return

        if current is None:
            await interaction.response.send_message(
                "No welcome message configured. Use `/forge admin welcome-set-channel` and `/forge admin welcome-set-message` to set up.",
                ephemeral=True,
            )
            return

        guild = interaction.guild
        channel = guild.get_channel(current["channel_id"]) if guild else None
        channel_mention = channel.mention if channel else f"Unknown channel ({current['channel_id']})"

        enabled = current.get("enabled", False)
        status = "Enabled" if enabled else "Disabled"

        embed = discord.Embed(
            title="Welcome Settings",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Status", value=status, inline=False)
        embed.add_field(name="Channel", value=channel_mention, inline=False)
        embed.add_field(name="Message", value=current["message"] or "_not set_", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @admin_group.command(name="welcome-toggle", description="Enable or disable welcome messages.")
    @app_commands.describe(action="Enable or disable welcome messages")
    async def welcome_toggle(interaction: Interaction, action: str):
        if action not in ("enable", "disable"):
            await interaction.response.send_message("Action must be 'enable' or 'disable'.", ephemeral=True)
            return

        guild_id = interaction.guild_id
        if guild_id is None:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return

        try:
            current = await _get_client().get_welcome_settings(guild_id)
        except BackendError as exc:
            await interaction.response.send_message(f"Failed to fetch settings: `{exc.message}`", ephemeral=True)
            return

        if current is None:
            await interaction.response.send_message(
                "No welcome message configured. Use `/forge admin welcome-set-channel` and `/forge admin welcome-set-message` to set up first.",
                ephemeral=True,
            )
            return

        enabled = action == "enable"
        try:
            await _get_client().set_welcome_settings(
                guild_id,
                current["channel_id"],
                current["message"],
                enabled=enabled,
            )
        except BackendError as exc:
            await interaction.response.send_message(f"Failed to update: `{exc.message}`", ephemeral=True)
            return

        status = "enabled" if enabled else "disabled"
        await interaction.response.send_message(f"Welcome messages are now **{status}**.", ephemeral=True)
