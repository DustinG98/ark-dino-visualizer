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
            name="/forge admin giveaway-panel #channel",
            value="Post (or move) the persistent admin giveaway panel into a channel. The panel auto-recovers if the message is deleted. Use the buttons on the panel for day-to-day admin actions.",
            inline=False,
        )
        embed.add_field(
            name="/forge admin giveaway-public-panel #channel",
            value="Post (or move) the persistent public giveaway panel into a channel. Members click **Create Giveaway** to open the modal. Auto-recovers if deleted.",
            inline=False,
        )
        embed.add_field(
            name="/forge admin giveaway-enable #channel #category",
            value="Enable giveaways and set the announcement channel plus the category for per-giveaway and exchange channels. Re-run this command to change the channel or category. (Also available as a button on the panel.)",
            inline=False,
        )
        embed.add_field(
            name="/forge admin giveaway-disable",
            value="Disable giveaways for this server.",
            inline=False,
        )
        embed.add_field(
            name="/forge admin giveaway-ping-role @role",
            value="Set the role that gets pinged when a new giveaway is opened (in the per-giveaway channel).",
            inline=False,
        )
        embed.add_field(
            name="/forge admin giveaway-view",
            value="Show the current giveaway settings.",
            inline=False,
        )
        embed.add_field(
            name="/forge admin giveaway-cancel <id>",
            value=(
                "Force-cancel an active giveaway by its id. Deletes the giveaway message "
                "and the per-giveaway channel. No winners are selected — use the "
                "**End now (Admin)** button on the per-giveaway channel (or the "
                "**Force-Cancel a Giveaway** button on the admin panel) to end properly "
                "with winner selection."
            ),
            inline=False,
        )
        embed.add_field(
            name="Placeholders",
            value="Welcome messages support:\n"
            "`{member.mention}` — mentions the new member\n"
            "`{member.name}` — the member's username\n"
            "`{server.name}` — the server name\n"
            "`{channel.<channel-name>}` — clickable link to a text channel (e.g. `{channel.general}`)\n"
            "`{forum.<forum-name>}` — clickable link to a forum channel (e.g. `{forum.intro}`)",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
