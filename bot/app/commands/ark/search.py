import discord
from discord import app_commands, Interaction

from ...cache import Cache
from ...views.dino_search import DinoSearchView


SEARCH_RESULT_LIMIT = 10


def register_search(ark_group: app_commands.Group, cache: Cache) -> None:
    async def dino_autocomplete(interaction: Interaction, current: str) -> list[app_commands.Choice[str]]:
        needle = current.lower()
        matches = [d for d in cache.dinos if not needle or needle in d["name"].lower()][:25]
        return [app_commands.Choice(name=d["name"][:100], value=d["name"][:100]) for d in matches]

    @ark_group.command(name="search", description="Search dinos and open the recolor builder.")
    @app_commands.describe(text="Substring to match against dino names.")
    async def search_cmd(interaction: Interaction, text: str):
        if not cache.warm:
            await interaction.response.send_message("Backend not ready yet — try again in a moment.", ephemeral=True)
            return
        results = cache.search_dinos(text, limit=SEARCH_RESULT_LIMIT)
        if not results:
            await interaction.response.send_message(f"No dinos match `{text}`.", ephemeral=True)
            return
        embed = discord.Embed(
            title=f"Dino search: {text}",
            description="\n".join(f"• **{d['name']}**" for d in results),
            color=discord.Color.blurple(),
        )
        view = DinoSearchView(cache, results, interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
