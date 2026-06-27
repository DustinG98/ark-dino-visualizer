import logging
import asyncio
from datetime import datetime, timedelta, timezone

import discord
from discord import Interaction

from ..backend_client import BackendError


log = logging.getLogger(__name__)


class PublicGiveawayCreateModal(discord.ui.Modal, title="Create a Giveaway"):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(
            discord.ui.TextInput(
                custom_id="giveaway_create:title",
                label="Giveaway title",
                placeholder="e.g. 100x Cryopod Tokens",
                required=True,
                max_length=200,
            )
        )
        self.add_item(
            discord.ui.TextInput(
                custom_id="giveaway_create:winners",
                label="Winner count (1-20)",
                placeholder="1",
                required=True,
                max_length=3,
            )
        )
        self.add_item(
            discord.ui.TextInput(
                custom_id="giveaway_create:duration",
                label="Duration (e.g. 30m, 2h, 1d, max 30d)",
                placeholder="2h",
                required=True,
                max_length=10,
            )
        )
        self.add_item(
            discord.ui.TextInput(
                custom_id="giveaway_create:description",
                label="Description (optional, max 1000 chars)",
                style=discord.TextStyle.paragraph,
                required=False,
                max_length=1000,
            )
        )
        self.add_item(
            discord.ui.Label(
                text="Cover image (optional)",
                description="Upload an image/* file as the giveaway cover.",
                component=discord.ui.FileUpload(
                    custom_id="giveaway_create:cover_image",
                    required=False,
                    max_values=1,
                ),
            )
        )

    @property
    def title_input(self) -> str:
        return str(self.children[0].value or "").strip()

    @property
    def winners_input(self) -> str:
        return str(self.children[1].value or "").strip()

    @property
    def duration_input(self) -> str:
        return str(self.children[2].value or "").strip()

    @property
    def description_input(self) -> str:
        v = self.children[3].value
        return str(v).strip() if v else ""

    @property
    def cover_image_values(self):
        # children[4] is the Label; its wrapped component is .component
        label_item = self.children[4]
        return getattr(label_item.component, "values", None)

    async def on_submit(self, interaction: Interaction) -> None:
        from ..commands.public.giveaway import run_giveaway_create

        try:
            winners = int(self.winners_input)
        except ValueError:
            await interaction.response.send_message("Winners must be a number between 1 and 20.", ephemeral=True)
            return

        image_url: str | None = None
        attachments = self.cover_image_values
        if attachments:
            att = attachments[0]
            content_type = getattr(att, "content_type", "") or ""
            if not content_type.startswith("image/"):
                await interaction.response.send_message(
                    "Cover image must be an image/* attachment.", ephemeral=True
                )
                return
            image_url = att.url

        await interaction.response.defer(ephemeral=True)
        ok, message = await run_giveaway_create(
            interaction,
            title=self.title_input,
            winners=winners,
            duration_text=self.duration_input,
            description=(self.description_input or None),
            image_url=image_url,
        )
        if ok:
            await interaction.followup.send(message, ephemeral=True)


PUBLIC_PANEL_BTN_PREFIX = "public_giveaway:"


def _public_panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🎉 Giveaways",
        color=discord.Color.blurple(),
        description=(
            "Click **Create Giveaway** to open a form and start a new giveaway in this server.\n"
            "Winners get a private exchange channel after the giveaway ends."
        ),
    )
    embed.add_field(
        name="Slash commands",
        value=(
            "• `/giveaway create <title> <winners> <duration> [description] [image]`\n"
            "• `/giveaway list`\n"
            "• `/giveaway cancel <id>`"
        ),
        inline=False,
    )
    embed.set_footer(text="This panel auto-recovers if the message is deleted.")
    return embed


class PublicGiveawayPanelView(discord.ui.View):
    """Persistent panel posted by admins via `/forge admin giveaway-public-panel`.
    Survives bot restarts via `client.add_view(...)` registration in the scheduler.
    """

    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label="Create Giveaway",
                style=discord.ButtonStyle.primary,
                custom_id="public_giveaway:create",
            )
        )
        self.add_item(
            discord.ui.Button(
                label="Help",
                style=discord.ButtonStyle.secondary,
                custom_id="public_giveaway:help",
            )
        )
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.callback = self._on_button

    async def _on_button(self, interaction: Interaction) -> None:
        custom_id = interaction.data.get("custom_id", "") if interaction.data else ""
        if custom_id == "public_giveaway:create":
            await interaction.response.send_modal(PublicGiveawayCreateModal())
            return
        if custom_id == "public_giveaway:help":
            embed = discord.Embed(
                title="🎉 Giveaway Commands",
                color=discord.Color.blurple(),
                description=(
                    "Click **Create Giveaway** to open a form, or use the slash commands:\n"
                    "• `/giveaway create <title> <winners> <duration> [description] [image]`\n"
                    "• `/giveaway list`\n"
                    "• `/giveaway cancel <id>`"
                ),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        await interaction.response.defer()


def make_public_panel_view() -> PublicGiveawayPanelView:
    return PublicGiveawayPanelView()