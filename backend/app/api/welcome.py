from fastapi import HTTPException
from pydantic import BaseModel

from app.db import get_welcome_settings, upsert_welcome_settings


class WelcomeSettingsRequest(BaseModel):
    guild_id: int
    channel_id: int
    message: str
    enabled: bool = False


class WelcomeSettingsResponse(BaseModel):
    guild_id: int
    channel_id: int
    message: str
    enabled: bool
    updated_at: int


async def get_settings(guild_id: int) -> WelcomeSettingsResponse:
    settings = await get_welcome_settings(guild_id)
    if settings is None:
        raise HTTPException(status_code=404, detail="Welcome settings not configured for this server")
    return WelcomeSettingsResponse(
        guild_id=settings.guild_id,
        channel_id=settings.channel_id,
        message=settings.message,
        enabled=settings.enabled,
        updated_at=settings.updated_at,
    )


async def create_or_update_settings(request: WelcomeSettingsRequest) -> WelcomeSettingsResponse:
    settings = await upsert_welcome_settings(
        guild_id=request.guild_id,
        channel_id=request.channel_id,
        message=request.message,
        enabled=request.enabled,
    )
    return WelcomeSettingsResponse(
        guild_id=settings.guild_id,
        channel_id=settings.channel_id,
        message=settings.message,
        enabled=settings.enabled,
        updated_at=settings.updated_at,
    )
