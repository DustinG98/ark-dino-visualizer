import asyncio
import logging

import discord
from discord import Interaction

from ..backend_client import BackendError


log = logging.getLogger(__name__)


ENABLE_BTN_ID = "giveaway_admin:enable"
DISABLE_BTN_ID = "giveaway_admin:disable"
PING_ROLE_BTN_ID = "giveaway_admin:ping_role"
VIEW_BTN_ID = "giveaway_admin:view"
FORCE_CANCEL_BTN_ID = "giveaway_admin:force_cancel"
PUBLIC_PANEL_BTN_ID = "giveaway_admin:public_panel"
CONFIRM_CANCEL_BTN_ID_PREFIX = "giveaway_admin:confirm_cancel:"
CANCEL_SELECT_ID_PREFIX = "giveaway_admin:cancel_select:"


def _get_client():
    from ..bot_commands import _get_client
    return _get_client()


async def _edit_panel_if_possible(interaction: Interaction) -> None:
    """Refresh the panel embed to reflect new state (best-effort, no-op on failure)."""
    try:
        from ..commands.admin.giveaway import run_giveaway_view
        gid = interaction.guild_id
        if gid is None:
            return
        _, embed, _ = await run_giveaway_view(gid)
        if embed is not None and interaction.message is not None:
            await interaction.message.edit(embed=embed)
    except Exception as exc:
        log.debug("panel edit skipped: %s", exc)


async def _auto_dismiss(interaction: Interaction, summary: str, delay: float = 4.0) -> None:
    """Edit the original ephemeral message to drop the View and show a summary, then delete after `delay` seconds."""
    if interaction.message is None:
        return
    try:
        await interaction.edit_original_response(content=summary, view=None, embed=None)
    except (discord.HTTPException, AttributeError) as exc:
        log.debug("auto-dismiss edit failed: %s", exc)
        return

    async def _delete_later() -> None:
        try:
            await asyncio.sleep(delay)
            await interaction.delete_original_response()
        except (discord.HTTPException, AttributeError) as exc:
            log.debug("auto-dismiss delete failed: %s", exc)

    asyncio.create_task(_delete_later())


class EnableReconfigureView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=120)
        self.guild_id = guild_id
        self.selected_channel_id: int | None = None
        self.selected_category_id: int | None = None

        self.channel_select = discord.ui.ChannelSelect(
            channel_types=[discord.ChannelType.text],
            placeholder="Pick the announcement channel…",
            min_values=0,
            max_values=1,
        )
        self.channel_select.callback = self._on_channel_select
        self.add_item(self.channel_select)

        self.category_select = discord.ui.ChannelSelect(
            channel_types=[discord.ChannelType.category],
            placeholder="Pick the per-giveaway category…",
            min_values=0,
            max_values=1,
        )
        self.category_select.callback = self._on_category_select
        self.add_item(self.category_select)

        confirm_btn = discord.ui.Button(
            label="Confirm",
            style=discord.ButtonStyle.success,
            custom_id=f"giveaway_admin:confirm_enable:{guild_id}",
            disabled=True,
        )
        confirm_btn.callback = self._confirm_callback
        self.add_item(confirm_btn)

    async def _on_channel_select(self, interaction: Interaction) -> None:
        values = interaction.data.get("values", []) if interaction.data else []
        self.selected_channel_id = int(values[0]) if values else None
        self._refresh_confirm_state()
        await interaction.response.edit_message(view=self)

    async def _on_category_select(self, interaction: Interaction) -> None:
        values = interaction.data.get("values", []) if interaction.data else []
        self.selected_category_id = int(values[0]) if values else None
        self._refresh_confirm_state()
        await interaction.response.edit_message(view=self)

    def _refresh_confirm_state(self) -> None:
        ready = self.selected_channel_id is not None and self.selected_category_id is not None
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.custom_id and child.custom_id.startswith("giveaway_admin:confirm_enable:"):
                child.disabled = not ready

    async def _confirm_callback(self, interaction: Interaction) -> None:
        if self.selected_channel_id is None or self.selected_category_id is None:
            await interaction.response.send_message("Pick both a channel and a category first.", ephemeral=True)
            return

        from ..commands.admin.giveaway import run_giveaway_enable

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Must be used in a server.", ephemeral=True)
            return
        ch = guild.get_channel(self.selected_channel_id)
        if not isinstance(ch, discord.TextChannel):
            await interaction.response.send_message("The selected channel is no longer available.", ephemeral=True)
            return
        cat = guild.get_channel(self.selected_category_id)
        if not isinstance(cat, discord.CategoryChannel):
            await interaction.response.send_message("The selected category is no longer available.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        result = await run_giveaway_enable(self.guild_id, self.selected_channel_id, self.selected_category_id)
        if not result["ok"]:
            await interaction.followup.send(f"Failed to save {result['field']}: `{result['message']}`", ephemeral=True)
            return
        await interaction.followup.send(
            f"Giveaways enabled. Announcements go in {ch.mention}; per-giveaway and exchange channels will be created in {cat.mention}.",
            ephemeral=True,
        )
        await _auto_dismiss(interaction, "✅ Saved.")


class SetPingRoleView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=120)
        self.guild_id = guild_id
        self.selected_role_id: int | None = None

        select = discord.ui.RoleSelect(
            placeholder="Choose a role to ping…",
            min_values=0,
            max_values=1,
        )
        select.callback = self._select_callback
        self.add_item(select)

        confirm_btn = discord.ui.Button(
            label="Confirm",
            style=discord.ButtonStyle.success,
            custom_id=f"giveaway_admin:confirm_ping:{guild_id}",
            disabled=True,
        )
        confirm_btn.callback = self._confirm_callback
        self.add_item(confirm_btn)

        clear_btn = discord.ui.Button(
            label="Clear ping role",
            style=discord.ButtonStyle.secondary,
            custom_id=f"giveaway_admin:clear_ping:{guild_id}",
        )
        clear_btn.callback = self._clear_callback
        self.add_item(clear_btn)

    async def _select_callback(self, interaction: Interaction) -> None:
        if not interaction.data or "values" not in interaction.data:
            await interaction.response.defer()
            return
        values = interaction.data["values"]
        if values:
            try:
                self.selected_role_id = int(values[0])
            except ValueError:
                self.selected_role_id = None
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.custom_id and child.custom_id.startswith("giveaway_admin:confirm_ping:"):
                child.disabled = self.selected_role_id is None
        await interaction.response.edit_message(view=self)

    async def _confirm_callback(self, interaction: Interaction) -> None:
        if self.selected_role_id is None:
            await interaction.response.send_message("Pick a role from the dropdown first.", ephemeral=True)
            return
        from ..commands.admin.giveaway import run_giveaway_set_ping_role
        result = await run_giveaway_set_ping_role(self.guild_id, self.selected_role_id)
        if not result["ok"]:
            await interaction.response.send_message(f"Failed to save: `{result['message']}`", ephemeral=True)
            return
        await interaction.response.send_message(
            f"<@&{self.selected_role_id}> will be pinged when a new giveaway is created.",
            ephemeral=True,
        )
        await _auto_dismiss(interaction, "✅ Saved.")

    async def _clear_callback(self, interaction: Interaction) -> None:
        from ..commands.admin.giveaway import run_giveaway_set_ping_role
        result = await run_giveaway_set_ping_role(self.guild_id, None)
        if not result["ok"]:
            await interaction.response.send_message(f"Failed to save: `{result['message']}`", ephemeral=True)
            return
        await interaction.response.send_message("Giveaway ping role cleared.", ephemeral=True)
        await _auto_dismiss(interaction, "✅ Cleared.")


class SetPublicPanelView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=120)
        self.guild_id = guild_id
        self.selected_channel_id: int | None = None

        self.channel_select = discord.ui.ChannelSelect(
            channel_types=[discord.ChannelType.text],
            placeholder="Pick the public panel channel…",
            min_values=0,
            max_values=1,
        )
        self.channel_select.callback = self._select_callback
        self.add_item(self.channel_select)

        confirm_btn = discord.ui.Button(
            label="Confirm",
            style=discord.ButtonStyle.success,
            custom_id=f"giveaway_admin:confirm_public_panel:{guild_id}",
            disabled=True,
        )
        confirm_btn.callback = self._confirm_callback
        self.add_item(confirm_btn)

        clear_btn = discord.ui.Button(
            label="Clear",
            style=discord.ButtonStyle.secondary,
            custom_id=f"giveaway_admin:clear_public_panel:{guild_id}",
        )
        clear_btn.callback = self._clear_callback
        self.add_item(clear_btn)

    async def _select_callback(self, interaction: Interaction) -> None:
        values = interaction.data.get("values", []) if interaction.data else []
        self.selected_channel_id = int(values[0]) if values else None
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.custom_id and child.custom_id.startswith("giveaway_admin:confirm_public_panel:"):
                child.disabled = self.selected_channel_id is None
        await interaction.response.edit_message(view=self)

    async def _confirm_callback(self, interaction: Interaction) -> None:
        if self.selected_channel_id is None:
            await interaction.response.send_message("Pick a channel first.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        from ..commands.admin.giveaway import (
            run_giveaway_public_panel_set_channel,
            ensure_giveaways_configured,
        )
        settings = await ensure_giveaways_configured(interaction)
        if settings is None:
            return
        result = await run_giveaway_public_panel_set_channel(self.guild_id, self.selected_channel_id)
        if not result["ok"]:
            await interaction.followup.send(f"Failed to save: `{result['message']}`", ephemeral=True)
            return
        guild = interaction.guild
        ch = guild.get_channel(self.selected_channel_id) if guild else None
        mention = ch.mention if isinstance(ch, discord.TextChannel) else f"<#{self.selected_channel_id}>"
        await interaction.followup.send(
            f"Public panel channel set to {mention}.", ephemeral=True
        )
        await _auto_dismiss(interaction, "✅ Saved.")

    async def _clear_callback(self, interaction: Interaction) -> None:
        from ..commands.admin.giveaway import run_giveaway_public_panel_set_channel
        result = await run_giveaway_public_panel_set_channel(self.guild_id, None)
        if not result["ok"]:
            await interaction.response.send_message(f"Failed to save: `{result['message']}`", ephemeral=True)
            return
        await interaction.response.send_message("Public panel channel cleared.", ephemeral=True)
        await _auto_dismiss(interaction, "✅ Cleared.")


class ForceCancelConfirmView(discord.ui.View):
    def __init__(self, guild_id: int, giveaway_id: str, title: str):
        super().__init__(timeout=60)
        self.guild_id = guild_id
        self.giveaway_id = giveaway_id
        self.title = title

        confirm_btn = discord.ui.Button(
            label="Confirm cancel",
            style=discord.ButtonStyle.danger,
            custom_id=f"{CONFIRM_CANCEL_BTN_ID_PREFIX}{giveaway_id}",
        )
        confirm_btn.callback = self._confirm_callback
        self.add_item(confirm_btn)

    async def _confirm_callback(self, interaction: Interaction) -> None:
        from ..commands.admin.giveaway import run_giveaway_force_cancel
        await interaction.response.defer(ephemeral=True)
        result = await run_giveaway_force_cancel(interaction.client, self.guild_id, self.giveaway_id, interaction.user.id)
        if not result["ok"]:
            await interaction.followup.send(f"Failed at {result['stage']}: `{result['message']}`", ephemeral=True)
            return
        await interaction.followup.send(
            f"Giveaway `{self.giveaway_id}` (**{self.title}**) cancelled.",
            ephemeral=True,
        )


def build_cancel_select(guild_id: int, giveaways: list[dict]) -> discord.ui.Select:
    options: list[discord.SelectOption] = []
    for g in giveaways[:25]:
        gid = str(g.get("id") or g.get("giveaway_id") or "?")
        title_v = str(g.get("title") or "Untitled")[:80]
        entries = len(g.get("entries") or [])
        end_at = g.get("end_at_iso") or g.get("end_at") or "?"
        options.append(
            discord.SelectOption(
                label=title_v[:100],
                description=f"id={gid} • entries={entries} • ends {end_at}"[:100],
                value=gid,
            )
        )
    select = discord.ui.Select(
        placeholder="Pick a giveaway to cancel…",
        options=options,
        min_values=1,
        max_values=1,
        custom_id=f"{CANCEL_SELECT_ID_PREFIX}{guild_id}",
    )
    return select


class AdminGiveawayPanelView(discord.ui.View):
    """Persistent panel with the 5 admin actions. Buttons only; modals/selects
    are dispatched to ephemeral follow-ups. Re-registered on bot start.
    """

    def __init__(self, guild_id: int):
        super().__init__(timeout=None)
        self.guild_id = guild_id

        self.add_item(
            discord.ui.Button(
                label="Enable / Reconfigure",
                style=discord.ButtonStyle.primary,
                custom_id=f"{ENABLE_BTN_ID}:{guild_id}",
            )
        )
        self.add_item(
            discord.ui.Button(
                label="Disable",
                style=discord.ButtonStyle.secondary,
                custom_id=f"{DISABLE_BTN_ID}:{guild_id}",
            )
        )
        self.add_item(
            discord.ui.Button(
                label="Set Ping Role",
                style=discord.ButtonStyle.secondary,
                custom_id=f"{PING_ROLE_BTN_ID}:{guild_id}",
            )
        )
        self.add_item(
            discord.ui.Button(
                label="View Settings",
                style=discord.ButtonStyle.secondary,
                custom_id=f"{VIEW_BTN_ID}:{guild_id}",
            )
        )
        self.add_item(
            discord.ui.Button(
                label="Set Public Panel Channel",
                style=discord.ButtonStyle.secondary,
                custom_id=f"{PUBLIC_PANEL_BTN_ID}:{guild_id}",
            )
        )
        self.add_item(
            discord.ui.Button(
                label="Force-Cancel a Giveaway",
                style=discord.ButtonStyle.danger,
                custom_id=f"{FORCE_CANCEL_BTN_ID}:{guild_id}",
            )
        )

        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.callback = self._on_button

    async def interaction_check(self, interaction: Interaction) -> bool:
        if interaction.guild is None:
            return False
        member = interaction.user
        if not isinstance(member, discord.Member):
            return False
        perms = member.guild_permissions
        if perms.administrator or perms.manage_guild:
            return True
        from discord import app_commands
        raise app_commands.CheckFailure("You need the **Manage Server** permission to use this panel.")

    async def _on_button(self, interaction: Interaction) -> None:
        custom_id = interaction.data.get("custom_id", "") if interaction.data else ""
        if custom_id.startswith(ENABLE_BTN_ID + ":"):
            await self._on_enable(interaction)
        elif custom_id.startswith(DISABLE_BTN_ID + ":"):
            await self._on_disable(interaction)
        elif custom_id.startswith(PING_ROLE_BTN_ID + ":"):
            await self._on_ping_role(interaction)
        elif custom_id.startswith(VIEW_BTN_ID + ":"):
            await self._on_view(interaction)
        elif custom_id.startswith(PUBLIC_PANEL_BTN_ID + ":"):
            await self._on_public_panel(interaction)
        elif custom_id.startswith(FORCE_CANCEL_BTN_ID + ":"):
            await self._on_force_cancel(interaction)
        else:
            await interaction.response.defer()

    async def _on_enable(self, interaction: Interaction) -> None:
        view = EnableReconfigureView(self.guild_id)
        await interaction.response.send_message(
            "Pick the announcement channel and the per-giveaway category, then click Confirm.",
            view=view,
            ephemeral=True,
        )

    async def _on_disable(self, interaction: Interaction) -> None:
        from ..commands.admin.giveaway import run_giveaway_disable
        result = await run_giveaway_disable(self.guild_id)
        if not result["ok"]:
            await interaction.response.send_message(f"Failed: `{result['message']}`", ephemeral=True)
            return
        await interaction.response.send_message("Giveaways disabled.", ephemeral=True)

    async def _on_ping_role(self, interaction: Interaction) -> None:
        view = SetPingRoleView(self.guild_id)
        await interaction.response.send_message(
            "Pick a role to ping when a new giveaway opens.",
            view=view,
            ephemeral=True,
        )

    async def _on_view(self, interaction: Interaction) -> None:
        from ..commands.admin.giveaway import run_giveaway_view
        _, embed, err = await run_giveaway_view(self.guild_id)
        if err is not None:
            await interaction.response.send_message(err, ephemeral=True)
            return
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _on_public_panel(self, interaction: Interaction) -> None:
        view = SetPublicPanelView(self.guild_id)
        await interaction.response.send_message(
            "Pick the channel where the public giveaway panel should live, then click Confirm.",
            view=view,
            ephemeral=True,
        )

    async def _on_force_cancel(self, interaction: Interaction) -> None:
        backend = _get_client()
        try:
            giveaways = await backend.list_active_giveaways(self.guild_id)
        except BackendError as exc:
            await interaction.response.send_message(f"Failed to list: `{exc.message}`", ephemeral=True)
            return
        if not giveaways:
            await interaction.response.send_message("No active giveaways in this server.", ephemeral=True)
            return

        select = build_cancel_select(self.guild_id, giveaways)
        confirm_btn = _ForceCancelConfirmPlaceholder(self.guild_id)

        async def on_select(select_interaction: Interaction) -> None:
            if not select_interaction.data or "values" not in select_interaction.data:
                await select_interaction.response.defer()
                return
            values = select_interaction.data["values"]
            if not values:
                await select_interaction.response.defer()
                return
            chosen_id = values[0]
            chosen = next((g for g in giveaways if str(g.get("id") or g.get("giveaway_id")) == chosen_id), None)
            chosen_title = str(chosen.get("title", "Untitled")) if chosen else chosen_id
            confirm_view = ForceCancelConfirmView(self.guild_id, chosen_id, chosen_title)
            await select_interaction.response.send_message(
                f"Cancel giveaway **{chosen_title}** (`{chosen_id}`)? This cannot be undone.",
                view=confirm_view,
                ephemeral=True,
            )

        select.callback = on_select

        view = discord.ui.View(timeout=120)
        view.add_item(select)
        view.add_item(confirm_btn)

        await interaction.response.send_message(
            "Select the giveaway to force-cancel:",
            view=view,
            ephemeral=True,
        )

class _ForceCancelConfirmPlaceholder(discord.ui.Button):
    """Hidden placeholder so the Select menu can sit on its own row cleanly.
    Not user-clickable; replaced by a per-giveaway Confirm view on selection.
    """

    def __init__(self, guild_id: int):
        super().__init__(
            label="Pick a giveaway above",
            style=discord.ButtonStyle.secondary,
            custom_id=f"giveaway_admin:noop:{guild_id}",
            disabled=True,
            row=4,
        )

    async def callback(self, interaction: Interaction) -> None:
        await interaction.response.defer()


def make_admin_panel_view(guild_id: int) -> AdminGiveawayPanelView:
    return AdminGiveawayPanelView(guild_id)
