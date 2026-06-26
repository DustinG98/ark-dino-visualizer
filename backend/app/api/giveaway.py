import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field, conint

from app.db import (
    Giveaway,
    GiveawayExchange,
    GiveawaySettings,
    cancel_exchange,
    cancel_giveaway,
    confirm_exchange,
    count_active_giveaways_in_window,
    create_exchange,
    create_giveaway,
    end_giveaway,
    get_exchange,
    get_exchange_by_winner,
    get_giveaway,
    get_giveaway_settings,
    list_active_giveaways_for_guild,
    list_active_giveaways_global,
    list_ended_unposted_giveaways,
    list_exchanges_for_giveaway,
    list_pending_exchanges,
    mark_winners_posted,
    toggle_giveaway_entry,
    update_exchange_message_ids,
    update_giveaway_category,
    update_giveaway_message_id,
    update_giveaway_admin_panel_channel,
    update_giveaway_admin_panel_message,
    update_giveaway_public_panel_channel,
    update_giveaway_public_panel_message,
    update_giveaway_ping_role,
    upsert_giveaway_settings,
)


log = logging.getLogger(__name__)


router = APIRouter(prefix="/api/giveaway")


MAX_TITLE_LEN = 200
MAX_DESCRIPTION_LEN = 1000
MAX_WINNER_COUNT = 20
MAX_DURATION_SECONDS = 30 * 24 * 60 * 60
MIN_DURATION_SECONDS = 60
RATE_LIMIT_WINDOW_SECONDS = 60 * 60
RATE_LIMIT_MAX_ACTIVE = 5


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _serialize(g, entries: list[int] | None = None) -> dict:
    """Accept either a Giveaway ORM object or a plain dict (from db layer)."""
    if isinstance(g, dict):
        return g
    if entries is None:
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
        "entries": entries,
        "created_at": g.created_at,
        "end_at": g.end_at,
        "end_at_iso": _iso(g.end_at),
    }


def _serialize_settings(s: GiveawaySettings) -> dict:
    return {
        "guild_id": s.guild_id,
        "enabled": s.enabled,
        "channel_id": s.channel_id,
        "category_id": s.category_id,
        "ping_role_id": getattr(s, "ping_role_id", None),
        "admin_panel_channel_id": getattr(s, "admin_panel_channel_id", None),
        "admin_panel_message_id": getattr(s, "admin_panel_message_id", None),
        "public_panel_channel_id": getattr(s, "public_panel_channel_id", None),
        "public_panel_message_id": getattr(s, "public_panel_message_id", None),
        "updated_at": s.updated_at,
    }


def _serialize_exchange(e: GiveawayExchange) -> dict:
    return {
        "id": e.id,
        "exchange_id": e.id,
        "giveaway_id": e.giveaway_id,
        "guild_id": e.guild_id,
        "winner_id": e.winner_id,
        "creator_id": e.creator_id,
        "channel_id": e.channel_id,
        "exchange_message_id": getattr(e, "exchange_message_id", None),
        "winners_message_id": getattr(e, "winners_message_id", None),
        "status": e.status,
        "winner_confirmed": e.winner_confirmed,
        "creator_confirmed": e.creator_confirmed,
        "created_at": e.created_at,
        "closed_at": e.closed_at,
    }


class GiveawaySettingsRequest(BaseModel):
    guild_id: int
    enabled: bool
    channel_id: int | None = None
    category_id: int | None = None


class GiveawaySettingsResponse(BaseModel):
    guild_id: int
    enabled: bool
    channel_id: int | None
    updated_at: int


class GiveawayCreateRequest(BaseModel):
    guild_id: int
    creator_id: int
    channel_id: int
    title: str = Field(..., min_length=1, max_length=MAX_TITLE_LEN)
    description: str = Field("", max_length=MAX_DESCRIPTION_LEN)
    image_url: str | None = None
    winner_count: int = Field(1, ge=1, le=MAX_WINNER_COUNT)
    end_at: str
    message_id: int | None = None


class GiveawayUpdateRequest(BaseModel):
    message_id: int | None = None


class EnterRequest(BaseModel):
    user_id: int


class EndRequest(BaseModel):
    winner_ids: list[int] = []


@router.get("/settings/{guild_id}")
async def get_settings(guild_id: Annotated[int, Path(ge=0)]) -> dict:
    settings = await get_giveaway_settings(guild_id)
    if settings is None:
        raise HTTPException(status_code=404, detail="Giveaway settings not configured for this server")
    return _serialize_settings(settings)


@router.post("/settings")
async def set_settings(request: GiveawaySettingsRequest) -> dict:
    settings = await upsert_giveaway_settings(
        guild_id=request.guild_id,
        enabled=request.enabled,
        channel_id=request.channel_id,
    )
    if request.category_id is not None:
        settings = await update_giveaway_category(request.guild_id, request.category_id)
    return _serialize_settings(settings)


@router.post("/settings/category")
async def set_category(guild_id: int, category_id: int | None = None) -> dict:
    settings = await update_giveaway_category(guild_id, category_id)
    return _serialize_settings(settings)


@router.post("/settings/ping-role")
async def set_ping_role(guild_id: int, ping_role_id: int | None = None) -> dict:
    settings = await update_giveaway_ping_role(guild_id, ping_role_id)
    return _serialize_settings(settings)


@router.post("/settings/admin-panel-channel")
async def set_admin_panel_channel(guild_id: int, channel_id: int | None = None) -> dict:
    settings = await update_giveaway_admin_panel_channel(guild_id, channel_id)
    return _serialize_settings(settings)


@router.post("/settings/admin-panel-message")
async def set_admin_panel_message(guild_id: int, message_id: int | None = None) -> dict:
    settings = await update_giveaway_admin_panel_message(guild_id, message_id)
    if settings is None:
        raise HTTPException(status_code=404, detail="Guild settings not found")
    return _serialize_settings(settings)


@router.post("/settings/public-panel-channel")
async def set_public_panel_channel(guild_id: int, channel_id: int | None = None) -> dict:
    settings = await update_giveaway_public_panel_channel(guild_id, channel_id)
    return _serialize_settings(settings)


@router.post("/settings/public-panel-message")
async def set_public_panel_message(guild_id: int, message_id: int | None = None) -> dict:
    settings = await update_giveaway_public_panel_message(guild_id, message_id)
    if settings is None:
        raise HTTPException(status_code=404, detail="Guild settings not found")
    return _serialize_settings(settings)


@router.get("/exchanges")
async def list_exchanges(
    status: str | None = Query(None),
    giveaway_id: str | None = Query(None),
    winner_id: int | None = Query(None),
) -> dict:
    if giveaway_id is not None and winner_id is not None:
        exchange = await get_exchange_by_winner(giveaway_id, winner_id)
        if exchange is None:
            return {"exchanges": []}
        return {"exchanges": [_serialize_exchange(exchange)]}
    if giveaway_id is not None:
        exchanges = await list_exchanges_for_giveaway(giveaway_id)
        if status:
            exchanges = [e for e in exchanges if e.status == status]
        return {"exchanges": [_serialize_exchange(e) for e in exchanges]}
    exchanges = await list_pending_exchanges()
    if status and status != "pending":
        exchanges = [e for e in exchanges if e.status == status]
    return {"exchanges": [_serialize_exchange(e) for e in exchanges]}


@router.get("/exchanges/{exchange_id}")
async def get_exchange_one(exchange_id: str) -> dict:
    exchange = await get_exchange(exchange_id)
    if exchange is None:
        raise HTTPException(status_code=404, detail="Exchange not found")
    return _serialize_exchange(exchange)


class ClaimRequest(BaseModel):
    giveaway_id: str
    winner_id: int
    creator_id: int
    channel_id: int
    guild_id: int | None = None
    exchange_message_id: int | None = None
    winners_message_id: int | None = None


class ExchangeMessageUpdate(BaseModel):
    exchange_message_id: int | None = None
    winners_message_id: int | None = None


class ConfirmRequest(BaseModel):
    by: str


@router.post("/exchanges")
async def open_exchange(request: ClaimRequest) -> dict:
    import uuid as _uuid
    existing = await get_exchange_by_winner(request.giveaway_id, request.winner_id)
    if existing is not None:
        existing_id = existing.id if hasattr(existing, "id") else existing["id"]
        existing_guild_id = existing.guild_id if hasattr(existing, "guild_id") else existing.get("guild_id")
        if (
            request.exchange_message_id is not None
            or request.winners_message_id is not None
            or (request.guild_id and (not existing_guild_id or existing_guild_id == 0))
        ):
            updated = await update_exchange_message_ids(
                existing_id,
                exchange_message_id=request.exchange_message_id,
                winners_message_id=request.winners_message_id,
                guild_id=request.guild_id,
            )
            if updated is not None:
                return _serialize_exchange(updated)
        return _serialize_exchange(existing)
    exchange = await create_exchange(
        id=_uuid.uuid4().hex[:12],
        giveaway_id=request.giveaway_id,
        guild_id=request.guild_id or 0,
        winner_id=request.winner_id,
        creator_id=request.creator_id,
        channel_id=request.channel_id,
        exchange_message_id=request.exchange_message_id,
        winners_message_id=request.winners_message_id,
    )
    return _serialize_exchange(exchange)


@router.patch("/exchanges/{exchange_id}/messages")
async def update_exchange_messages(exchange_id: str, request: ExchangeMessageUpdate) -> dict:
    updated = await update_exchange_message_ids(
        exchange_id,
        exchange_message_id=request.exchange_message_id,
        winners_message_id=request.winners_message_id,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Exchange not found")
    return _serialize_exchange(updated)


@router.post("/exchanges/{exchange_id}/confirm")
async def confirm(exchange_id: str, request: ConfirmRequest) -> dict:
    if request.by not in ("winner", "creator"):
        raise HTTPException(status_code=400, detail="by must be 'winner' or 'creator'")
    exchange = await confirm_exchange(exchange_id, request.by)
    if exchange is None:
        raise HTTPException(status_code=404, detail="Exchange not found")
    return _serialize_exchange(exchange)


@router.post("/exchanges/{exchange_id}/cancel")
async def cancel_exch(exchange_id: str) -> dict:
    exchange = await cancel_exchange(exchange_id)
    if exchange is None:
        raise HTTPException(status_code=404, detail="Exchange not found")
    return _serialize_exchange(exchange)


@router.get("/active")
async def list_active_global() -> dict:
    giveaways = await list_active_giveaways_global()
    return {"giveaways": [_serialize(g) for g in giveaways]}


@router.get("/active/{guild_id}")
async def list_active_for_guild(guild_id: Annotated[int, Path(ge=0)]) -> dict:
    giveaways = await list_active_giveaways_for_guild(guild_id)
    return {"giveaways": [_serialize(g) for g in giveaways]}


@router.post("")
async def create(request: GiveawayCreateRequest) -> dict:
    try:
        end_at_dt = datetime.fromisoformat(request.end_at.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid end_at timestamp")
    if end_at_dt.tzinfo is None:
        end_at_dt = end_at_dt.replace(tzinfo=timezone.utc)
    end_at_ts = int(end_at_dt.timestamp())
    now_ts = int(datetime.now(timezone.utc).timestamp())

    if end_at_ts - now_ts < MIN_DURATION_SECONDS:
        raise HTTPException(status_code=400, detail="Giveaway duration is too short")
    if end_at_ts - now_ts > MAX_DURATION_SECONDS:
        raise HTTPException(status_code=400, detail="Giveaway duration exceeds 30 days")

    settings = await get_giveaway_settings(request.guild_id)
    if settings is None or not settings.enabled:
        raise HTTPException(status_code=400, detail="Giveaways are not enabled in this server")

    window_start = now_ts - RATE_LIMIT_WINDOW_SECONDS
    active_count = await count_active_giveaways_in_window(request.guild_id, window_start)
    if active_count >= RATE_LIMIT_MAX_ACTIVE:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit: at most {RATE_LIMIT_MAX_ACTIVE} active giveaways per hour per guild",
        )

    giveaway_id = uuid.uuid4().hex[:12]
    giveaway = await create_giveaway(
        id=giveaway_id,
        guild_id=request.guild_id,
        creator_id=request.creator_id,
        channel_id=request.channel_id,
        title=request.title,
        description=request.description,
        image_url=request.image_url,
        winner_count=request.winner_count,
        end_at=end_at_ts,
    )
    log.info("created giveaway %s for guild %s by user %s", giveaway_id, request.guild_id, request.creator_id)
    return _serialize(giveaway)


@router.get("/ended-unposted")
async def ended_unposted() -> dict:
    giveaways = await list_ended_unposted_giveaways()
    return {"giveaways": [_serialize(g) for g in giveaways]}


@router.get("/{giveaway_id}")
async def get_one(giveaway_id: str) -> dict:
    giveaway = await get_giveaway(giveaway_id)
    if giveaway is None:
        raise HTTPException(status_code=404, detail="Giveaway not found")
    return _serialize(giveaway)


@router.patch("/{giveaway_id}")
async def update(giveaway_id: str, request: GiveawayUpdateRequest) -> dict:
    if request.message_id is None:
        raise HTTPException(status_code=400, detail="No fields to update")
    giveaway = await update_giveaway_message_id(giveaway_id, request.message_id)
    if giveaway is None:
        raise HTTPException(status_code=404, detail="Giveaway not found")
    return _serialize(giveaway)


@router.post("/{giveaway_id}/enter")
async def enter(giveaway_id: str, request: EnterRequest) -> dict:
    giveaway, joined = await toggle_giveaway_entry(giveaway_id, request.user_id)
    if giveaway is None:
        raise HTTPException(status_code=404, detail="Giveaway not found")
    return {"giveaway": _serialize(giveaway), "joined": joined}


@router.post("/{giveaway_id}/leave")
async def leave(giveaway_id: str, request: EnterRequest) -> dict:
    giveaway, joined = await toggle_giveaway_entry(giveaway_id, request.user_id)
    if giveaway is None:
        raise HTTPException(status_code=404, detail="Giveaway not found")
    return {"giveaway": _serialize(giveaway), "joined": joined}


@router.post("/{giveaway_id}/cancel")
async def cancel(giveaway_id: str) -> dict:
    giveaway = await cancel_giveaway(giveaway_id)
    if giveaway is None:
        raise HTTPException(status_code=404, detail="Giveaway not found")
    return _serialize(giveaway)


@router.post("/{giveaway_id}/end")
async def end(giveaway_id: str, request: EndRequest) -> dict:
    giveaway = await get_giveaway(giveaway_id)
    if giveaway is None:
        raise HTTPException(status_code=404, detail="Giveaway not found")
    if giveaway.get("status") != "active":
        return _serialize(giveaway)
    winner_ids = [int(w) for w in request.winner_ids if int(w) > 0]
    giveaway = await end_giveaway(giveaway_id, winner_ids)
    return _serialize(giveaway)


@router.post("/{giveaway_id}/winners-posted")
async def winners_posted(giveaway_id: str) -> dict:
    ok = await mark_winners_posted(giveaway_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Giveaway not found")
    return {"ok": True}