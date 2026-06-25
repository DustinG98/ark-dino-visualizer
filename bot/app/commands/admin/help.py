import discord
from discord import app_commands, Interaction


def register_admin_help(admin_group: app_commands.Group) -> None:
    @admin_group.command(name="help", description="Show admin commands.")
    async def admin_help_cmd(interaction: Interaction):
        embed = discord.Embed(
            title="Forge — Admin Commands",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="/forge admin welcome-set-channel #channel",
            value="Set the channel where welcome messages are sent when new members join.",
            inline=False,
        )
        embed.add_field(
            name="/forge admin welcome-set-message",
            value="Set the welcome message text (supports multiline). Opens a modal editor.",
            inline=False,
        )
        embed.add_field(
            name="/forge admin welcome-view",
            value="View the current welcome channel, message, and enabled status.",
            inline=False,
        )
        embed.add_field(
            name="/forge admin welcome-toggle enable|disable",
            value="Enable or disable welcome messages for this server.",
            inline=False,
        )
        embed.add_field(
            name="Placeholders",
            value="Welcome messages support:\n"
            "`{member.mention}` — mentions the new member\n"
            "`{member.name}` — the member's username\n"
            "`{server.name}` — the server name\n"
            "`{channel.<channel-name>}` — clickable link to a channel (e.g. `{channel.general}`)",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
