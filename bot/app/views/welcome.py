import discord
from discord import Interaction

from ..backend_client import BackendError


def _get_client():
    from ..bot_commands import _get_client
    return _get_client()


class WelcomeMessageModal(discord.ui.Modal):
    def __init__(self, current_message: str):
        super().__init__(title="Set Welcome Message")
        self.message_input = discord.ui.TextInput(
            label="Welcome Message",
            placeholder="Welcome to {server.name}, {member.mention}!",
            default=current_message or "",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=2000,
        )
        self.add_item(self.message_input)

    async def on_submit(self, interaction: Interaction) -> None:
        guild_id = interaction.guild_id
        if guild_id is None:
            return

        try:
            current = await _get_client().get_welcome_settings(guild_id)
        except BackendError as exc:
            await interaction.response.send_message(f"Failed to fetch settings: `{exc.message}`", ephemeral=True)
            return

        if current is None:
            await interaction.response.send_message(
                "No welcome channel set yet. Use `/forge admin welcome-set-channel` first.",
                ephemeral=True,
            )
            return

        try:
            enabled = current.get("enabled", False)
            await _get_client().set_welcome_settings(guild_id, current["channel_id"], self.message_input.value, enabled=enabled)
        except BackendError as exc:
            await interaction.response.send_message(f"Failed to save: `{exc.message}`", ephemeral=True)
            return

        await interaction.response.send_message("Welcome message updated.", ephemeral=True)


class SetMessageView(discord.ui.View):
    def __init__(self, current_message: str, modal_cls: type[discord.ui.Modal]):
        super().__init__(timeout=60)
        self.current_message = current_message
        self._modal_cls = modal_cls

    @discord.ui.button(label="Edit Message", style=discord.ButtonStyle.primary)
    async def edit_message(self, interaction: Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(self._modal_cls(self.current_message))
        self.stop()
