import asyncio
import logging
from typing import Any

from .backend_client import BackendClient, BackendError


log = logging.getLogger(__name__)


CACHE_REFRESH_SECONDS = 600
STARTUP_RETRY_SECONDS = 30


class Cache:
    def __init__(self, client: BackendClient):
        self._client = client
        self._dinos: list[dict] = []
        self._colors: list[dict] = []
        self._regions: list[dict] = []
        self._color_swatch_images: list[bytes] | None = None
        self._warm = False
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None

    @property
    def warm(self) -> bool:
        return self._warm

    @property
    def dinos(self) -> list[dict]:
        return self._dinos

    @property
    def colors(self) -> list[dict]:
        return self._colors

    @property
    def regions(self) -> list[dict]:
        return self._regions

    def _build_color_swatch(self) -> list[bytes]:
        import io
        from PIL import Image, ImageDraw, ImageFont

        colors = self._colors
        num_images = 4
        chunk_size = (len(colors) + num_images - 1) // num_images
        chunks = [colors[i : i + chunk_size] for i in range(0, len(colors), chunk_size)]

        swatch_size = 18
        row_h = swatch_size + 12
        col_id = 4
        col_swatch = col_id + 36
        col_name = col_swatch + swatch_size + 10
        col_w = 200
        num_cols = 4
        img_w = num_cols * col_w + 8
        max_chunk_len = max((len(c) + num_cols - 1) // num_cols for c in chunks) if chunks else 1
        img_h = max_chunk_len * row_h + 8

        font = ImageFont.load_default()
        results = []

        for img_idx, chunk in enumerate(chunks):
            img = Image.new("RGB", (img_w, img_h), (30, 30, 30))
            draw = ImageDraw.Draw(img)

            for idx, color in enumerate(chunk):
                col = idx % num_cols
                row = idx // num_cols
                x = 6 + col * col_w
                y = 6 + row * row_h

                color_id = color.get("ID", "?")
                draw.text((x + col_id, y + 2), f"#{color_id}", fill=(160, 160, 160), font=font)

                hex_str = str(color.get("Hex") or color.get("hex") or "#888888").lstrip("#")
                rgb = (int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16))
                draw.rectangle([x + col_swatch, y, x + col_swatch + swatch_size, y + swatch_size], fill=rgb)

                name = str(color.get("Name") or color.get("name") or "").strip()
                draw.text((x + col_name, y + 2), name, fill=(160, 160, 160), font=font)

            for c in range(1, num_cols):
                line_x = 6 + c * col_w - 2
                draw.line([(line_x, 0), (line_x, img_h)], fill=(60, 60, 60), width=1)

            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            results.append(buf.getvalue())

        return results

    @property
    def color_swatch_images(self) -> list[bytes]:
        if self._color_swatch_images is None:
            self._color_swatch_images = self._build_color_swatch()
        return self._color_swatch_images

    def find_dino(self, name: str) -> dict | None:
        target = name.lower()
        for d in self._dinos:
            if d["name"].lower() == target:
                return d
        return None

    def search_dinos(self, term: str, limit: int = 10) -> list[dict]:
        needle = term.lower()
        results = [d for d in self._dinos if any(needle in t for t in d.get("searchTerms", []))]
        return results[:limit]

    async def _refresh_once(self) -> bool:
        try:
            dinos, colors, regions = await asyncio.gather(
                self._client.list_dinos(),
                self._client.list_colors(),
                self._client.list_regions(),
            )
        except BackendError as exc:
            log.warning("backend returned error during cache refresh: %s", exc)
            return False
        except Exception as exc:
            log.warning("backend unreachable during cache refresh: %s", exc)
            return False

        async with self._lock:
            self._dinos = dinos
            self._colors = colors
            self._regions = regions
            self._warm = True
        log.info("cache refreshed: %d dinos, %d colors, %d regions", len(dinos), len(colors), len(regions))
        return True

    async def warm_up(self) -> None:
        while not self._warm:
            ok = await self._refresh_once()
            if ok:
                return
            await asyncio.sleep(STARTUP_RETRY_SECONDS)

    async def start_background_refresh(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._refresh_loop(), name="cache-refresh")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _refresh_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(CACHE_REFRESH_SECONDS)
                await self._refresh_once()
        except asyncio.CancelledError:
            return
