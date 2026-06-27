import logging

import discord
from discord import Interaction

from ..backend_client import BackendError


log = logging.getLogger(__name__)


ENTER_PREFIX = "giveaway:enter:"
CANCEL_PREFIX = "giveaway:cancel:"
FORCE_END_PREFIX = "giveaway:force_end:"


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
            await interaction.response.edit_message(embed=embed, view=build_giveaway_view(giveaway_id))
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
        try:
            data = await _get_client().get_giveaway(self.giveaway_id)
        except BackendError as exc:
            await interaction.response.send_message(f"Failed to fetch giveaway: `{exc.message}`", ephemeral=True)
            return
        if data is None:
            await interaction.response.send_message("This giveaway no longer exists.", ephemeral=True)
            return
        if int(data.get("creator_id", 0)) != interaction.user.id:
            await interaction.response.send_message(
                "Only the giveaway creator can cancel this giveaway.", ephemeral=True
            )
            return

        from ..commands.admin.giveaway import run_giveaway_force_end

        await interaction.response.defer(ephemeral=True)
        result = await run_giveaway_force_end(
            interaction.client,
            interaction.guild_id,
            self.giveaway_id,
            requested_by=interaction.user.id,
        )
        if not result["ok"]:
            await interaction.followup.send(
                f"Failed at {result['stage']}: `{result['message']}`", ephemeral=True
            )
            return
        await interaction.followup.send(
            f"Giveaway `{self.giveaway_id}` ended and winners selected.",
            ephemeral=True,
        )


def make_enter_view(giveaway_id: str) -> GiveawayEnterView:
    return GiveawayEnterView(giveaway_id)


def make_cancel_view(giveaway_id: str) -> GiveawayCancelView:
    return GiveawayCancelView(giveaway_id)


def enter_custom_id(giveaway_id: str) -> str:
    return f"{ENTER_PREFIX}{giveaway_id}"


def cancel_custom_id(giveaway_id: str) -> str:
    return f"{CANCEL_PREFIX}{giveaway_id}"


def build_giveaway_view(giveaway_id: str) -> discord.ui.View:
    """Combined View (Enter + Cancel Giveaway + End now (Admin)) used for the
    per-giveaway message. Reused on every embed edit so the Force End button
    survives enter/leave toggles.
    """
    combined = discord.ui.View(timeout=None)
    for child in make_enter_view(giveaway_id).children:
        combined.add_item(child)
    for child in make_cancel_view(giveaway_id).children:
        combined.add_item(child)
    for child in make_force_end_view(giveaway_id).children:
        combined.add_item(child)
    return combined


class ForceEndGiveawayView(discord.ui.View):
    """Admin-only 'End now' button rendered in the per-giveaway channel.

    Picks winners immediately via the same `_end_giveaway` path the scheduler
    uses for a normal end, then posts the winners embed and deletes the
    per-giveaway channel.
    """

    def __init__(self, giveaway_id: str):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id
        btn = discord.ui.Button(
            label="End now (Admin)",
            style=discord.ButtonStyle.danger,
            custom_id=f"{FORCE_END_PREFIX}{giveaway_id}",
        )
        btn.callback = self._callback
        self.add_item(btn)

    async def _callback(self, interaction: Interaction) -> None:
        member = interaction.user
        if not isinstance(member, discord.Member) or not (
            member.guild_permissions.administrator or member.guild_permissions.manage_guild
        ):
            await interaction.response.send_message(
                "You need the **Manage Server** permission to end this giveaway immediately.",
                ephemeral=True,
            )
            return

        from ..commands.admin.giveaway import run_giveaway_force_end

        await interaction.response.defer(ephemeral=True)
        result = await run_giveaway_force_end(
            interaction.client,
            interaction.guild_id,
            self.giveaway_id,
            requested_by=interaction.user.id,
        )
        if not result["ok"]:
            await interaction.followup.send(
                f"Failed at {result['stage']}: `{result['message']}`", ephemeral=True
            )
            return
        await interaction.followup.send(
            f"Giveaway `{self.giveaway_id}` ended and winners selected.",
            ephemeral=True,
        )


def make_force_end_view(giveaway_id: str) -> ForceEndGiveawayView:
    return ForceEndGiveawayView(giveaway_id)
