import logging

import discord
from discord import Interaction

from ..backend_client import BackendError


log = logging.getLogger(__name__)


ENTER_PREFIX = "giveaway:enter:"
CANCEL_PREFIX = "giveaway:cancel:"


def _get_client():
    from ..bot_commands import _get_client
    return _get_client()


def _set_entry_count(embed: discord.Embed, count: int) -> None:
    for i, field in enumerate(embed.fields):
        if field.name.lower().startswith("entries"):
            embed.set_field_at(i, name="Entries", value=str(count), inline=field.inline)
            return
    embed.add_field(name="Entries", value=str(count), inline=False)


class GiveawayEnterView(discord.ui.View):
    def __init__(self, giveaway_id: str):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id

        enter_btn = discord.ui.Button(
            label="Enter",
            style=discord.ButtonStyle.success,
            custom_id=f"{ENTER_PREFIX}{giveaway_id}",
        )
        enter_btn.callback = self._enter_callback
        self.add_item(enter_btn)

    async def _enter_callback(self, interaction: Interaction) -> None:
        giveaway_id = self.giveaway_id
        user_id = interaction.user.id

        try:
            current = await _get_client().get_giveaway(giveaway_id)
        except BackendError as exc:
            await interaction.response.send_message(f"Failed to fetch giveaway: `{exc.message}`", ephemeral=True)
            return

        if current is None:
            await interaction.response.send_message("This giveaway no longer exists.", ephemeral=True)
            return

        status = current.get("status", "active")
        if status != "active":
            await interaction.response.send_message("This giveaway has ended.", ephemeral=True)
            return

        entries: list[int] = list(current.get("entries") or [])
        if user_id in entries:
            try:
                await _get_client().leave_giveaway(giveaway_id, user_id)
            except BackendError as exc:
                await interaction.response.send_message(f"Failed to leave: `{exc.message}`", ephemeral=True)
                return
            entries = [e for e in entries if e != user_id]
            joined = False
        else:
            try:
                await _get_client().enter_giveaway(giveaway_id, user_id)
            except BackendError as exc:
                await interaction.response.send_message(f"Failed to enter: `{exc.message}`", ephemeral=True)
                return
            entries.append(user_id)
            joined = True

        embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
        _set_entry_count(embed, len(entries))

        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.HTTPException as exc:
            log.warning("failed to edit giveaway embed: %s", exc)
            await interaction.response.send_message(
                ("You've entered the giveaway." if joined else "You've left the giveaway."),
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            ("You've entered the giveaway." if joined else "You've left the giveaway."),
            ephemeral=True,
        )


class GiveawayCancelView(discord.ui.View):
    def __init__(self, giveaway_id: str):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id

        cancel_btn = discord.ui.Button(
            label="Cancel Giveaway",
            style=discord.ButtonStyle.danger,
            custom_id=f"{CANCEL_PREFIX}{giveaway_id}",
        )
        cancel_btn.callback = self._cancel_callback
        self.add_item(cancel_btn)

    async def _cancel_callback(self, interaction: Interaction) -> None:
        from ..giveaway_scheduler import cancel_giveaway_now

        await interaction.response.defer(ephemeral=True)
        try:
            await cancel_giveaway_now(interaction.client, self.giveaway_id, requested_by=interaction.user.id)
        except Exception as exc:
            log.warning("cancel giveaway failed for %s: %s", self.giveaway_id, exc)
            await interaction.followup.send(f"Failed to cancel: `{exc}`", ephemeral=True)
            return
        await interaction.followup.send("Giveaway cancelled.", ephemeral=True)


def make_enter_view(giveaway_id: str) -> GiveawayEnterView:
    return GiveawayEnterView(giveaway_id)


def make_cancel_view(giveaway_id: str) -> GiveawayCancelView:
    return GiveawayCancelView(giveaway_id)


def enter_custom_id(giveaway_id: str) -> str:
    return f"{ENTER_PREFIX}{giveaway_id}"


def cancel_custom_id(giveaway_id: str) -> str:
    return f"{CANCEL_PREFIX}{giveaway_id}"
