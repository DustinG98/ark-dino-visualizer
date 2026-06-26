import logging
import re
import regex

import discord
from discord import Interaction


log = logging.getLogger(__name__)


TOGGLE_PREFIX = "role_picker:toggle"


def _safe_emoji(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    if len(value) > 64:
        return None
    if re.fullmatch(r"\d{15,21}", value):
        return None
    if len(regex.findall(r"\X", value, regex.UNICODE)) > 1:
        return None
    return value


def _parse_toggle_custom_id(custom_id: str) -> tuple[int, int] | None:
    if not custom_id.startswith(f"{TOGGLE_PREFIX}:"):
        return None
    parts = custom_id.split(":")
    if len(parts) != 4:
        return None
    try:
        return int(parts[2]), int(parts[3])
    except ValueError:
        return None


def _build_public_embed(roles: list[dict]) -> discord.Embed:
    embed = discord.Embed(
        title="🎭 Role Picker",
        color=discord.Color.blurple(),
        description="Click a button below to toggle a role. Click again to remove it.",
    )
    if roles:
        lines = []
        for r in roles:
            emoji_str = f"{_safe_emoji(r.get('emoji'))} " if r.get("emoji") else ""
            desc_str = f" — {r['description']}" if r.get("description") else ""
            lines.append(f"{emoji_str}**{r['label']}**{desc_str}")
        embed.add_field(
            name="Available Roles",
            value="\n".join(lines),
            inline=False,
        )
    else:
        embed.add_field(
            name="Available Roles",
            value="_No roles configured yet._",
            inline=False,
        )
    embed.set_footer(text="This panel auto-recovers if the message is deleted.")
    return embed


class RolePickerPublicView(discord.ui.View):
    def __init__(self, guild_id: int, roles: list[dict]):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.roles = {r["role_id"]: r for r in roles}
        for r in roles:
            role_id = r["role_id"]
            label = r["label"]
            emoji = _safe_emoji(r.get("emoji"))
            btn = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.secondary,
                custom_id=f"{TOGGLE_PREFIX}:{guild_id}:{role_id}",
                emoji=emoji,
            )
            btn.callback = self._on_toggle
            self.add_item(btn)

    async def _on_toggle(self, interaction: Interaction) -> None:
        custom_id = interaction.data.get("custom_id", "") if interaction.data else ""
        parsed = _parse_toggle_custom_id(custom_id)
        if parsed is None:
            await interaction.response.defer()
            return
        guild_id, role_id = parsed

        guild = interaction.guild
        if guild is None:
            await interaction.response.defer()
            return
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.defer()
            return

        role = guild.get_role(role_id)
        if role is None:
            await interaction.response.send_message(
                "That role no longer exists on this server.",
                ephemeral=True,
            )
            return

        try:
            if role in member.roles:
                await member.remove_roles(role)
                label = self.roles.get(role_id, {}).get("label", role.name)
                await interaction.response.send_message(
                    f"Removed **{label}**.",
                    ephemeral=True,
                )
            else:
                await member.add_roles(role)
                label = self.roles.get(role_id, {}).get("label", role.name)
                await interaction.response.send_message(
                    f"Added **{label}**.",
                    ephemeral=True,
                )
        except discord.Forbidden:
            await interaction.response.send_message(
                "I can't manage that role here. It may be above my highest role.",
                ephemeral=True,
            )
        except discord.HTTPException:
            await interaction.response.send_message(
                "Something went wrong trying to update your roles.",
                ephemeral=True,
            )


def make_public_view(guild_id: int, roles: list[dict]) -> RolePickerPublicView:
    return RolePickerPublicView(guild_id, roles)
