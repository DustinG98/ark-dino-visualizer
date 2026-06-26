import logging
import os
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, ForeignKey, BigInteger, Boolean
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.pool import NullPool

_log = logging.getLogger(__name__)


_raw_url = os.environ.get(
    "DATABASE_URL",
    "postgresql://arkbot:changeme@db:5432/arkbot"
)
if _raw_url.startswith("postgresql://"):
    DATABASE_URL = _raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)
else:
    DATABASE_URL = _raw_url

Base = declarative_base()

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    poolclass=NullPool,
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Guild(Base):
    __tablename__ = "guilds"

    guild_id = Column(BigInteger, primary_key=True)
    name = Column(String(255), nullable=True)
    created_at = Column(Integer, nullable=False, default=lambda: int(datetime.utcnow().timestamp()))

    welcome_message = relationship("WelcomeMessage", back_populates="guild", uselist=False)
    giveaway_settings = relationship("GiveawaySettings", back_populates="guild", uselist=False)
    giveaways = relationship("Giveaway", back_populates="guild")
    role_picker_settings = relationship("RolePickerSettings", back_populates="guild", uselist=False)


class WelcomeMessage(Base):
    __tablename__ = "welcome_messages"

    guild_id = Column(BigInteger, ForeignKey("guilds.guild_id"), primary_key=True)
    channel_id = Column(BigInteger, nullable=False)
    message = Column(Text, nullable=False)
    enabled = Column(Boolean, nullable=False, default=False)
    updated_at = Column(Integer, nullable=False, default=lambda: int(datetime.utcnow().timestamp()))

    guild = relationship("Guild", back_populates="welcome_message")


class GiveawaySettings(Base):
    __tablename__ = "giveaway_settings"

    guild_id = Column(BigInteger, ForeignKey("guilds.guild_id"), primary_key=True)
    enabled = Column(Boolean, nullable=False, default=False)
    channel_id = Column(BigInteger, nullable=True)
    category_id = Column(BigInteger, nullable=True)
    ping_role_id = Column(BigInteger, nullable=True)
    admin_panel_channel_id = Column(BigInteger, nullable=True)
    admin_panel_message_id = Column(BigInteger, nullable=True)
    public_panel_channel_id = Column(BigInteger, nullable=True)
    public_panel_message_id = Column(BigInteger, nullable=True)
    updated_at = Column(Integer, nullable=False, default=lambda: int(datetime.utcnow().timestamp()))

    guild = relationship("Guild", back_populates="giveaway_settings")


class RolePickerSettings(Base):
    __tablename__ = "role_picker_settings"

    guild_id = Column(BigInteger, ForeignKey("guilds.guild_id"), primary_key=True)
    admin_panel_channel_id = Column(BigInteger, nullable=True)
    admin_panel_message_id = Column(BigInteger, nullable=True)
    public_panel_channel_id = Column(BigInteger, nullable=True)
    public_panel_message_id = Column(BigInteger, nullable=True)
    updated_at = Column(Integer, nullable=False, default=lambda: int(datetime.utcnow().timestamp()))

    guild = relationship("Guild", back_populates="role_picker_settings")


class RolePickerRole(Base):
    __tablename__ = "role_picker_roles"

    guild_id = Column(BigInteger, ForeignKey("guilds.guild_id"), primary_key=True)
    position = Column(Integer, primary_key=True)
    role_id = Column(BigInteger, nullable=False)
    label = Column(String(80), nullable=False)
    emoji = Column(String(64), nullable=True)
    description = Column(String(100), nullable=True)
    created_at = Column(Integer, nullable=False, default=lambda: int(datetime.utcnow().timestamp()))


class Giveaway(Base):
    __tablename__ = "giveaways"

    id = Column(String(36), primary_key=True)
    guild_id = Column(BigInteger, ForeignKey("guilds.guild_id"), nullable=False, index=True)
    creator_id = Column(BigInteger, nullable=False, index=True)
    channel_id = Column(BigInteger, nullable=False)
    message_id = Column(BigInteger, nullable=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False, default="")
    image_url = Column(Text, nullable=True)
    winner_count = Column(Integer, nullable=False, default=1)
    status = Column(String(16), nullable=False, default="active", index=True)
    winner_ids = Column(Text, nullable=False, default="")
    winners_posted = Column(Boolean, nullable=False, default=False)
    created_at = Column(Integer, nullable=False, default=lambda: int(datetime.utcnow().timestamp()))
    end_at = Column(Integer, nullable=False, index=True)

    guild = relationship("Guild", back_populates="giveaways")
    entries = relationship("GiveawayEntry", back_populates="giveaway", cascade="all, delete-orphan")


class GiveawayEntry(Base):
    __tablename__ = "giveaway_entries"

    giveaway_id = Column(String(36), ForeignKey("giveaways.id"), primary_key=True)
    user_id = Column(BigInteger, primary_key=True)
    entered_at = Column(Integer, nullable=False, default=lambda: int(datetime.utcnow().timestamp()))

    giveaway = relationship("Giveaway", back_populates="entries")


class GiveawayExchange(Base):
    __tablename__ = "giveaway_exchanges"

    id = Column(String(36), primary_key=True)
    giveaway_id = Column(String(36), ForeignKey("giveaways.id"), nullable=False, index=True)
    guild_id = Column(BigInteger, nullable=False, index=True)
    winner_id = Column(BigInteger, nullable=False, index=True)
    creator_id = Column(BigInteger, nullable=False)
    channel_id = Column(BigInteger, nullable=False)
    exchange_message_id = Column(BigInteger, nullable=True)
    winners_message_id = Column(BigInteger, nullable=True)
    status = Column(String(16), nullable=False, default="pending", index=True)
    winner_confirmed = Column(Boolean, nullable=False, default=False)
    creator_confirmed = Column(Boolean, nullable=False, default=False)
    created_at = Column(Integer, nullable=False, default=lambda: int(datetime.utcnow().timestamp()))
    closed_at = Column(Integer, nullable=True)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _run_lightweight_migrations(conn)


async def _run_lightweight_migrations(conn) -> None:
    from sqlalchemy import text

    statements = [
        "ALTER TABLE giveaways ADD COLUMN IF NOT EXISTS winners_posted BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE giveaway_exchanges ADD COLUMN IF NOT EXISTS exchange_message_id BIGINT",
        "ALTER TABLE giveaway_exchanges ADD COLUMN IF NOT EXISTS winners_message_id BIGINT",
        "ALTER TABLE giveaway_settings ADD COLUMN IF NOT EXISTS ping_role_id BIGINT",
        "ALTER TABLE giveaway_settings ADD COLUMN IF NOT EXISTS admin_panel_channel_id BIGINT",
        "ALTER TABLE giveaway_settings ADD COLUMN IF NOT EXISTS admin_panel_message_id BIGINT",
        "ALTER TABLE giveaway_settings ADD COLUMN IF NOT EXISTS public_panel_channel_id BIGINT",
        "ALTER TABLE giveaway_settings ADD COLUMN IF NOT EXISTS public_panel_message_id BIGINT",
        "CREATE TABLE IF NOT EXISTS role_picker_settings (guild_id BIGINT PRIMARY KEY REFERENCES guilds(guild_id) ON DELETE CASCADE, admin_panel_channel_id BIGINT, admin_panel_message_id BIGINT, public_panel_channel_id BIGINT, public_panel_message_id BIGINT, updated_at INTEGER NOT NULL DEFAULT 0)",
        "CREATE TABLE IF NOT EXISTS role_picker_roles (guild_id BIGINT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE, position INTEGER NOT NULL, role_id BIGINT NOT NULL, label VARCHAR(80) NOT NULL, emoji VARCHAR(64), description VARCHAR(100), created_at INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (guild_id, position))",
    ]
    for stmt in statements:
        try:
            await conn.execute(text(stmt))
        except Exception as exc:
            _log.warning("migration statement failed (%s): %s", stmt, exc)


async def get_guild(guild_id: int) -> Guild | None:
    async with async_session() as session:
        result = await session.get(Guild, guild_id)
        return result


async def upsert_guild(guild_id: int, name: str | None = None) -> Guild:
    async with async_session() as session:
        guild = await session.get(Guild, guild_id)
        if guild is None:
            guild = Guild(guild_id=guild_id, name=name)
            session.add(guild)
        else:
            if name is not None:
                guild.name = name
        await session.commit()
        await session.refresh(guild)
        return guild


async def get_welcome_settings(guild_id: int) -> WelcomeMessage | None:
    async with async_session() as session:
        result = await session.get(WelcomeMessage, guild_id)
        return result


async def upsert_welcome_settings(guild_id: int, channel_id: int, message: str, enabled: bool = True) -> WelcomeMessage:
    await upsert_guild(guild_id)

    async with async_session() as session:
        welcome = await session.get(WelcomeMessage, guild_id)
        if welcome is None:
            welcome = WelcomeMessage(guild_id=guild_id, channel_id=channel_id, message=message, enabled=enabled)
            session.add(welcome)
        else:
            welcome.channel_id = channel_id
            welcome.message = message
            welcome.enabled = enabled
            welcome.updated_at = int(datetime.utcnow().timestamp())
        await session.commit()
        await session.refresh(welcome)
        return welcome


async def get_giveaway_settings(guild_id: int) -> GiveawaySettings | None:
    async with async_session() as session:
        result = await session.get(GiveawaySettings, guild_id)
        return result


async def upsert_giveaway_settings(guild_id: int, enabled: bool, channel_id: int | None) -> GiveawaySettings:
    await upsert_guild(guild_id)

    async with async_session() as session:
        existing = await session.get(GiveawaySettings, guild_id)
        if existing is None:
            existing = GiveawaySettings(guild_id=guild_id, enabled=enabled, channel_id=channel_id)
            session.add(existing)
        else:
            existing.enabled = enabled
            if channel_id is not None:
                existing.channel_id = channel_id
            existing.updated_at = int(datetime.utcnow().timestamp())
        await session.commit()
        await session.refresh(existing)
        return existing


async def update_giveaway_category(guild_id: int, category_id: int | None) -> GiveawaySettings:
    await upsert_guild(guild_id)

    async with async_session() as session:
        existing = await session.get(GiveawaySettings, guild_id)
        if existing is None:
            existing = GiveawaySettings(guild_id=guild_id, enabled=False, channel_id=None, category_id=category_id)
            session.add(existing)
        else:
            existing.category_id = category_id
            existing.updated_at = int(datetime.utcnow().timestamp())
        await session.commit()
        await session.refresh(existing)
        return existing


async def update_giveaway_ping_role(guild_id: int, ping_role_id: int | None) -> GiveawaySettings:
    await upsert_guild(guild_id)

    async with async_session() as session:
        existing = await session.get(GiveawaySettings, guild_id)
        if existing is None:
            existing = GiveawaySettings(guild_id=guild_id, enabled=False, channel_id=None, category_id=None, ping_role_id=ping_role_id)
            session.add(existing)
        else:
            existing.ping_role_id = ping_role_id
            existing.updated_at = int(datetime.utcnow().timestamp())
        await session.commit()
        await session.refresh(existing)
        return existing


async def update_giveaway_admin_panel_channel(guild_id: int, channel_id: int | None) -> GiveawaySettings:
    await upsert_guild(guild_id)

    async with async_session() as session:
        existing = await session.get(GiveawaySettings, guild_id)
        if existing is None:
            existing = GiveawaySettings(
                guild_id=guild_id,
                enabled=False,
                channel_id=None,
                category_id=None,
                admin_panel_channel_id=channel_id,
            )
            session.add(existing)
        else:
            existing.admin_panel_channel_id = channel_id
            existing.updated_at = int(datetime.utcnow().timestamp())
        await session.commit()
        await session.refresh(existing)
        return existing


async def list_guilds_with_admin_panel() -> list[int]:
    from sqlalchemy import select

    async with async_session() as session:
        stmt = select(GiveawaySettings.guild_id).where(
            GiveawaySettings.admin_panel_channel_id.isnot(None)
        )
        result = await session.execute(stmt)
        return [int(row[0]) for row in result.all()]


async def update_giveaway_admin_panel_message(guild_id: int, message_id: int | None) -> GiveawaySettings | None:
    async with async_session() as session:
        existing = await session.get(GiveawaySettings, guild_id)
        if existing is None:
            return None
        existing.admin_panel_message_id = message_id
        existing.updated_at = int(datetime.utcnow().timestamp())
        await session.commit()
        await session.refresh(existing)
        return existing


async def get_admin_panel_message_id(guild_id: int) -> int | None:
    async with async_session() as session:
        existing = await session.get(GiveawaySettings, guild_id)
        if existing is None:
            return None
        return getattr(existing, "admin_panel_message_id", None)


async def update_giveaway_public_panel_channel(guild_id: int, channel_id: int | None) -> GiveawaySettings:
    await upsert_guild(guild_id)

    async with async_session() as session:
        existing = await session.get(GiveawaySettings, guild_id)
        if existing is None:
            existing = GiveawaySettings(
                guild_id=guild_id,
                enabled=False,
                channel_id=None,
                category_id=None,
                public_panel_channel_id=channel_id,
            )
            session.add(existing)
        else:
            existing.public_panel_channel_id = channel_id
            existing.updated_at = int(datetime.utcnow().timestamp())
        await session.commit()
        await session.refresh(existing)
        return existing


async def list_guilds_with_public_panel() -> list[int]:
    from sqlalchemy import select

    async with async_session() as session:
        stmt = select(GiveawaySettings.guild_id).where(
            GiveawaySettings.public_panel_channel_id.isnot(None)
        )
        result = await session.execute(stmt)
        return [int(row[0]) for row in result.all()]


async def update_giveaway_public_panel_message(guild_id: int, message_id: int | None) -> GiveawaySettings | None:
    async with async_session() as session:
        existing = await session.get(GiveawaySettings, guild_id)
        if existing is None:
            return None
        existing.public_panel_message_id = message_id
        existing.updated_at = int(datetime.utcnow().timestamp())
        await session.commit()
        await session.refresh(existing)
        return existing


async def get_giveaway(giveaway_id: str) -> dict | None:
    async with async_session() as session:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        stmt = (
            select(Giveaway)
            .where(Giveaway.id == giveaway_id)
            .options(selectinload(Giveaway.entries))
        )
        result = await session.execute(stmt)
        giveaway = result.scalar_one_or_none()
        if giveaway is None:
            return None
        return _giveaway_to_dict(giveaway)


async def list_active_giveaways_for_guild(guild_id: int) -> list[dict]:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    async with async_session() as session:
        stmt = (
            select(Giveaway)
            .where(Giveaway.guild_id == guild_id, Giveaway.status == "active")
            .options(selectinload(Giveaway.entries))
            .order_by(Giveaway.end_at.asc())
        )
        result = await session.execute(stmt)
        return [_giveaway_to_dict(g) for g in result.scalars().all()]


async def list_active_giveaways_global() -> list[dict]:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    async with async_session() as session:
        stmt = (
            select(Giveaway)
            .where(Giveaway.status == "active")
            .options(selectinload(Giveaway.entries))
            .order_by(Giveaway.end_at.asc())
        )
        result = await session.execute(stmt)
        return [_giveaway_to_dict(g) for g in result.scalars().all()]


async def count_active_giveaways_in_window(guild_id: int, since_ts: int) -> int:
    from sqlalchemy import func, select

    async with async_session() as session:
        stmt = select(func.count(Giveaway.id)).where(
            Giveaway.guild_id == guild_id,
            Giveaway.status == "active",
            Giveaway.created_at >= since_ts,
        )
        result = await session.execute(stmt)
        return int(result.scalar() or 0)


async def create_giveaway(
    *,
    id: str,
    guild_id: int,
    creator_id: int,
    channel_id: int,
    title: str,
    description: str,
    image_url: str | None,
    winner_count: int,
    end_at: int,
) -> dict:
    await upsert_guild(guild_id)

    async with async_session() as session:
        giveaway = Giveaway(
            id=id,
            guild_id=guild_id,
            creator_id=creator_id,
            channel_id=channel_id,
            message_id=None,
            title=title,
            description=description,
            image_url=image_url,
            winner_count=winner_count,
            status="active",
            winner_ids="",
            end_at=end_at,
        )
        session.add(giveaway)
        await session.commit()
        await session.refresh(giveaway)
        return _giveaway_to_dict(giveaway)


async def update_giveaway_message_id(giveaway_id: str, message_id: int) -> dict | None:
    async with async_session() as session:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        stmt = (
            select(Giveaway)
            .where(Giveaway.id == giveaway_id)
            .options(selectinload(Giveaway.entries))
        )
        result = await session.execute(stmt)
        giveaway = result.scalar_one_or_none()
        if giveaway is None:
            return None
        giveaway.message_id = message_id
        await session.commit()
        await session.refresh(giveaway)
        return _giveaway_to_dict(giveaway)


def _giveaway_to_dict(g: Giveaway) -> dict:
    try:
        entries = sorted(int(e.user_id) for e in (g.entries or []))
    except Exception:
        entries = []
    winner_ids = [int(x) for x in (g.winner_ids or "").split(",") if x]
    return {
        "id": g.id,
        "giveaway_id": g.id,
        "guild_id": g.guild_id,
        "creator_id": g.creator_id,
        "channel_id": g.channel_id,
        "message_id": g.message_id,
        "title": g.title,
        "description": g.description,
        "image_url": g.image_url,
        "winner_count": g.winner_count,
        "status": g.status,
        "winner_ids": winner_ids,
        "winners_posted": bool(getattr(g, "winners_posted", False)),
        "entries": entries,
        "created_at": g.created_at,
        "end_at": g.end_at,
        "end_at_iso": datetime.fromtimestamp(g.end_at, tz=timezone.utc).isoformat(),
    }


async def toggle_giveaway_entry(giveaway_id: str, user_id: int) -> tuple[dict | None, bool]:
    """Returns (giveaway_dict, joined). joined=True if user is now entered."""
    async with async_session() as session:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        stmt = select(GiveawayEntry).where(
            GiveawayEntry.giveaway_id == giveaway_id,
            GiveawayEntry.user_id == user_id,
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing is not None:
            await session.delete(existing)
            await session.commit()
        else:
            entry = GiveawayEntry(giveaway_id=giveaway_id, user_id=user_id)
            session.add(entry)
            await session.commit()

        stmt = (
            select(Giveaway)
            .where(Giveaway.id == giveaway_id)
            .options(selectinload(Giveaway.entries))
        )
        result = await session.execute(stmt)
        giveaway = result.scalar_one_or_none()
        if giveaway is None:
            return None, False
        return _giveaway_to_dict(giveaway), existing is None


async def cancel_giveaway(giveaway_id: str) -> dict | None:
    async with async_session() as session:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        stmt = (
            select(Giveaway)
            .where(Giveaway.id == giveaway_id)
            .options(selectinload(Giveaway.entries))
        )
        result = await session.execute(stmt)
        giveaway = result.scalar_one_or_none()
        if giveaway is None:
            return None
        if giveaway.status == "active":
            giveaway.status = "cancelled"
            await session.commit()
            await session.refresh(giveaway)
        return _giveaway_to_dict(giveaway)


async def end_giveaway(giveaway_id: str, winner_ids: list[int]) -> dict | None:
    async with async_session() as session:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        stmt = (
            select(Giveaway)
            .where(Giveaway.id == giveaway_id)
            .options(selectinload(Giveaway.entries))
        )
        result = await session.execute(stmt)
        giveaway = result.scalar_one_or_none()
        if giveaway is None:
            return None
        if giveaway.status != "active":
            return _giveaway_to_dict(giveaway)
        giveaway.status = "ended"
        giveaway.winner_ids = ",".join(str(w) for w in winner_ids)
        await session.commit()
        await session.refresh(giveaway)
        return _giveaway_to_dict(giveaway)


async def mark_winners_posted(giveaway_id: str) -> bool:
    async with async_session() as session:
        giveaway = await session.get(Giveaway, giveaway_id)
        if giveaway is None:
            return False
        giveaway.winners_posted = True
        await session.commit()
        return True


async def list_ended_unposted_giveaways() -> list[dict]:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    async with async_session() as session:
        stmt = (
            select(Giveaway)
            .where(Giveaway.status == "ended", Giveaway.winners_posted.is_(False))
            .options(selectinload(Giveaway.entries))
            .order_by(Giveaway.end_at.asc())
        )
        result = await session.execute(stmt)
        return [_giveaway_to_dict(g) for g in result.scalars().all()]


async def create_exchange(
    *,
    id: str,
    giveaway_id: str,
    guild_id: int,
    winner_id: int,
    creator_id: int,
    channel_id: int,
    exchange_message_id: int | None = None,
    winners_message_id: int | None = None,
) -> GiveawayExchange:
    async with async_session() as session:
        exchange = GiveawayExchange(
            id=id,
            giveaway_id=giveaway_id,
            guild_id=guild_id,
            winner_id=winner_id,
            creator_id=creator_id,
            channel_id=channel_id,
            exchange_message_id=exchange_message_id,
            winners_message_id=winners_message_id,
            status="pending",
            winner_confirmed=False,
            creator_confirmed=False,
        )
        session.add(exchange)
        await session.commit()
        await session.refresh(exchange)
        return exchange


async def update_exchange_message_ids(
    exchange_id: str,
    *,
    exchange_message_id: int | None = None,
    winners_message_id: int | None = None,
    guild_id: int | None = None,
) -> GiveawayExchange | None:
    async with async_session() as session:
        exchange = await session.get(GiveawayExchange, exchange_id)
        if exchange is None:
            return None
        if exchange_message_id is not None:
            exchange.exchange_message_id = exchange_message_id
        if winners_message_id is not None:
            exchange.winners_message_id = winners_message_id
        if guild_id is not None and (not exchange.guild_id or exchange.guild_id == 0):
            exchange.guild_id = guild_id
        await session.commit()
        await session.refresh(exchange)
        return exchange


async def get_exchange(id: str) -> GiveawayExchange | None:
    async with async_session() as session:
        return await session.get(GiveawayExchange, id)


async def get_exchange_by_winner(giveaway_id: str, winner_id: int) -> GiveawayExchange | None:
    from sqlalchemy import select

    async with async_session() as session:
        stmt = select(GiveawayExchange).where(
            GiveawayExchange.giveaway_id == giveaway_id,
            GiveawayExchange.winner_id == winner_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


async def list_pending_exchanges() -> list[GiveawayExchange]:
    from sqlalchemy import select

    async with async_session() as session:
        stmt = select(GiveawayExchange).where(GiveawayExchange.status == "pending")
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def list_exchanges_for_giveaway(giveaway_id: str) -> list[GiveawayExchange]:
    from sqlalchemy import select

    async with async_session() as session:
        stmt = select(GiveawayExchange).where(GiveawayExchange.giveaway_id == giveaway_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def confirm_exchange(id: str, by: str) -> GiveawayExchange | None:
    async with async_session() as session:
        exchange = await session.get(GiveawayExchange, id)
        if exchange is None:
            return None
        if by == "winner":
            exchange.winner_confirmed = True
        elif by == "creator":
            exchange.creator_confirmed = True
        if exchange.winner_confirmed and exchange.creator_confirmed:
            exchange.status = "completed"
            from datetime import datetime as _dt
            exchange.closed_at = int(_dt.utcnow().timestamp())
        await session.commit()
        await session.refresh(exchange)
        return exchange


async def cancel_exchange(id: str) -> GiveawayExchange | None:
    from datetime import datetime as _dt

    async with async_session() as session:
        exchange = await session.get(GiveawayExchange, id)
        if exchange is None:
            return None
        if exchange.status == "pending":
            exchange.status = "cancelled"
            exchange.closed_at = int(_dt.utcnow().timestamp())
            await session.commit()
            await session.refresh(exchange)
        return exchange


# ─── Role Picker ──────────────────────────────────────────────────────────────────

async def get_role_picker_settings(guild_id: int) -> RolePickerSettings | None:
    async with async_session() as session:
        return await session.get(RolePickerSettings, guild_id)


async def upsert_role_picker_settings(guild_id: int) -> RolePickerSettings:
    await upsert_guild(guild_id)
    async with async_session() as session:
        existing = await session.get(RolePickerSettings, guild_id)
        if existing is None:
            existing = RolePickerSettings(guild_id=guild_id)
            session.add(existing)
        existing.updated_at = int(datetime.utcnow().timestamp())
        await session.commit()
        await session.refresh(existing)
        return existing


async def update_role_picker_admin_panel_channel(guild_id: int, channel_id: int | None) -> RolePickerSettings:
    await upsert_guild(guild_id)
    async with async_session() as session:
        existing = await session.get(RolePickerSettings, guild_id)
        if existing is None:
            existing = RolePickerSettings(guild_id=guild_id)
            session.add(existing)
        existing.admin_panel_channel_id = channel_id
        existing.updated_at = int(datetime.utcnow().timestamp())
        await session.commit()
        await session.refresh(existing)
        return existing


async def update_role_picker_admin_panel_message(guild_id: int, message_id: int | None) -> RolePickerSettings | None:
    async with async_session() as session:
        existing = await session.get(RolePickerSettings, guild_id)
        if existing is None:
            return None
        existing.admin_panel_message_id = message_id
        existing.updated_at = int(datetime.utcnow().timestamp())
        await session.commit()
        await session.refresh(existing)
        return existing


async def update_role_picker_public_panel_channel(guild_id: int, channel_id: int | None) -> RolePickerSettings:
    await upsert_guild(guild_id)
    async with async_session() as session:
        existing = await session.get(RolePickerSettings, guild_id)
        if existing is None:
            existing = RolePickerSettings(guild_id=guild_id)
            session.add(existing)
        existing.public_panel_channel_id = channel_id
        existing.updated_at = int(datetime.utcnow().timestamp())
        await session.commit()
        await session.refresh(existing)
        return existing


async def update_role_picker_public_panel_message(guild_id: int, message_id: int | None) -> RolePickerSettings | None:
    async with async_session() as session:
        existing = await session.get(RolePickerSettings, guild_id)
        if existing is None:
            return None
        existing.public_panel_message_id = message_id
        existing.updated_at = int(datetime.utcnow().timestamp())
        await session.commit()
        await session.refresh(existing)
        return existing


async def get_role_picker_roles(guild_id: int) -> list[dict]:
    from sqlalchemy import select

    async with async_session() as session:
        stmt = select(RolePickerRole).where(RolePickerRole.guild_id == guild_id).order_by(RolePickerRole.position.asc())
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [
            {
                "guild_id": r.guild_id,
                "position": r.position,
                "role_id": r.role_id,
                "label": r.label,
                "emoji": r.emoji,
                "description": r.description,
                "created_at": r.created_at,
            }
            for r in rows
        ]


async def upsert_role_picker_role(
    guild_id: int,
    position: int,
    role_id: int,
    label: str,
    emoji: str | None,
    description: str | None,
) -> dict:
    await upsert_guild(guild_id)
    async with async_session() as session:
        existing = await session.get(RolePickerRole, (guild_id, position))
        if existing is None:
            existing = RolePickerRole(
                guild_id=guild_id,
                position=position,
                role_id=role_id,
                label=label,
                emoji=emoji,
                description=description,
            )
            session.add(existing)
        else:
            existing.role_id = role_id
            existing.label = label
            existing.emoji = emoji
            existing.description = description
        await session.commit()
        await session.refresh(existing)
        return {
            "guild_id": existing.guild_id,
            "position": existing.position,
            "role_id": existing.role_id,
            "label": existing.label,
            "emoji": existing.emoji,
            "description": existing.description,
            "created_at": existing.created_at,
        }


async def delete_role_picker_role(guild_id: int, position: int) -> bool:
    from sqlalchemy import select

    async with async_session() as session:
        row = await session.get(RolePickerRole, (guild_id, position))
        if row is None:
            return False
        await session.delete(row)
        stmt = select(RolePickerRole).where(
            RolePickerRole.guild_id == guild_id, RolePickerRole.position > position
        ).order_by(RolePickerRole.position.asc())
        result = await session.execute(stmt)
        for r in result.scalars().all():
            r.position = r.position - 1
        await session.commit()
        return True


async def count_role_picker_roles(guild_id: int) -> int:
    from sqlalchemy import func, select

    async with async_session() as session:
        stmt = select(func.count(RolePickerRole.guild_id)).where(RolePickerRole.guild_id == guild_id)
        result = await session.execute(stmt)
        return int(result.scalar() or 0)


async def list_role_picker_settings_with_public_panel() -> list[int]:
    from sqlalchemy import select

    async with async_session() as session:
        stmt = select(RolePickerSettings.guild_id).where(
            RolePickerSettings.public_panel_channel_id.isnot(None)
        )
        result = await session.execute(stmt)
        return [int(row[0]) for row in result.all()]


async def list_role_picker_settings_with_admin_panel() -> list[int]:
    from sqlalchemy import select

    async with async_session() as session:
        stmt = select(RolePickerSettings.guild_id).where(
            RolePickerSettings.admin_panel_channel_id.isnot(None)
        )
        result = await session.execute(stmt)
        return [int(row[0]) for row in result.all()]
