import io
import logging

import discord
from discord import app_commands, Interaction


log = logging.getLogger(__name__)


def register_colors(ark_group: app_commands.Group, cache) -> None:
    @ark_group.command(name="colors", description="Show all available ASA color IDs with swatches.")
    async def colors_cmd(interaction: Interaction):
        if not cache.warm:
            await interaction.response.send_message("Backend not ready yet — try again in a moment.", ephemeral=True)
            return
        await interaction.response.defer()
        try:
            swatch_imgs = cache.color_swatch_images
        except Exception as exc:
            log.warning("failed to build color swatch: %s", exc)
            await interaction.followup.send(
                "Could not generate color swatch image.",
                ephemeral=True,
            )
            return
        files = [
            discord.File(io.BytesIO(img), filename=f"asa_colors_{i+1}.png")
            for i, img in enumerate(swatch_imgs)
        ]
        embed = discord.Embed(
            title=f"ASA Color Palette ({len(cache.colors)} colors)",
            description=(
                f"Page 1-{len(files)} of {len(cache.colors)} colors. "
                "Use `/forge help` to see region names and neutral color ID."
            ),
            color=discord.Color.blurple(),
        )
        await interaction.followup.send(embed=embed, files=files)
