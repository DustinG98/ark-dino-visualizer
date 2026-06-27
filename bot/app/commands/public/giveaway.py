import logging
import re
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands, Interaction

from ...backend_client import BackendError
from ...views.giveaway import build_giveaway_view


log = logging.getLogger(__name__)


_DURATION_RE = re.compile(r"^(\d+)\s*(s|sec|secs|m|min|mins|h|hr|hrs|d|day|days)$", re.IGNORECASE)


_SLUG_RE = re.compile(r"[^a-z0-9]+")


_UNCONFIGURED_MSG = (
    "Giveaways aren't configured in this server. "
    "Ask an admin to enable them with `/forge admin giveaway-enable` "
    "(or use the admin panel)."
)


_GIVEAWAY_CHANNEL_PREFIX = "🎁-"


def _slug(text: str, max_len: int = 60) -> str:
    s = _SLUG_RE.sub("-", text.lower()).strip("-")
    return s[:max_len] or "giveaway"


def _get_client():
    from ...bot_commands import _get_client
    return _get_client()


def _get_scheduler():
    from ...giveaway_scheduler import get_scheduler
    return get_scheduler()


def _parse_duration(text: str) -> timedelta | None:
    m = _DURATION_RE.match(text.strip())
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2).lower()
    if unit.startswith("s"):
        return timedelta(seconds=n)
    if unit.startswith("m"):
        return timedelta(minutes=n)
    if unit.startswith("h"):
        return timedelta(hours=n)
    if unit.startswith("d"):
        return timedelta(days=n)
    return None


async def _reply(interaction: Interaction, content: str) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(content, ephemeral=True)
    else:
        await interaction.response.send_message(content, ephemeral=True)


async def _validate_giveaway_setup(
    interaction: Interaction,
) -> tuple[dict | None, discord.TextChannel | None, discord.CategoryChannel | None, str | None]:
    """Return (settings, channel, category, error_message).

    `error_message` is non-None iff giveaways aren't usable. Caller is
    responsible for surfacing it ephemerally.
    """
    guild_id = interaction.guild_id
    if guild_id is None:
        return None, None, None, "This must be used in a server."
    backend = _get_client()
    try:
        settings = await backend.get_giveaway_settings(guild_id)
    except BackendError as exc:
        return None, None, None, f"Failed to load settings: `{exc.message}`"
    if not settings or not settings.get("enabled", False):
        return None, None, None, _UNCONFIGURED_MSG
    channel_id = settings.get("channel_id")
    category_id = settings.get("category_id")
    if not channel_id or not category_id:
        return None, None, None, _UNCONFIGURED_MSG
    guild = interaction.guild
    channel = guild.get_channel(int(channel_id)) if guild else None
    if channel is None or not isinstance(channel, discord.TextChannel):
        return None, None, None, _UNCONFIGURED_MSG
    category: discord.CategoryChannel | None = None
    if category_id:
        cat_obj = guild.get_channel(int(category_id)) if guild else None
        if isinstance(cat_obj, discord.CategoryChannel):
            category = cat_obj
    if category is None:
        return None, None, None, _UNCONFIGURED_MSG
    return settings, channel, category, None


async def _create_per_giveaway_channel(
    interaction: Interaction,
    category: discord.CategoryChannel,
    title: str,
    settings: dict | None = None,
) -> tuple[discord.TextChannel | None, str | None]:
    guild = interaction.guild
    bot_member = guild.me if guild else None
    if guild is None or bot_member is None:
        return None, "Bot member not found in this server."
    base = _slug(title, max_len=80)
    name = f"{_GIVEAWAY_CHANNEL_PREFIX}giveaway-{base}"

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=False, read_message_history=True),
        bot_member: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_channels=True,
            manage_messages=True,
        ),
    }
    admin_role = discord.utils.get(guild.roles, permissions=discord.Permissions(administrator=True))
    if admin_role is not None:
        overwrites[admin_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

    ping_role_id = (settings or {}).get("ping_role_id")
    if ping_role_id:
        ping_role = guild.get_role(int(ping_role_id))
        if ping_role is not None:
            overwrites[ping_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            )

    try:
        channel = await guild.create_text_channel(
            name=name,
            category=category,
            overwrites=overwrites,
            reason=f"New giveaway: {title}",
        )
        return channel, None
    except discord.Forbidden as exc:
        me = guild.me
        perms = me.guild_permissions if me else discord.Permissions.none()
        missing: list[str] = []
        if not perms.manage_channels:
            missing.append("`Manage Channels`")
        if not perms.manage_roles:
            missing.append("`Manage Roles` (needed to apply permission overwrites)")
        if not perms.manage_messages:
            missing.append("`Manage Messages`")
        cat_perm = me and category.permissions_for(me).manage_channels
        if not cat_perm:
            missing.append("`Manage Channels` in the giveaway category")
        msg = (
            f"Missing permissions: {', '.join(missing)}. "
            "Ensure the bot's role is **above** all roles it tries to overwrite, and that the bot has "
            "`Manage Channels` + `Manage Roles` server-wide **and** in the giveaway category."
            if missing else
            f"Discord returned: {exc}"
        )
        log.warning("failed to create per-giveaway channel: %s", msg)
        return None, msg
    except discord.HTTPException as exc:
        log.warning("failed to create per-giveaway channel: %s", exc)
        return None, f"Discord returned: {exc}"


async def _make_giveaway_message(
    interaction: Interaction,
    channel: discord.TextChannel,
    title: str,
    description: str,
    winner_count: int,
    end_at: datetime,
    image_url: str | None,
    giveaway_id: str,
    ping_role_id: int | None = None,
) -> discord.Message:
    embed = discord.Embed(
        title=f"🎉 {title}",
        description=description,
        color=discord.Color.blurple(),
        timestamp=end_at,
    )
    embed.add_field(name="Winners", value=str(winner_count), inline=True)
    embed.add_field(name="Entries", value="0", inline=True)
    embed.add_field(name="Ends", value=f"<t:{int(end_at.timestamp())}:R>", inline=True)
    embed.add_field(name="Host", value=f"{interaction.user.mention}", inline=True)
    embed.set_footer(text=f"ID: {giveaway_id}")
    if image_url:
        embed.set_image(url=image_url)

    view = build_giveaway_view(giveaway_id)

    content_parts = []
    if ping_role_id:
        content_parts.append(f"<@&{ping_role_id}>")
    content_parts.append(f"New giveaway hosted by {interaction.user.mention}")
    content = " — ".join(content_parts) if len(content_parts) > 1 else content_parts[0]

    return await channel.send(content=content, embed=embed, view=view)


async def run_giveaway_create(
    interaction: Interaction,
    *,
    title: str,
    winners: int,
    duration_text: str,
    description: str | None,
    image_url: str | None,
) -> tuple[bool, str]:
    """Validate inputs, create the per-giveaway channel + giveaway, post embed. Returns (ok, message)."""
    settings, _default_channel, category, err_msg = await _validate_giveaway_setup(interaction)
    if err_msg is not None:
        await _reply(interaction, err_msg)
        return False, err_msg

    if winners < 1 or winners > 20:
        return False, "Winners must be between 1 and 20."

    delta = _parse_duration(duration_text)
    if delta is None:
        return False, "Invalid duration. Use e.g. '30m', '2h', '1d'."
    if delta > timedelta(days=30):
        return False, "Maximum giveaway duration is 30 days."

    end_at = datetime.now(timezone.utc) + delta

    per_channel, err = await _create_per_giveaway_channel(interaction, category, title, settings=settings)
    if per_channel is None:
        return False, err or "Failed to create the per-giveaway channel (see bot logs)."

    backend = _get_client()
    try:
        created = await backend.create_giveaway(
            guild_id=interaction.guild_id,
            creator_id=interaction.user.id,
            channel_id=per_channel.id,
            message_id=None,
            title=title,
            description=description or "",
            image_url=image_url,
            winner_count=winners,
            end_at_iso=end_at.isoformat(),
        )
    except BackendError as exc:
        try:
            await per_channel.delete(reason="giveaway creation failed")
        except discord.HTTPException:
            pass
        return False, f"Failed to create giveaway: `{exc.message}`"

    giveaway_id = str(created.get("id") or created.get("giveaway_id") or "")
    if not giveaway_id:
        return False, "Backend did not return a giveaway id."

    try:
        msg = await _make_giveaway_message(
            interaction, per_channel, title, description or "", winners, end_at, image_url, giveaway_id,
            ping_role_id=(settings or {}).get("ping_role_id"),
        )
    except discord.HTTPException as exc:
        log.warning("failed to post giveaway message: %s", exc)
        return False, "Failed to post giveaway message."

    sched = _get_scheduler()
    if sched is not None:
        sched.register_views(giveaway_id)
        sched.schedule_end(giveaway_id, end_at)

    try:
        await backend.update_giveaway_message_id(giveaway_id, msg.id)
    except Exception as exc:
        log.warning("failed to backfill message_id for %s: %s", giveaway_id, exc)

    return True, f"Giveaway created in {per_channel.mention} — id `{giveaway_id}`."


def register_giveaway_commands(tree: app_commands.CommandTree) -> None:
    giveaway_group = app_commands.Group(name="giveaway", description="Create and manage giveaways.")

    @giveaway_group.command(name="create", description="Start a new giveaway.")
    @app_commands.describe(
        title="Giveaway title",
        winners="How many winners (1-20)",
        duration="Duration like '30m', '2h', '1d' (max 30d)",
        description="Optional description (max 1000 chars)",
        image="Optional cover image (image/* attachment)",
    )
    async def giveaway_create(
        interaction: Interaction,
        title: str,
        winners: int,
        duration: str,
        description: str | None = None,
        image: discord.Attachment | None = None,
    ):
        if image is not None and not (image.content_type or "").startswith("image/"):
            await interaction.response.send_message("Image must be an image/* attachment.", ephemeral=True)
            return
        image_url = image.url if image is not None else None

        await interaction.response.defer(ephemeral=True)
        ok, msg_text = await run_giveaway_create(
            interaction,
            title=title,
            winners=winners,
            duration_text=duration,
            description=description,
            image_url=image_url,
        )
        if ok:
            await interaction.followup.send(msg_text, ephemeral=True)

    @giveaway_group.command(name="list", description="List active giveaways in this server.")
    async def giveaway_list(interaction: Interaction):
        guild_id = interaction.guild_id
        if guild_id is None:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return
        backend = _get_client()
        try:
            giveaways = await backend.list_active_giveaways(guild_id)
        except BackendError as exc:
            await interaction.response.send_message(f"Failed to list giveaways: `{exc.message}`", ephemeral=True)
            return

        if not giveaways:
            await interaction.response.send_message("No active giveaways.", ephemeral=True)
            return

        embed = discord.Embed(title="Active Giveaways", color=discord.Color.blurple())
        for g in giveaways[:10]:
            gid = g.get("id") or g.get("giveaway_id") or "?"
            title_v = g.get("title", "Untitled")
            end_at = g.get("end_at", "?")
            entries = len(g.get("entries") or [])
            embed.add_field(name=f"`{gid}` — {title_v}", value=f"Ends: {end_at}\nEntries: {entries}", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @giveaway_group.command(name="cancel", description="End one of your giveaways immediately and select winners.")
    @app_commands.describe(giveaway_id="The giveaway id (visible in /giveaway list and the giveaway footer).")
    async def giveaway_cancel(interaction: Interaction, giveaway_id: str):
        backend = _get_client()
        try:
            data = await backend.get_giveaway(giveaway_id)
        except BackendError as exc:
            await interaction.response.send_message(f"Failed to fetch: `{exc.message}`", ephemeral=True)
            return
        if data is None:
            await interaction.response.send_message("Giveaway not found.", ephemeral=True)
            return
        if int(data.get("creator_id", 0)) != interaction.user.id:
            await interaction.response.send_message("You can only cancel giveaways you created.", ephemeral=True)
            return

        from ...commands.admin.giveaway import run_giveaway_force_end

        await interaction.response.defer(ephemeral=True)
        result = await run_giveaway_force_end(
            interaction.client,
            interaction.guild_id,
            giveaway_id,
            requested_by=interaction.user.id,
        )
        if not result["ok"]:
            await interaction.followup.send(
                f"Failed at {result['stage']}: `{result['message']}`", ephemeral=True
            )
            return
        await interaction.followup.send(
            f"Giveaway `{giveaway_id}` ended and winners selected.", ephemeral=True
        )

    @giveaway_group.command(name="help", description="Show public giveaway commands.")
    async def giveaway_help(interaction: Interaction):
        embed = discord.Embed(
            title="🎉 Giveaway Commands",
            color=discord.Color.blurple(),
            description=(
                "Create and manage giveaways. Giveaways must be enabled by a server admin first "
                "(use `/forge admin giveaway-enable`)."
            ),
        )
        embed.add_field(
            name="Public panel",
            value=(
                "Most servers have a permanent **Giveaways** panel in a designated channel. "
                "Click **Create Giveaway** on it to open a form (supports a cover image upload). "
                "Ask an admin if you don't see one."
            ),
            inline=False,
        )
        embed.add_field(
            name="/giveaway create <title> <winners> <duration> [description] [image]",
            value=(
                "Start a new giveaway.\n"
                "• `title` — giveaway title (max 200 chars)\n"
                "• `winners` — number of winners (1–20)\n"
                "• `duration` — how long it runs, e.g. `30m`, `2h`, `1d` (max 30 days)\n"
                "• `description` — optional details (max 1000 chars)\n"
                "• `image` — optional cover image attachment (`image/*`)\n"
                "The bot creates a private channel in the configured category, posts an Enter button, "
                "and pings the configured role if one is set."
            ),
            inline=False,
        )
        embed.add_field(
            name="/giveaway list",
            value="List up to 10 active giveaways in this server with their id, end time, and entry count.",
            inline=False,
        )
        embed.add_field(
            name="/giveaway cancel <giveaway_id>",
            value=(
                "End one of **your** giveaways immediately and select winners. "
                "You can only end giveaways you created. "
                "Admins can end any giveaway from the per-giveaway channel via the **End now (Admin)** button."
            ),
            inline=False,
        )
        embed.add_field(
            name="After a giveaway ends",
            value=(
                "Winners are announced in the master giveaway channel with a per-winner **Claim** button. "
                "Clicking Claim opens a private exchange channel with the host to coordinate the prize. "
                "Both parties must click their confirm button before the exchange channel closes."
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    tree.add_command(giveaway_group)
