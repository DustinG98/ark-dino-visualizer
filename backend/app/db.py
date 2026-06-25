import os
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, ForeignKey, BigInteger, Boolean
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.pool import NullPool

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


class WelcomeMessage(Base):
    __tablename__ = "welcome_messages"

    guild_id = Column(BigInteger, ForeignKey("guilds.guild_id"), primary_key=True)
    channel_id = Column(BigInteger, nullable=False)
    message = Column(Text, nullable=False)
    enabled = Column(Boolean, nullable=False, default=False)
    updated_at = Column(Integer, nullable=False, default=lambda: int(datetime.utcnow().timestamp()))

    guild = relationship("Guild", back_populates="welcome_message")


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


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
