import io
import logging
from typing import Optional

import discord
from discord import app_commands, Interaction

from ...backend_client import BackendError, convert_png_to_webp, is_too_large_for_discord


log = logging.getLogger(__name__)

DISCORD_UPLOAD_CAP = 8 * 1024 * 1024


def _region_label(region: dict | None, region_id: int) -> str:
    if region:
        name = str(region.get("Name") or region.get("name") or "").strip()
        if name:
            return f"Region {region_id} — {name}"
    return f"Region {region_id}"


def _get_client():
    from ...bot_commands import _get_client
    return _get_client()


def register_render(ark_group: app_commands.Group, cache) -> None:
    async def dino_autocomplete(interaction: Interaction, current: str) -> list[app_commands.Choice[str]]:
        needle = current.lower()
        matches = [d for d in cache.dinos if not needle or needle in d["name"].lower()][:25]
        return [app_commands.Choice(name=d["name"][:100], value=d["name"][:100]) for d in matches]

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
