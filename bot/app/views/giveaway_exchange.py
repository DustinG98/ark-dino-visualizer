import logging
import re

import discord
from discord import Interaction

from ..backend_client import BackendError


log = logging.getLogger(__name__)


CLAIM_PREFIX = "giveaway:claim:"
WINNER_CONFIRM_PREFIX = "giveaway:winner_confirm:"
CREATOR_CONFIRM_PREFIX = "giveaway:creator_confirm:"


def claim_custom_id(giveaway_id: str, winner_id: int) -> str:
    return f"{CLAIM_PREFIX}{giveaway_id}:{winner_id}"


def _parse_claim_winner_id(custom_id: str, giveaway_id: str) -> int | None:
    prefix = f"{CLAIM_PREFIX}{giveaway_id}:"
    if not custom_id.startswith(prefix):
        return None
    raw = custom_id[len(prefix):]
    try:
        return int(raw)
    except ValueError:
        return None


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(text: str, max_len: int = 80) -> str:
    s = _SLUG_RE.sub("-", text.lower()).strip("-")
    return s[:max_len] or "giveaway"


def _get_client():
    from ..bot_commands import _get_client
    return _get_client()


async def _find_existing_exchange(backend, giveaway_id: str, winner_id: int) -> dict | None:
    try:
        return await backend.find_exchange_for_winner(giveaway_id, winner_id)
    except BackendError as exc:
        log.warning("find_exchange_for_winner failed: %s", exc)
        return None


class ClaimView(discord.ui.View):
    def __init__(
        self,
        giveaway_id: str,
        winner_ids: list[int],
        winner_labels: dict[int, str] | None = None,
    ):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id
        self.winner_ids = [int(w) for w in winner_ids]
        self._labels = winner_labels or {}
        for winner_id in self.winner_ids:
            label = self._format_label(winner_id)
            btn = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.primary,
                custom_id=claim_custom_id(giveaway_id, winner_id),
            )
            btn.callback = self._make_callback(winner_id)
            self.add_item(btn)

    def _format_label(self, winner_id: int) -> str:
        name = self._labels.get(winner_id)
        if name:
            return f"Claim (for @{name})"[:80]
        return f"Claim (for {winner_id})"[:80]

    def _make_callback(self, winner_id: int):
        async def _callback(interaction: Interaction) -> None:
            await _handle_claim(interaction, self.giveaway_id, allowed_winner_id=winner_id)
        return _callback


async def _handle_claim(interaction: Interaction, giveaway_id: str, allowed_winner_id: int | None = None) -> None:
    backend = _get_client()
    try:
        data = await backend.get_giveaway(giveaway_id)
    except BackendError as exc:
        await interaction.response.send_message(f"Failed to fetch giveaway: `{exc.message}`", ephemeral=True)
        return

    if data is None:
        await interaction.response.send_message("This giveaway no longer exists.", ephemeral=True)
        return
    if data.get("status") != "ended":
        await interaction.response.send_message("This giveaway hasn't ended yet.", ephemeral=True)
        return

    winners = [int(w) for w in (data.get("winner_ids") or [])]
    if allowed_winner_id is not None:
        if interaction.user.id != allowed_winner_id:
            await interaction.response.send_message("This claim button isn't for you.", ephemeral=True)
            return
        if allowed_winner_id not in winners:
            await interaction.response.send_message("You're not a winner of this giveaway.", ephemeral=True)
            return
    else:
        if interaction.user.id not in winners:
            await interaction.response.send_message("Only the listed winners can claim this prize.", ephemeral=True)
            return

    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message("Must be used in a server.", ephemeral=True)
        return

    winner = interaction.user
    creator_id = int(data.get("creator_id", 0))
    bot_member = guild.me or guild.get_member(interaction.client.user.id)
    if bot_member is None:
        await interaction.response.send_message("Bot member not found in this server.", ephemeral=True)
        return

    settings_resp = await backend.get_giveaway_settings(guild.id)
    if settings_resp is None:
        await interaction.response.send_message("Giveaways are not configured in this server.", ephemeral=True)
        return
    category_id = settings_resp.get("category_id")
    category = guild.get_channel(int(category_id)) if category_id else None
    if category is None or not isinstance(category, discord.CategoryChannel):
        await interaction.response.send_message(
            "No giveaway category configured. Ask an admin to set one with `/forge admin giveaway-category`.",
            ephemeral=True,
        )
        return

    existing = await _find_existing_exchange(backend, giveaway_id, winner.id)
    if existing is not None:
        channel = guild.get_channel(int(existing["channel_id"]))
        if channel is not None:
            await interaction.response.send_message(
                f"You already have an open exchange: {channel.mention}", ephemeral=True
            )
            return

    channel_name = f"exchange-{_slug(data.get('title', 'giveaway'))}-{winner.id % 10000:04d}"

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        winner: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
        ),
        bot_member: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_channels=True,
            manage_messages=True,
        ),
    }
    creator = guild.get_member(creator_id)
    if creator is not None:
        overwrites[creator] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
        )

    seen_admin_member_ids: set[int] = set()
    for member in guild.members:
        if member.bot:
            continue
        if member.id in seen_admin_member_ids:
            continue
        perms = member.guild_permissions
        if perms.administrator or perms.manage_guild:
            overwrites[member] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            )
            seen_admin_member_ids.add(member.id)

    admin_role = discord.utils.get(guild.roles, permissions=discord.Permissions(administrator=True))
    if admin_role is not None:
        overwrites[admin_role] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
        )

    await interaction.response.defer(ephemeral=True)
    try:
        channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites,
            reason=f"Giveaway exchange for {giveaway_id} winner {winner.id}",
        )
    except discord.HTTPException as exc:
        log.warning("failed to create exchange channel: %s", exc)
        await interaction.followup.send(f"Failed to create exchange channel: `{exc}`", ephemeral=True)
        return

    try:
        created = await backend.create_exchange(
            giveaway_id=giveaway_id,
            winner_id=winner.id,
            creator_id=creator_id,
            channel_id=channel.id,
            guild_id=guild.id,
        )
    except BackendError as exc:
        log.warning("failed to register exchange: %s", exc)
        try:
            await channel.delete(reason="exchange registration failed")
        except discord.HTTPException:
            pass
        await interaction.followup.send(f"Failed to register exchange: `{exc.message}`", ephemeral=True)
        return

    exchange_id = str(created.get("id") or created.get("exchange_id") or "")
    exchange_view = ExchangeView(exchange_id, giveaway_id, winner.id, creator_id)
    embed = discord.Embed(
        title="🎁 Giveaway Exchange",
        description=(
            f"Winner: {winner.mention}\n"
            f"Host: <@{creator_id}>\n"
            f"Giveaway: **{data.get('title', 'Untitled')}**\n\n"
            "Both parties must click their confirm button below to close this exchange."
        ),
        color=discord.Color.blurple(),
    )
    exchange_message_id: int | None = None
    try:
        exchange_msg = await channel.send(
            content=f"{winner.mention} <@{creator_id}>",
            embed=embed,
            view=exchange_view,
        )
        exchange_message_id = exchange_msg.id
    except discord.HTTPException as exc:
        log.warning("failed to post exchange message: %s", exc)

    if exchange_id and (exchange_message_id is not None):
        try:
            from ..giveaway_scheduler import get_winners_message_id
            winners_message_id = get_winners_message_id(giveaway_id)
            await backend.update_exchange_messages(
                exchange_id,
                exchange_message_id=exchange_message_id,
                winners_message_id=winners_message_id,
            )
        except BackendError as exc:
            log.warning("failed to backfill exchange message ids: %s", exc)

    try:
        await _disable_claim_button_for_winner(interaction.client, giveaway_id, winner.id)
    except Exception as exc:
        log.warning("failed to disable claim button for winner %s: %s", winner.id, exc)

    await interaction.followup.send(
        f"Exchange channel created: {channel.mention}", ephemeral=True
    )


async def _close_exchange_channel(client: discord.Client, exchange_id: str) -> None:
    backend = _get_client()
    try:
        exchange = await backend.get_exchange(exchange_id)
    except BackendError as exc:
        log.warning("close: failed to fetch exchange %s: %s", exchange_id, exc)
        return

    if exchange is None:
        return

    guild_id = exchange.get("guild_id")
    channel_id = exchange.get("channel_id")
    if not guild_id or not channel_id:
        return

    guild = client.get_guild(int(guild_id))
    if guild is None:
        return
    channel = guild.get_channel(int(channel_id))
    if channel is None:
        return

    winners_message_id = exchange.get("winners_message_id")
    if winners_message_id:
        try:
            await _update_winners_message_in_master(client, exchange, claimed=True)
        except Exception as exc:
            log.warning("close: failed to update winners message: %s", exc)
        try:
            await _maybe_finalize_winners_log(client, exchange)
        except Exception as exc:
            log.warning("close: failed to finalize winners log: %s", exc)

    embed = discord.Embed(
        title="🎁 Exchange Completed",
        description="Both parties confirmed. This channel will be deleted shortly.",
        color=discord.Color.green(),
    )
    try:
        await channel.send(embed=embed)
    except discord.HTTPException as exc:
        log.warning("close: failed to post completion: %s", exc)

    import asyncio
    await asyncio.sleep(5)
    try:
        await channel.delete(reason="Giveaway exchange completed")
    except discord.NotFound:
        pass
    except discord.HTTPException as exc:
        log.warning("close: failed to delete channel: %s", exc)


async def _update_exchange_status_message(interaction: Interaction, exchange: dict) -> None:
    channel = interaction.channel
    if channel is None or not isinstance(channel, discord.TextChannel):
        return
    exchange_message_id = exchange.get("exchange_message_id")
    if not exchange_message_id:
        return
    try:
        msg = await channel.fetch_message(int(exchange_message_id))
    except discord.NotFound:
        return
    except discord.HTTPException:
        return

    winner_done = bool(exchange.get("winner_confirmed", False))
    creator_done = bool(exchange.get("creator_confirmed", False))

    winner_mark = "✅" if winner_done else "⬜"
    creator_mark = "✅" if creator_done else "⬜"
    status = exchange.get("status", "pending")

    description_lines = [
        f"Winner: <@{int(exchange.get('winner_id', 0))}>",
        f"Host: <@{int(exchange.get('creator_id', 0))}>",
        "",
        f"Winner confirmation: {winner_mark}",
        f"Host confirmation: {creator_mark}",
    ]
    if status == "completed":
        description_lines.append("")
        description_lines.append("**Both confirmed. Channel will close shortly.**")

    new_embed = discord.Embed(
        title="🎁 Giveaway Exchange",
        description="\n".join(description_lines),
        color=discord.Color.green() if status == "completed" else discord.Color.blurple(),
    )
    try:
        await msg.edit(embed=new_embed)
    except discord.HTTPException as exc:
        log.warning("exchange status: edit failed: %s", exc)


async def _update_winners_message_in_master(client: discord.Client, exchange: dict, *, claimed: bool) -> None:
    guild_id = exchange.get("guild_id")
    channel_id = exchange.get("channel_id")
    message_id = exchange.get("winners_message_id")
    if not guild_id or not message_id:
        return

    guild = client.get_guild(int(guild_id))
    if guild is None:
        return

    backend = _get_client()
    settings = None
    try:
        settings = await backend.get_giveaway_settings(int(guild_id))
    except BackendError:
        pass
    cfg_id = settings.get("channel_id") if settings else None
    if not cfg_id:
        return
    master = guild.get_channel(int(cfg_id))
    if not isinstance(master, discord.TextChannel):
        return

    try:
        msg = await master.fetch_message(int(message_id))
    except discord.NotFound:
        return
    except discord.HTTPException:
        return

    embed = msg.embeds[0] if msg.embeds else discord.Embed()
    winner_id = int(exchange.get("winner_id", 0))
    winner_line_replaced = False
    if embed.description:
        lines = embed.description.split("\n")
        new_lines = []
        for line in lines:
            if winner_id and (f"<@{winner_id}>" in line or f"@{winner_id}" in line):
                marker = " ✅ CLAIMED" if claimed else ""
                new_lines.append(line + marker)
                winner_line_replaced = True
            else:
                new_lines.append(line)
        embed.description = "\n".join(new_lines)

    if not winner_line_replaced:
        for i, field in enumerate(embed.fields):
            if field.name == "Winners" and winner_id and (f"<@{winner_id}>" in field.value or f"@{winner_id}" in field.value):
                new_value = field.value
                if claimed:
                    new_value = new_value.replace(f"<@{winner_id}>", f"<@{winner_id}> ✅")
                embed.set_field_at(i, name=field.name, value=new_value, inline=field.inline)
                break

    try:
        await msg.edit(embed=embed)
    except discord.HTTPException as exc:
        log.warning("winners message edit failed: %s", exc)


async def _maybe_finalize_winners_log(client: discord.Client, exchange: dict) -> None:
    guild_id = exchange.get("guild_id")
    message_id = exchange.get("winners_message_id")
    giveaway_id = exchange.get("giveaway_id")
    if not guild_id or not message_id or not giveaway_id:
        return

    guild = client.get_guild(int(guild_id))
    if guild is None:
        return

    backend = _get_client()
    try:
        settings = await backend.get_giveaway_settings(int(guild_id))
    except BackendError:
        return
    if not settings:
        return
    cfg_id = settings.get("channel_id")
    if not cfg_id:
        return
    master = guild.get_channel(int(cfg_id))
    if not isinstance(master, discord.TextChannel):
        return

    try:
        giveaway = await backend.get_giveaway(giveaway_id)
    except BackendError:
        return
    if giveaway is None:
        return
    winner_ids = [int(w) for w in (giveaway.get("winner_ids") or [])]
    if not winner_ids:
        return

    try:
        all_exchanges = await backend.list_exchanges_for_giveaway(giveaway_id)
    except BackendError:
        return

    status_by_winner: dict[int, str] = {
        int(e.get("winner_id")): str(e.get("status") or "")
        for e in all_exchanges
        if e.get("winner_id") is not None
    }
    terminal = {"completed", "cancelled"}
    if not all(status_by_winner.get(w) in terminal for w in winner_ids):
        return

    try:
        msg = await master.fetch_message(int(message_id))
    except (discord.NotFound, discord.HTTPException):
        return

    embed = msg.embeds[0] if msg.embeds else discord.Embed()
    title_text = (embed.title or "").replace("🎉 ", "").replace(" — Winners!", "")
    embed.title = f"📜 {title_text} — Log"
    embed.color = discord.Color.greyple()
    embed.set_footer(text="All winners have completed their exchanges. This message is now a permanent log.")

    try:
        await msg.edit(embed=embed, view=None)
    except discord.HTTPException as exc:
        log.warning("finalize winners log: edit failed: %s", exc)


async def _disable_claim_button_for_winner(
    client: discord.Client, giveaway_id: str, winner_id: int
) -> None:
    backend = _get_client()
    try:
        giveaway = await backend.get_giveaway(giveaway_id)
    except BackendError:
        return
    if giveaway is None:
        return

    guild_id = giveaway.get("guild_id")
    if not guild_id:
        return
    guild = client.get_guild(int(guild_id))
    if guild is None:
        return

    try:
        settings = await backend.get_giveaway_settings(int(guild_id))
    except BackendError:
        return
    if not settings:
        return
    cfg_id = settings.get("channel_id")
    if not cfg_id:
        return
    master = guild.get_channel(int(cfg_id))
    if not isinstance(master, discord.TextChannel):
        return

    winner_ids = [int(w) for w in (giveaway.get("winner_ids") or [])]

    try:
        existing_exchanges = await backend.list_exchanges_for_giveaway(giveaway_id)
    except BackendError:
        existing_exchanges = []
    winners_with_exchange: set[int] = {
        int(ex.get("winner_id")) for ex in existing_exchanges if ex.get("winner_id") is not None
    }

    target_msg: discord.Message | None = None
    async for m in master.history(limit=20):
        if m.author.id != client.user.id:
            continue
        if not m.components:
            continue
        for comp in m.components:
            for child in comp.children:
                cid = getattr(child, "custom_id", None)
                if isinstance(cid, str) and cid.startswith(CLAIM_PREFIX):
                    target_msg = m
                    break
            if target_msg is not None:
                break
        if target_msg is not None:
            break

    if target_msg is None:
        return

    try:
        labels = await _resolve_labels(client, guild, winner_ids)
        new_view = ClaimView(giveaway_id, winner_ids, labels)
        for child in new_view.children:
            if not isinstance(child, discord.ui.Button):
                continue
            cid = getattr(child, "custom_id", None)
            if not isinstance(cid, str):
                continue
            for w in winners_with_exchange:
                if cid.endswith(f":{w}"):
                    child.disabled = True
                    base = child.label or "Claim"
                    if "(claimed)" not in base:
                        child.label = f"{base} (claimed)"[:80]
                    break
        await target_msg.edit(view=new_view)
    except Exception as exc:
        log.warning("disable claim button: edit failed: %s", exc)


async def _resolve_labels(client: discord.Client, guild: discord.Guild, winner_ids: list[int]) -> dict[int, str]:
    labels: dict[int, str] = {}
    for wid in winner_ids:
        iwid = int(wid)
        member = guild.get_member(iwid)
        name = member.display_name if member else None
        if not name:
            try:
                user = await client.fetch_user(iwid)
                name = user.name
            except Exception:
                name = None
        labels[iwid] = name or str(iwid)
    return labels


class ExchangeView(discord.ui.View):
    def __init__(self, exchange_id: str, giveaway_id: str, winner_id: int, creator_id: int):
        super().__init__(timeout=None)
        self.exchange_id = exchange_id
        self.giveaway_id = giveaway_id
        self.winner_id = winner_id
        self.creator_id = creator_id

        winner_btn = discord.ui.Button(
            label="Confirm Received",
            style=discord.ButtonStyle.success,
            custom_id=f"{WINNER_CONFIRM_PREFIX}{exchange_id}",
        )
        winner_btn.callback = self._winner_callback
        self.add_item(winner_btn)

        creator_btn = discord.ui.Button(
            label="Confirm Sent",
            style=discord.ButtonStyle.success,
            custom_id=f"{CREATOR_CONFIRM_PREFIX}{exchange_id}",
        )
        creator_btn.callback = self._creator_callback
        self.add_item(creator_btn)

    async def _winner_callback(self, interaction: Interaction) -> None:
        await self._confirm(interaction, "winner", interaction.user.id == self.winner_id)

    async def _creator_callback(self, interaction: Interaction) -> None:
        await self._confirm(interaction, "creator", interaction.user.id == self.creator_id)

    async def _confirm(self, interaction: Interaction, by: str, authorized: bool) -> None:
        if not authorized:
            await interaction.response.send_message("You're not a participant of this exchange.", ephemeral=True)
            return

        backend = _get_client()
        try:
            exchange = await backend.confirm_exchange(self.exchange_id, by)
        except BackendError as exc:
            await interaction.response.send_message(f"Failed to confirm: `{exc.message}`", ephemeral=True)
            return

        winner_done = bool(exchange.get("winner_confirmed", False))
        creator_done = bool(exchange.get("creator_confirmed", False))
        status = exchange.get("status", "pending")

        await interaction.response.send_message(
            f"Marked as confirmed by {by}.", ephemeral=True
        )

        try:
            await _update_exchange_status_message(interaction, exchange)
        except Exception as exc:
            log.warning("exchange: failed to update status message: %s", exc)

        if status == "completed" and winner_done and creator_done:
            await _close_exchange_channel(interaction.client, self.exchange_id)


def make_claim_view(
    giveaway_id: str,
    winner_ids: list[int],
    winner_labels: dict[int, str] | None = None,
) -> ClaimView:
    return ClaimView(giveaway_id, winner_ids, winner_labels)