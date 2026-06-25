import discord
from discord import app_commands, Interaction

from ...config import NEUTRAL_COLOR_ID, REGION_COUNT


def _region_label(region: dict | None, region_id: int) -> str:
    if region:
        name = str(region.get("Name") or region.get("name") or "").strip()
        if name:
            return f"Region {region_id} — {name}"
    return f"Region {region_id}"


def register_help(ark_group: app_commands.Group, cache) -> None:
    @ark_group.command(name="help", description="Show ARK commands and color reference.")
    async def ark_help_cmd(interaction: Interaction):
        if not cache.warm:
            await interaction.response.send_message("Backend not ready yet — try again in a moment.", ephemeral=True)
            return

        embed = discord.Embed(
            title="Forge — ARK Commands",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="/forge ark search <text>",
            value="Search for a dino. Pick one from the dropdown to open the builder.",
            inline=False,
        )
        embed.add_field(
            name="/forge ark render <dino> [region0..5]",
            value="Power-user shortcut: render a dino with specific color IDs.\n"
            "Example: `/forge ark render Raptor region0:1 region1:2`",
            inline=False,
        )
        embed.add_field(
            name="/forge ark colors",
            value="Shows all 227 ASA color IDs with swatch previews.",
            inline=False,
        )
        embed.add_field(
            name="/forge ark reaper <queen> <player> <extra_levels>",
            value="Calculate Reaper level from queen level, player level, and XP bonus.\n"
            "Example: `/forge ark reaper 195 150 true`",
            inline=False,
        )
        embed.add_field(
            name="Builder workflow",
            value="1. Pick a region from the **dropdown**.\n"
            "2. A color picker modal opens automatically.\n"
            "3. Enter a color ID and submit.\n"
            "4. Repeat for other regions, then click **Render**.",
            inline=False,
        )
        region_lookup = {r.get("RegionID", r.get("regionId", idx)): r for idx, r in enumerate(cache.regions)}
        region_lines = [f"**{i}** — {_region_label(region_lookup.get(i), i)}" for i in range(REGION_COUNT)]
        embed.add_field(name="Regions (0–5)", value="\n".join(region_lines), inline=False)
        embed.add_field(
            name="Neutral color",
            value=f"Color ID `{NEUTRAL_COLOR_ID}` is neutral / no recolor. "
            "All regions default to this.",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
