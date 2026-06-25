import io
import logging
from typing import Optional

import discord
from discord import app_commands, Interaction

from .backend_client import BackendClient, BackendError, convert_png_to_webp, is_too_large_for_discord
from .cache import Cache
from .config import NEUTRAL_COLOR_ID, REGION_COUNT
from .views.dino_builder import DinoBuilderView


log = logging.getLogger(__name__)


DISCORD_UPLOAD_CAP = 8 * 1024 * 1024
SEARCH_RESULT_LIMIT = 10


def _color_label(color: dict) -> str:
    name = str(color.get("Name") or color.get("name") or "").strip()
    color_id = color.get("ID", color.get("id", "?"))
    if name:
        return f"{name} (#{color_id})"
    return f"Color {color_id}"


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
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This menu isn't for you.", ephemeral=True)
            return
        name = select.values[0]
        dino = self.cache.find_dino(name)
        if dino is None:
            await interaction.response.send_message("That dino is no longer in the cache.", ephemeral=True)
            return
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


_client_ref: dict[str, BackendClient] = {}


def _get_client() -> BackendClient:
    return _client_ref["client"]


def set_client(client: BackendClient) -> None:
    _client_ref["client"] = client


def register_commands(tree: app_commands.CommandTree, cache: Cache) -> None:

    forge_group = app_commands.Group(name="forge", description="ARK: ASA dino recolorer")
    ark_group = app_commands.Group(name="ark", description="ARK dino subcommands", parent=forge_group)

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

    @ark_group.command(name="render", description="Render a recolored dino directly (power-user).")
    @app_commands.describe(
        dino="Dino name",
        region0="Color ID for region 0",
        region1="Color ID for region 1",
        region2="Color ID for region 2",
        region3="Color ID for region 3",
        region4="Color ID for region 4",
        region5="Color ID for region 5",
    )
    @app_commands.autocomplete(dino=dino_autocomplete)
    async def render_cmd(
        interaction: Interaction,
        dino: str,
        region0: Optional[int] = None,
        region1: Optional[int] = None,
        region2: Optional[int] = None,
        region3: Optional[int] = None,
        region4: Optional[int] = None,
        region5: Optional[int] = None,
    ):
        if not cache.warm:
            await interaction.response.send_message("Backend not ready yet — try again in a moment.", ephemeral=True)
            return
        dino_entry = cache.find_dino(dino)
        if dino_entry is None:
            await interaction.response.send_message(f"No dino named `{dino}`.", ephemeral=True)
            return

        region_colors: dict[int, int] = {}
        for idx, value in enumerate([region0, region1, region2, region3, region4, region5]):
            if value is not None:
                region_colors[idx] = value

        used = set(dino_entry.get("usedRegions", []))
        if used:
            bad = [r for r in region_colors if r not in used]
            if bad:
                names = ", ".join(str(r) for r in bad)
                await interaction.response.send_message(
                    f"Region(s) {names} not present on `{dino_entry['name']}`. "
                    f"Used regions: {sorted(used)}.",
                    ephemeral=True,
                )
                return

        await interaction.response.defer()
        try:
            png = await _get_client().render(dino_entry["imageFile"], region_colors)
        except BackendError as exc:
            log.warning("render failed: %s", exc)
            await interaction.followup.send(
                f"Render failed: `{exc.message}` (status {exc.status_code}).",
                ephemeral=True,
            )
            return

        if is_too_large_for_discord(png, DISCORD_UPLOAD_CAP):
            webp = convert_png_to_webp(png)
            stem = dino_entry["imageFile"].rsplit(".", 1)[0]
            file = discord.File(io.BytesIO(webp), filename=f"{stem}.webp")
            note = " (rendered as WebP to fit Discord's upload limit)"
        else:
            stem = dino_entry["imageFile"].rsplit(".", 1)[0]
            file = discord.File(io.BytesIO(png), filename=f"{stem}.png")
            note = ""

        region_lookup = {r.get("RegionID", r.get("regionId", idx)): r for idx, r in enumerate(cache.regions)}
        lines = []
        for region_id in sorted(region_colors):
            region = region_lookup.get(region_id)
            lines.append(f"**{_region_label(region, region_id)}** → color `{region_colors[region_id]}`")
        embed = discord.Embed(
            title=f"Render: {dino_entry['name']}{note}",
            description="\n".join(lines) if lines else "No regions applied.",
            color=discord.Color.blurple(),
        )
        await interaction.followup.send(embed=embed, file=file)

    @ark_group.command(name="reaper", description="Calculate Reaper level from queen and player levels.")
    @app_commands.describe(
        queen_level="Reaper Queen's level",
        player_level="Player's character level",
        extra_levels="Did the pregnancy receive max XP bonus?",
    )
    async def reaper_cmd(
        interaction: Interaction,
        queen_level: int,
        player_level: int,
        extra_levels: bool,
    ):
        base_level = int(queen_level * ((player_level + 100) / 250))
        final_level = base_level + (75 if extra_levels else 0)

        if final_level >= 500:
            title = "Reaper Level Calculation"
            desc = (
                f"**Base level:** {base_level}\n"
                f"**XP bonus:** +{75 if extra_levels else 0}\n"
                f"**Final level:** {final_level}\n\n"
                "Exceptional result — this is a powerful Reaper!"
            )
            color = discord.Color.dark_purple()
        elif final_level >= 300:
            title = "Reaper Level Calculation"
            desc = (
                f"**Base level:** {base_level}\n"
                f"**XP bonus:** +{75 if extra_levels else 0}\n"
                f"**Final level:** {final_level}\n\n"
                "Solid Reaper. Worth the grind."
            )
            color = discord.Color.blue()
        else:
            title = "Reaper Level Calculation"
            desc = (
                f"**Base level:** {base_level}\n"
                f"**XP bonus:** +{75 if extra_levels else 0}\n"
                f"**Final level:** {final_level}\n\n"
                "Low yield. Consider higher queen/player levels before breeding."
            )
            color = discord.Color.orange()

        embed = discord.Embed(title=title, description=desc, color=color)
        await interaction.response.send_message(embed=embed)

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

    @forge_group.command(name="help", description="Show usage and color/region reference.")
    async def help_cmd(interaction: Interaction):
        if not cache.warm:
            await interaction.response.send_message("Backend not ready yet — try again in a moment.", ephemeral=True)
            return
        embed = discord.Embed(
            title="Forge — Help",
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

    tree.add_command(forge_group)
