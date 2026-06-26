import discord
from discord import app_commands

from .backend_client import BackendClient


_client_ref: dict[str, BackendClient] = {}


def _get_client() -> BackendClient:
    return _client_ref["client"]


def set_client(client: BackendClient) -> None:
    _client_ref["client"] = client


def _admin_check(interaction: discord.Interaction) -> bool:
    if interaction.guild is None:
        return False
    member = interaction.user
    if not isinstance(member, discord.Member):
        return False
    perms = member.guild_permissions
    if perms.administrator or perms.manage_guild:
        return True
    raise app_commands.CheckFailure("You need the **Manage Server** permission to use this command.")


def register_commands(tree: app_commands.CommandTree, cache) -> None:
    from app.commands.ark import register_ark_commands
    from app.commands.admin import (
        register_welcome_commands,
        register_admin_help,
        register_giveaway_admin_commands,
        register_role_picker_admin_commands,
    )
    from app.commands.public.giveaway import register_giveaway_commands

    forge_group = app_commands.Group(name="forge", description="ARK: ASA dino recolorer")
    ark_group = app_commands.Group(name="ark", description="ARK dino subcommands", parent=forge_group)
    admin_group = app_commands.Group(
        name="admin",
        description="Admin commands (server administrators only).",
        parent=forge_group,
        default_permissions=discord.Permissions(administrator=True),
    )
    admin_group.interaction_check = _admin_check

    register_ark_commands(ark_group, cache)
    register_welcome_commands(admin_group)
    register_admin_help(admin_group)
    register_giveaway_admin_commands(admin_group)
    register_role_picker_admin_commands(admin_group)
    register_giveaway_commands(tree)

    @forge_group.command(name="help", description="Show help topics.")
    async def help_cmd(interaction):
        embed = discord.Embed(
            title="Forge — Help",
            color=discord.Color.blurple(),
            description="Use the commands below to get help for each category.",
        )
        embed.add_field(
            name="/forge ark help",
            value="ARK commands — search, render, colors, reaper calculator.",
            inline=False,
        )
        embed.add_field(
            name="/forge admin help",
            value="Admin commands — welcome message and giveaway management (Administrator only).",
            inline=False,
        )
        embed.add_field(
            name="/giveaway help",
            value="Public commands — create, list, and cancel giveaways.",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    tree.add_command(forge_group)
