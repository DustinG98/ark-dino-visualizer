import io
import logging

import discord
from discord import Interaction
from discord.ui import Label, TextInput

from ..backend_client import BackendClient, BackendError, convert_png_to_webp, is_too_large_for_discord
from ..cache import Cache
from ..config import NEUTRAL_COLOR_ID, REGION_COUNT


log = logging.getLogger(__name__)


DISCORD_UPLOAD_CAP = 8 * 1024 * 1024


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


def _neutral_colors() -> dict[int, int]:
    return {i: NEUTRAL_COLOR_ID for i in range(REGION_COUNT)}


class ColorModal(discord.ui.Modal, title="Set Color"):
    region_id: int
    builder_view: "DinoBuilderView"

    color_id = Label(text="Color ID", component=TextInput(
        placeholder="e.g. 1, 51, 201",
        style=discord.TextStyle.short,
        min_length=1,
        max_length=5,
    ))

    def __init__(self, region_id: int, builder_view: "DinoBuilderView"):
        super().__init__()
        self.region_id = region_id
        self.builder_view = builder_view

    async def on_submit(self, interaction: Interaction) -> None:
        try:
            color_id = int(self.color_id.component.value.strip())
        except ValueError:
            await interaction.response.send_message("Enter a numeric color ID, e.g. `1`.", ephemeral=True)
            return
        valid_ids = {c.get("ID") or c.get("id") for c in self.builder_view.cache.colors}
        if color_id not in valid_ids:
            await interaction.response.send_message(
                f"Unknown color ID `{color_id}`. Use `/dino help` to see available IDs.",
                ephemeral=True,
            )
            return
        self.builder_view.region_colors[self.region_id] = color_id
        self.builder_view.active_region = self.region_id
        self.builder_view._rebuild_region_options()
        embed = discord.Embed(
            title=f"Color {self.builder_view.dino['name']}",
            description=self.builder_view._render_status_text(),
            color=discord.Color.blurple(),
        )
        await interaction.response.edit_message(embed=embed, view=self.builder_view)


class DinoBuilderView(discord.ui.View):
    def __init__(self, client: BackendClient, cache: Cache, dino: dict):
        super().__init__(timeout=600)
        self.client = client
        self.cache = cache
        self.dino = dino
        self.used_regions: list[int] = list(dino.get("usedRegions", []))
        if not self.used_regions:
            self.used_regions = list(range(REGION_COUNT))
        self.region_colors: dict[int, int] = _neutral_colors()
        self.active_region: int | None = self.used_regions[0] if self.used_regions else None

    def _render_status_text(self) -> str:
        lines = []
        region_lookup = {r.get("RegionID", r.get("regionId", idx)): r for idx, r in enumerate(self.cache.regions)}
        for region_id in self.used_regions:
            region = region_lookup.get(region_id)
            color_id = self.region_colors.get(region_id, NEUTRAL_COLOR_ID)
            label = _region_label(region, region_id)
            marker = " >>> " if region_id == self.active_region else "     "
            lines.append(f"{marker}{label}: color `{color_id}`")
        if not lines:
            return f"**{self.dino['name']}** — no mask; rendering with neutral colors."
        header = f"**{self.dino['name']}**"
        if self.active_region is not None:
            active_label = _region_label(region_lookup.get(self.active_region), self.active_region)
            header += f" — editing: **{active_label}**"
        return header + "\n" + "\n".join(f"  {l}" for l in lines)

    async def _edit_picker(self, interaction: Interaction) -> None:
        embed = discord.Embed(
            title=f"Color {self.dino['name']}",
            description=self._render_status_text(),
            color=discord.Color.blurple(),
        )
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.select(
        placeholder="Pick a region to edit…",
        min_values=1,
        max_values=1,
        options=[discord.SelectOption(label="Region 0", value="0")],
    )
    async def region_select(self, interaction: Interaction, select: discord.ui.Select):
        self.active_region = int(select.values[0])
        self._rebuild_region_options()
        modal = ColorModal(self.active_region, self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Set Color", style=discord.ButtonStyle.secondary)
    async def set_color_button(self, interaction: Interaction, button: discord.ui.Button):
        if self.active_region is None:
            await interaction.response.send_message("Pick a region first.", ephemeral=True)
            return
        modal = ColorModal(self.active_region, self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Reset", style=discord.ButtonStyle.danger)
    async def reset_button(self, interaction: Interaction, button: discord.ui.Button):
        self.region_colors = _neutral_colors()
        self._rebuild_region_options()
        await self._edit_picker(interaction)

    @discord.ui.button(label="Render", style=discord.ButtonStyle.success)
    async def render_button(self, interaction: Interaction, button: discord.ui.Button):
        if not self.dino.get("usedRegions"):
            await interaction.response.send_message(
                f"`{self.dino['name']}` doesn't support recoloring (no mask).",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=False)
        try:
            png = await self.client.render(self.dino["imageFile"], self.region_colors)
        except BackendError as exc:
            log.warning("render failed: %s", exc)
            await interaction.followup.send(
                f"Render failed: `{exc.message}` (status {exc.status_code}).",
                ephemeral=True,
            )
            return

        attachment, _, fallback = self._build_attachment(png)
        region_lookup = {r.get("RegionID", r.get("regionId", idx)): r for idx, r in enumerate(self.cache.regions)}
        lines = []
        for region_id in sorted(self.region_colors):
            region = region_lookup.get(region_id)
            lines.append(f"**{_region_label(region, region_id)}** → color `{self.region_colors[region_id]}`")
        embed = discord.Embed(
            title=f"Render: {self.dino['name']}",
            description="\n".join(lines) if lines else "No regions applied.",
            color=discord.Color.blurple(),
        )
        if fallback:
            embed.set_footer(text="Rendered as WebP to fit Discord's upload limit.")
        await interaction.followup.send(embed=embed, file=attachment)

        try:
            await interaction.edit_original_response(
                embed=discord.Embed(
                    title=f"Color {self.dino['name']}",
                    description="Rendered. Reset to start over.",
                    color=discord.Color.green(),
                ),
                view=None,
            )
        except Exception:
            pass

    def _build_attachment(self, png: bytes) -> tuple[discord.File, str, bool]:
        if is_too_large_for_discord(png, DISCORD_UPLOAD_CAP):
            webp = convert_png_to_webp(png)
            stem = self.dino["name"].replace(" ", "_")
            return discord.File(io.BytesIO(webp), filename=f"{stem}.webp"), f"{stem}.webp", True
        stem = self.dino["name"].replace(" ", "_")
        return discord.File(io.BytesIO(png), filename=f"{stem}.png"), f"{stem}.png", False

    def _rebuild_region_options(self) -> None:
        region_lookup = {r.get("RegionID", r.get("regionId", idx)): r for idx, r in enumerate(self.cache.regions)}
        options = []
        for region_id in self.used_regions:
            region = region_lookup.get(region_id)
            label = _region_label(region, region_id)[:100]
            color_id = self.region_colors.get(region_id, NEUTRAL_COLOR_ID)
            desc = f"color {color_id}"
            options.append(discord.SelectOption(label=label, value=str(region_id), description=desc))
        if not options:
            options = [discord.SelectOption(label="(no regions)", value="-1")]
        self.region_select.options = options

    def prime(self) -> None:
        self._rebuild_region_options()
