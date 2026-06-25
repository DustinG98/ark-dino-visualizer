from contextlib import asynccontextmanager
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from app.api.dinos import (
    get_dino_list,
    apply_region_color,
    load_color_lut,
    load_color_entries,
    load_region_mappings,
    DINO_IMAGE_DIR,
)
from app.api.welcome import get_settings, create_or_update_settings, WelcomeSettingsRequest
from app.config import ALLOWED_ORIGINS, configure_logging
from app.db import init_db
from pydantic import BaseModel


configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="Ark Dino Visualizer",
    version="0.1.0",
    description="ARK ASA Dino Visualizer",
    lifespan=lifespan,
)


class RenderRequest(BaseModel):
    dinoName: str
    regionColors: dict[int, int]


@app.get("/")
def ping():
    return {"status": "ok"}


@app.get("/api/dinos")
def list_dinos(search: str | None = Query(None)):
    return get_dino_list(search)


@app.get("/api/dinos/colors")
def get_colors():
    return load_color_entries()


@app.get("/api/dinos/regions")
def get_regions():
    return {"regions": load_region_mappings()}


@app.post("/api/dinos/render")
def render_dino(request: RenderRequest):
    image_path = DINO_IMAGE_DIR / request.dinoName

    if not image_path.exists():
        return Response(content="Dino not found", status_code=404)

    mask_path = image_path.with_name(image_path.stem + "_m.png")
    if not mask_path.exists():
        return Response(content="Mask not found", status_code=404)

    from PIL import Image
    image = Image.open(image_path)
    mask = Image.open(mask_path)

    color_lut = load_color_lut()

    result = apply_region_color(image, mask, request.regionColors, color_lut)

    import io
    buf = io.BytesIO()
    result.save(buf, format="PNG")
    buf.seek(0)

    return Response(content=buf.getvalue(), media_type="image/png")


@app.get("/api/welcome/{guild_id}")
async def get_welcome(guild_id: int):
    return await get_settings(guild_id)


@app.post("/api/welcome")
async def set_welcome(request: WelcomeSettingsRequest):
    return await create_or_update_settings(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
