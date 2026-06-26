import asyncio
import logging
import re
import regex

import discord
from discord import Interaction


log = logging.getLogger(__name__)


def _safe_emoji(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    if len(value) > 64:
        return None
    if re.fullmatch(r"\d{15,21}", value):
        return None
    if len(regex.findall(r"\X", value, regex.UNICODE)) > 1:
        return None
    return value


SET_PUBLIC_CHANNEL_BTN = "rp_admin:set_public_channel"
OPEN_PANEL_BTN = "rp_admin:open_panel"
ADD_ROLE_BTN = "rp_admin:add_role"
VIEW_ROLES_BTN = "rp_admin:view_roles"
DISABLE_BTN = "rp_admin:disable"
SET_CHANNEL_CONFIRM_BTN_PREFIX = "rp_admin:confirm_channel:"
SET_CHANNEL_CLEAR_BTN_PREFIX = "rp_admin:clear_channel:"


def _get_client():
    from ..bot_commands import _get_client
    return _get_client()


async def _auto_dismiss(interaction: Interaction, summary: str, delay: float = 4.0) -> None:
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


async def _silent_delete(interaction: Interaction, delay: float = 0.5) -> None:
    if interaction.message is None:
        return

    async def _delete_later() -> None:
        try:
            await asyncio.sleep(delay)
            await interaction.delete_original_response()
        except (discord.HTTPException, AttributeError) as exc:
            log.debug("silent delete failed: %s", exc)

    asyncio.create_task(_delete_later())


async def _auto_delete_message(message: discord.Message | None, delay: float = 4.0) -> None:
    if message is None:
        return

    async def _delete_later() -> None:
        try:
            await asyncio.sleep(delay)
            await message.delete()
        except (discord.HTTPException, AttributeError) as exc:
            log.debug("auto-delete message failed: %s", exc)

    asyncio.create_task(_delete_later())


def _build_admin_embed(guild_id: int, roles: list[dict], public_channel_id: int | None) -> discord.Embed:
    embed = discord.Embed(
        title="🎭 Role Picker — Admin",
        color=discord.Color.blurple(),
        description="Manage the self-assign role picker for this server.",
    )
    role_count = len(roles)
    embed.add_field(
        name="Configured Roles",
        value=f"{role_count}/25",
        inline=True,
    )
    ch_mention = f"<#{public_channel_id}>" if public_channel_id else "_not set_"
    embed.add_field(
        name="Public Panel Channel",
        value=ch_mention,
        inline=True,
    )
    embed.add_field(
        name="Available Actions",
        value=(
            "• **Set Public Channel** — pick the channel for the public panel\n"
            "• **Open Public Panel** — post/update the public panel in the configured channel\n"
            "• **Add Role** — add a new toggle role (max 25)\n"
            "• **View Roles** — see configured roles with Edit/Remove\n"
            "• **Disable** — clear the public panel"
        ),
        inline=False,
    )
    embed.set_footer(text="This panel auto-recovers if the message is deleted.")
    return embed


# ─── Modals ────────────────────────────────────────────────────────────────────

class AddRoleModal(discord.ui.Modal):
    def __init__(self, guild_id: int, original_interaction: Interaction | None = None):
        super().__init__(title="Add a role", timeout=300)
        self.guild_id = guild_id
        self._original_interaction = original_interaction
        self.add_item(
            discord.ui.TextInput(
                custom_id="rp_add:label",
                label="Button label",
                placeholder="e.g. VIP, Notifications, Gamer",
                required=True,
                max_length=80,
            )
        )
        self.add_item(
            discord.ui.TextInput(
                custom_id="rp_add:emoji",
                label="Emoji (optional)",
                placeholder="e.g. 😀 or for custom emojis: name:id",
                required=False,
                max_length=64,
            )
        )
        self.add_item(
            discord.ui.TextInput(
                custom_id="rp_add:description",
                label="Description (optional, max 100 chars)",
                placeholder="Short description shown in the panel",
                required=False,
                max_length=100,
            )
        )
        self.add_item(
            discord.ui.Label(
                text="Role to assign",
                component=discord.ui.RoleSelect(
                    custom_id="rp_add:role",
                    placeholder="Pick the role to assign…",
                    min_values=1,
                    max_values=1,
                    required=True,
                ),
            )
        )

    @property
    def label(self) -> str:
        return str(self.children[0].value or "").strip()

    @property
    def emoji(self) -> str | None:
        v = self.children[1].value
        return _safe_emoji(str(v).strip() or None)

    @property
    def description(self) -> str | None:
        v = self.children[2].value
        return str(v).strip() or None

    @property
    def role_id(self) -> int | None:
        label_item = self.children[3]
        select: discord.ui.RoleSelect = label_item.component
        values = select.values
        if not values:
            return None
        role = values[0]
        return role.id if isinstance(role, discord.Role) else None

    async def on_submit(self, interaction: Interaction) -> None:
        if not self.label:
            await interaction.response.send_message("Button label cannot be empty.", ephemeral=True)
            return
        raw_emoji = str(self.children[1].value or "").strip()
        if raw_emoji and _safe_emoji(raw_emoji) is None:
            await interaction.response.send_message(
                "Emoji must be a single unicode emoji (e.g. 😀) or a Discord custom emoji in `name:id` format. Multiple emojis are not supported.",
                ephemeral=True,
            )
            return
        if not self.role_id:
            await interaction.response.send_message("You must pick a role.", ephemeral=True)
            return

        from ..commands.admin.role_picker import run_rp_add_role
        await interaction.response.defer(ephemeral=True)
        ok, message = await run_rp_add_role(
            self.guild_id,
            role_id=self.role_id,
            label=self.label,
            emoji=self.emoji,
            description=self.description,
        )
        if not ok:
            msg = await interaction.followup.send(message, ephemeral=True)
            asyncio.create_task(_auto_delete_message(msg))
            return
        if self._original_interaction and self._original_interaction.message:
            asyncio.create_task(_silent_delete(self._original_interaction))
        msg = await interaction.followup.send(message, ephemeral=True)
        asyncio.create_task(_auto_delete_message(msg))


class EditRoleModal(discord.ui.Modal):
    def __init__(self, guild_id: int, position: int, current: dict, original_interaction: Interaction | None = None):
        super().__init__(title="Edit role", timeout=300)
        self.guild_id = guild_id
        self.position = position
        self.current = current
        self._original_interaction = original_interaction
        self.add_item(
            discord.ui.TextInput(
                custom_id="rp_edit:label",
                label="Button label",
                required=True,
                max_length=80,
                default=current.get("label", ""),
            )
        )
        self.add_item(
            discord.ui.TextInput(
                custom_id="rp_edit:emoji",
                label="Emoji (optional)",
                required=False,
                max_length=64,
                default=current.get("emoji") or "",
            )
        )
        self.add_item(
            discord.ui.TextInput(
                custom_id="rp_edit:description",
                label="Description (optional)",
                required=False,
                max_length=100,
                default=current.get("description") or "",
            )
        )
        self.add_item(
            discord.ui.Label(
                text="Role to assign",
                component=discord.ui.RoleSelect(
                    custom_id="rp_edit:role",
                    placeholder="Pick a different role…",
                    min_values=1,
                    max_values=1,
                    required=True,
                    default_values=[discord.Object(id=current["role_id"])] if current.get("role_id") else [],
                ),
            )
        )

    @property
    def label(self) -> str:
        return str(self.children[0].value or "").strip()

    @property
    def emoji(self) -> str | None:
        v = self.children[1].value
        return _safe_emoji(str(v).strip() or None)

    @property
    def description(self) -> str | None:
        v = self.children[2].value
        return str(v).strip() or None

    @property
    def role_id(self) -> int | None:
        label_item = self.children[3]
        select: discord.ui.RoleSelect = label_item.component
        values = select.values
        if not values:
            return None
        role = values[0]
        return role.id if isinstance(role, discord.Role) else None

    async def on_submit(self, interaction: Interaction) -> None:
        if not self.label:
            await interaction.response.send_message("Button label cannot be empty.", ephemeral=True)
            return
        raw_emoji = str(self.children[1].value or "").strip()
        if raw_emoji and _safe_emoji(raw_emoji) is None:
            await interaction.response.send_message(
                "Emoji must be a single unicode emoji (e.g. 😀) or a Discord custom emoji in `name:id` format. Multiple emojis are not supported.",
                ephemeral=True,
            )
            return
        if not self.role_id:
            await interaction.response.send_message("You must pick a role.", ephemeral=True)
            return

        from ..commands.admin.role_picker import run_rp_edit_role
        await interaction.response.defer(ephemeral=True)
        ok, message = await run_rp_edit_role(
            self.guild_id,
            self.position,
            label=self.label,
            emoji=self.emoji,
            description=self.description,
            role_id=self.role_id,
        )
        if not ok:
            msg = await interaction.followup.send(message, ephemeral=True)
            asyncio.create_task(_auto_delete_message(msg))
            return
        if self._original_interaction and self._original_interaction.message:
            asyncio.create_task(_silent_delete(self._original_interaction))
        msg = await interaction.followup.send(message, ephemeral=True)
        asyncio.create_task(_auto_delete_message(msg))


# ─── Set Public Channel View ───────────────────────────────────────────────────

class SetPublicChannelView(discord.ui.View):
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
        self.channel_select.callback = self._on_select
        self.add_item(self.channel_select)

        confirm_btn = discord.ui.Button(
            label="Confirm",
            style=discord.ButtonStyle.success,
            custom_id=f"{SET_CHANNEL_CONFIRM_BTN_PREFIX}{guild_id}",
            disabled=True,
        )
        confirm_btn.callback = self._on_confirm
        self.add_item(confirm_btn)

        clear_btn = discord.ui.Button(
            label="Clear",
            style=discord.ButtonStyle.secondary,
            custom_id=f"{SET_CHANNEL_CLEAR_BTN_PREFIX}{guild_id}",
        )
        clear_btn.callback = self._on_clear
        self.add_item(clear_btn)

    async def _on_select(self, interaction: Interaction) -> None:
        values = interaction.data.get("values", []) if interaction.data else []
        self.selected_channel_id = int(values[0]) if values else None
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.custom_id and child.custom_id.startswith(SET_CHANNEL_CONFIRM_BTN_PREFIX):
                child.disabled = self.selected_channel_id is None
        await interaction.response.edit_message(view=self)

    async def _on_confirm(self, interaction: Interaction) -> None:
        if self.selected_channel_id is None:
            await interaction.response.send_message("Pick a channel first.", ephemeral=True)
            return

        from ..commands.admin.role_picker import run_rp_set_public_channel
        result = await run_rp_set_public_channel(self.guild_id, self.selected_channel_id)
        if not result["ok"]:
            await interaction.response.send_message(f"Failed: `{result.get('message', 'unknown')}`", ephemeral=True)
            return
        guild = interaction.guild
        ch = guild.get_channel(self.selected_channel_id) if guild else None
        mention = ch.mention if isinstance(ch, discord.TextChannel) else f"<#{self.selected_channel_id}>"
        await interaction.response.send_message(
            f"Public panel channel set to {mention}.",
            ephemeral=True,
        )
        await _auto_dismiss(interaction, "✅ Saved.")

    async def _on_clear(self, interaction: Interaction) -> None:
        from ..commands.admin.role_picker import run_rp_set_public_channel
        result = await run_rp_set_public_channel(self.guild_id, None)
        if not result["ok"]:
            await interaction.response.send_message(f"Failed: `{result.get('message', 'unknown')}`", ephemeral=True)
            return
        await interaction.response.send_message("Public panel channel cleared.", ephemeral=True)
        await _auto_dismiss(interaction, "✅ Cleared.")


# ─── View Roles (ephemeral) ─────────────────────────────────────────────────────
class ViewRolesView(discord.ui.View):
    def __init__(self, guild_id: int, roles: list[dict]):
        super().__init__(timeout=120)
        self.guild_id = guild_id
        self.roles = {r["position"]: r for r in roles}
        self._selected: str | None = None

        self.select = self._build_select()
        self.add_item(self.select)

        self.edit_btn = discord.ui.Button(
            label="Edit Selected",
            style=discord.ButtonStyle.secondary,
            custom_id="rp_view:edit",
            disabled=True,
        )
        self.edit_btn.callback = self._on_edit
        self.add_item(self.edit_btn)

        self.remove_btn = discord.ui.Button(
            label="Remove Selected",
            style=discord.ButtonStyle.danger,
            custom_id="rp_view:remove",
            disabled=True,
        )
        self.remove_btn.callback = self._on_remove
        self.add_item(self.remove_btn)

    def _build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="Role Picker — Configured Roles",
            color=discord.Color.blurple(),
        )
        if not self.roles:
            embed.description = "_No roles configured yet._"
        else:
            lines = []
            for r in sorted(self.roles.values(), key=lambda x: x["position"]):
                emoji_str = f"{_safe_emoji(r.get('emoji'))} " if r.get("emoji") else ""
                desc_str = f" — {r['description']}" if r.get("description") else ""
                lines.append(f"`{r['position']}` {emoji_str}**{r['label']}**{desc_str}")
            embed.description = "\n".join(lines)
        embed.set_footer(text=f"{len(self.roles)}/25 roles configured")
        return embed

    def _build_select(self) -> discord.ui.Select:
        # Discord requires at least one option — use a disabled placeholder when empty.
        if not self.roles:
            select = discord.ui.Select(
                placeholder="No roles configured.",
                options=[discord.SelectOption(label="—", value="__none__")],
                min_values=0,
                max_values=1,
                disabled=True,
                custom_id="rp_view:role_select",
            )
            select.callback = self._on_select
            return select

        options = [
            discord.SelectOption(
                label=r["label"][:100],
                description=(r.get("description") or "")[:100],
                value=str(r["position"]),
                emoji=_safe_emoji(r.get("emoji")),
                default=str(r["position"]) == self._selected,
            )
            for r in sorted(self.roles.values(), key=lambda x: x["position"])
        ]
        select = discord.ui.Select(
            placeholder="Select a role to edit or remove…",
            options=options,
            min_values=0,
            max_values=1,
            custom_id="rp_view:role_select",
        )
        select.callback = self._on_select
        return select

    async def _refresh_message(self, interaction: Interaction) -> None:
        """Rebuild the select (to persist the active selection) then re-render the message."""
        self.remove_item(self.select)
        self.select = self._build_select()
        self.add_item(self.select)
        await interaction.response.edit_message(
            embed=self._build_embed(),
            view=self,
        )

    async def _on_select(self, interaction: Interaction) -> None:
        values = interaction.data.get("values", []) if interaction.data else []
        self._selected = values[0] if values else None

        self.edit_btn.disabled = self._selected is None
        self.remove_btn.disabled = self._selected is None

        # Edit the original message to reflect updated button states.
        # No extra ephemeral noise — the button states themselves are the feedback.
        await self._refresh_message(interaction)

    async def _on_edit(self, interaction: Interaction) -> None:
        if self._selected is None:
            await interaction.response.defer()
            return
        current = self.roles.get(int(self._selected))
        if current is None:
            await interaction.response.defer()
            return
        modal = EditRoleModal(self.guild_id, int(self._selected), current, original_interaction=interaction)
        await interaction.response.send_modal(modal)

    async def _on_remove(self, interaction: Interaction) -> None:
        if self._selected is None:
            await interaction.response.defer()
            return
        current = self.roles.get(int(self._selected))
        if current is None:
            await interaction.response.defer()
            return
        confirm_view = ConfirmRemoveView(self.guild_id, int(self._selected), current["label"], original_interaction=interaction)
        await interaction.response.send_message(
            f"Remove **{current['label']}** from the picker? This cannot be undone.",
            view=confirm_view,
            ephemeral=True,
        )

class ConfirmRemoveView(discord.ui.View):
    def __init__(self, guild_id: int, position: int, label: str, original_interaction: Interaction | None = None):
        super().__init__(timeout=60)
        self.guild_id = guild_id
        self.position = position
        self.label = label
        self._original_interaction = original_interaction

        confirm_btn = discord.ui.Button(
            label="Confirm Remove",
            style=discord.ButtonStyle.danger,
            custom_id="rp_confirm_remove",
        )
        confirm_btn.callback = self._on_confirm
        self.add_item(confirm_btn)

        cancel_btn = discord.ui.Button(
            label="Cancel",
            style=discord.ButtonStyle.secondary,
            custom_id="rp_cancel_remove",
        )
        cancel_btn.callback = self._on_cancel
        self.add_item(cancel_btn)

    async def _on_confirm(self, interaction: Interaction) -> None:
        from ..commands.admin.role_picker import run_rp_remove_role
        await interaction.response.defer(ephemeral=True)
        ok, message = await run_rp_remove_role(self.guild_id, self.position)
        if not ok:
            msg = await interaction.followup.send(message, ephemeral=True)
            asyncio.create_task(_auto_delete_message(msg))
            return
        if self._original_interaction and self._original_interaction.message:
            asyncio.create_task(_silent_delete(self._original_interaction))
        msg = await interaction.followup.send(f"Removed **{self.label}**.", ephemeral=True)
        asyncio.create_task(_auto_delete_message(msg))

    async def _on_cancel(self, interaction: Interaction) -> None:
        await _silent_delete(interaction)


# ─── Main Admin View ────────────────────────────────────────────────────────────

class RolePickerAdminView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=None)
        self.guild_id = guild_id

        self.add_item(
            discord.ui.Button(
                label="Set Public Channel",
                style=discord.ButtonStyle.primary,
                custom_id=f"{SET_PUBLIC_CHANNEL_BTN}:{guild_id}",
            )
        )
        self.add_item(
            discord.ui.Button(
                label="Open Public Panel",
                style=discord.ButtonStyle.primary,
                custom_id=f"{OPEN_PANEL_BTN}:{guild_id}",
            )
        )
        self.add_item(
            discord.ui.Button(
                label="Add Role",
                style=discord.ButtonStyle.success,
                custom_id=f"{ADD_ROLE_BTN}:{guild_id}",
            )
        )
        self.add_item(
            discord.ui.Button(
                label="View Roles",
                style=discord.ButtonStyle.secondary,
                custom_id=f"{VIEW_ROLES_BTN}:{guild_id}",
            )
        )
        self.add_item(
            discord.ui.Button(
                label="Disable",
                style=discord.ButtonStyle.danger,
                custom_id=f"{DISABLE_BTN}:{guild_id}",
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

        if custom_id.startswith(f"{SET_PUBLIC_CHANNEL_BTN}:"):
            await self._on_set_public_channel(interaction)
        elif custom_id.startswith(f"{OPEN_PANEL_BTN}:"):
            await self._on_open_panel(interaction)
        elif custom_id.startswith(f"{ADD_ROLE_BTN}:"):
            await self._on_add_role(interaction)
        elif custom_id.startswith(f"{VIEW_ROLES_BTN}:"):
            await self._on_view_roles(interaction)
        elif custom_id.startswith(f"{DISABLE_BTN}:"):
            await self._on_disable(interaction)
        else:
            await interaction.response.defer()

    async def _on_set_public_channel(self, interaction: Interaction) -> None:
        view = SetPublicChannelView(self.guild_id)
        await interaction.response.send_message(
            "Pick the channel for the public role picker panel, then click Confirm.",
            view=view,
            ephemeral=True,
        )

    async def _on_open_panel(self, interaction: Interaction) -> None:
        from ..commands.admin.role_picker import post_public_panel
        backend = _get_client()
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Must be used in a server.", ephemeral=True)
            return
        settings = None
        try:
            settings = await backend.get_role_picker_settings(guild.id)
        except Exception:
            pass
        channel_id = settings.get("public_panel_channel_id") if settings else None
        if not channel_id:
            await interaction.response.send_message(
                "No public panel channel set. Use **Set Public Channel** first.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        msg_id = await post_public_panel(interaction.client, guild, channel_id)
        if msg_id is None:
            await interaction.followup.send(
                "Could not post the public panel. Check that I have View + Send permissions in that channel.",
                ephemeral=True,
            )
            return
        try:
            await backend.update_role_picker_public_panel_message(guild.id, msg_id)
        except Exception as exc:
            log.warning("failed to persist public panel message id: %s", exc)
        from ..role_picker_scheduler import register_and_persist_public_panel_message
        await register_and_persist_public_panel_message(backend, guild.id, channel_id, msg_id)
        await interaction.followup.send("Public panel posted.", ephemeral=True)

    async def _on_add_role(self, interaction: Interaction) -> None:
        modal = AddRoleModal(self.guild_id)
        await interaction.response.send_modal(modal)

    async def _on_view_roles(self, interaction: Interaction) -> None:
        from ..commands.admin.role_picker import run_rp_view_roles
        roles, err = await run_rp_view_roles(self.guild_id)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        view = ViewRolesView(self.guild_id, roles)
        await interaction.response.send_message(
            embed=view._build_embed(),
            view=view,
            ephemeral=True,
        )

    async def _on_disable(self, interaction: Interaction) -> None:
        from ..commands.admin.role_picker import run_rp_disable
        await interaction.response.defer(ephemeral=True)
        ok, message = await run_rp_disable(interaction.client, self.guild_id)
        if not ok:
            await interaction.followup.send(message, ephemeral=True)
            return
        await interaction.followup.send(message, ephemeral=True)


def make_admin_view(guild_id: int) -> RolePickerAdminView:
    return RolePickerAdminView(guild_id)
