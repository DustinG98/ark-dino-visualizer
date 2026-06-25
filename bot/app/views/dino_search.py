import logging

import discord
from discord import Interaction

from ..cache import Cache


log = logging.getLogger(__name__)


def _region_label(region: dict | None, region_id: int) -> str:
    if region:
        name = str(region.get("Name") or region.get("name") or "").strip()
        if name:
            return f"Region {region_id} — {name}"
    return f"Region {region_id}"


class DinoSearchView(discord.ui.View):
    def __init__(self, cache: Cache, results: list[dict], author_id: int):
        super().__init__(timeout=300)
        self.cache = cache
        self.results = results
        self.author_id = author_id
        self._build_options()

    def _build_options(self) -> None:
        options = [
            discord.SelectOption(label=d["name"][:100], value=d["name"][:100])
            for d in self.results[:25]
        ]
        self.dino_select.options = options

    @discord.ui.select(placeholder="Pick a dino to open the builder…", min_values=1, max_values=1)
    async def dino_select(self, interaction: Interaction, select: discord.ui.Select):
        from ..bot_commands import _get_client
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This menu isn't for you.", ephemeral=True)
            return
        name = select.values[0]
        dino = self.cache.find_dino(name)
        if dino is None:
            await interaction.response.send_message("That dino is no longer in the cache.", ephemeral=True)
            return
        from ..views.dino_builder import DinoBuilderView
        view = DinoBuilderView(_get_client(), self.cache, dino)
        view.prime()
        embed = discord.Embed(
            title=f"Color {dino['name']}",
            description=(
                f"**{dino['name']}** — pick a region from the dropdown.\n"
                "A color picker modal will open automatically."
                if dino.get("usedRegions")
                else f"**{dino['name']}** — no mask; rendering will use neutral colors only."
            ),
            color=discord.Color.blurple(),
        )
        await interaction.response.edit_message(embed=embed, view=view)
        self.stop()

    async def interaction_check(self, interaction: Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This menu isn't for you.", ephemeral=True)
            return False
        return True
