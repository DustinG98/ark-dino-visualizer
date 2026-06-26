from typing import Annotated
from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, Field

from app.db import (
    get_role_picker_settings,
    update_role_picker_admin_panel_channel,
    update_role_picker_admin_panel_message,
    update_role_picker_public_panel_channel,
    update_role_picker_public_panel_message,
    get_role_picker_roles,
    upsert_role_picker_role,
    delete_role_picker_role,
    count_role_picker_roles,
    upsert_role_picker_settings,
)


router = APIRouter(prefix="/api/role-picker")

MAX_ROLES = 25
MAX_LABEL_LEN = 80
MAX_DESCRIPTION_LEN = 100


class RoleAddRequest(BaseModel):
    guild_id: int
    role_id: int = Field(..., gt=0)
    label: str = Field(..., min_length=1, max_length=MAX_LABEL_LEN)
    emoji: str | None = Field(None, max_length=64)
    description: str | None = Field(None, max_length=MAX_DESCRIPTION_LEN)


class RoleEditRequest(BaseModel):
    label: str | None = Field(None, min_length=1, max_length=MAX_LABEL_LEN)
    emoji: str | None = Field(None, max_length=64)
    description: str | None = Field(None, max_length=MAX_DESCRIPTION_LEN)


class ReorderRequest(BaseModel):
    ordered_role_ids: list[int]


class PanelChannelRequest(BaseModel):
    guild_id: int
    channel_id: int | None = None


class PanelMessageRequest(BaseModel):
    guild_id: int
    message_id: int | None = None


def _serialize_settings(s) -> dict:
    return {
        "guild_id": s.guild_id,
        "admin_panel_channel_id": getattr(s, "admin_panel_channel_id", None),
        "admin_panel_message_id": getattr(s, "admin_panel_message_id", None),
        "public_panel_channel_id": getattr(s, "public_panel_channel_id", None),
        "public_panel_message_id": getattr(s, "public_panel_message_id", None),
        "updated_at": s.updated_at,
    }


@router.get("/roles/{guild_id}")
async def list_roles(guild_id: Annotated[int, Path(ge=0)]) -> dict:
    roles = await get_role_picker_roles(guild_id)
    return {"roles": roles}


@router.post("/roles")
async def add_role(request: RoleAddRequest) -> dict:
    count = await count_role_picker_roles(request.guild_id)
    if count >= MAX_ROLES:
        raise HTTPException(status_code=400, detail=f"Maximum of {MAX_ROLES} roles reached.")
    next_position = count
    result = await upsert_role_picker_role(
        guild_id=request.guild_id,
        position=next_position,
        role_id=request.role_id,
        label=request.label.strip(),
        emoji=request.emoji,
        description=request.description,
    )
    return result


@router.patch("/roles/{guild_id}/{position}")
async def edit_role(
    guild_id: Annotated[int, Path(ge=0)],
    position: int,
    request: RoleEditRequest,
) -> dict:
    roles = await get_role_picker_roles(guild_id)
    existing = next((r for r in roles if r["position"] == position), None)
    if existing is None:
        raise HTTPException(status_code=404, detail="Role not found at that position.")
    label = request.label.strip() if request.label is not None else existing["label"]
    emoji = request.emoji if request.emoji is not None else existing["emoji"]
    description = request.description if request.description is not None else existing["description"]
    result = await upsert_role_picker_role(
        guild_id=guild_id,
        position=position,
        role_id=existing["role_id"],
        label=label,
        emoji=emoji,
        description=description,
    )
    return result


@router.delete("/roles/{guild_id}/{position}")
async def remove_role(
    guild_id: Annotated[int, Path(ge=0)],
    position: int,
) -> dict:
    ok = await delete_role_picker_role(guild_id, position)
    if not ok:
        raise HTTPException(status_code=404, detail="Role not found at that position.")
    return {"ok": True}


@router.post("/roles/{guild_id}/reorder")
async def reorder_roles(guild_id: Annotated[int, Path(ge=0)], request: ReorderRequest) -> dict:
    roles = await get_role_picker_roles(guild_id)
    current_ids = [r["role_id"] for r in roles]
    if set(request.ordered_role_ids) != set(current_ids):
        raise HTTPException(status_code=400, detail="Reorder list must contain exactly the current role ids.")
    if len(request.ordered_role_ids) != len(current_ids):
        raise HTTPException(status_code=400, detail="Duplicate role ids in reorder list.")
    for new_pos, rid in enumerate(request.ordered_role_ids):
        existing = next(r for r in roles if r["role_id"] == rid)
        await upsert_role_picker_role(
            guild_id=guild_id,
            position=new_pos,
            role_id=rid,
            label=existing["label"],
            emoji=existing["emoji"],
            description=existing["description"],
        )
    return {"ok": True}


@router.post("/settings/admin-panel-channel")
async def set_admin_panel_channel(request: PanelChannelRequest) -> dict:
    s = await update_role_picker_admin_panel_channel(request.guild_id, request.channel_id)
    return _serialize_settings(s)


@router.post("/settings/admin-panel-message")
async def set_admin_panel_message(request: PanelMessageRequest) -> dict:
    s = await update_role_picker_admin_panel_message(request.guild_id, request.message_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Settings not found for this guild.")
    return _serialize_settings(s)


@router.post("/settings/public-panel-channel")
async def set_public_panel_channel(request: PanelChannelRequest) -> dict:
    s = await update_role_picker_public_panel_channel(request.guild_id, request.channel_id)
    return _serialize_settings(s)


@router.post("/settings/public-panel-message")
async def set_public_panel_message(request: PanelMessageRequest) -> dict:
    s = await update_role_picker_public_panel_message(request.guild_id, request.message_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Settings not found for this guild.")
    return _serialize_settings(s)


@router.get("/settings/{guild_id}")
async def get_settings(guild_id: Annotated[int, Path(ge=0)]) -> dict:
    s = await get_role_picker_settings(guild_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Role picker not configured for this server.")
    roles = await get_role_picker_roles(guild_id)
    result = _serialize_settings(s)
    result["roles"] = roles
    return result
