import io
import logging

import httpx


log = logging.getLogger(__name__)


class BackendError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"backend {status_code}: {message}")


class BackendClient:
    def __init__(self, base_url: str, timeout: float = 30.0):
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def ping(self) -> bool:
        try:
            resp = await self._client.get("/", timeout=5.0)
            return resp.status_code == 200
        except httpx.HTTPError as exc:
            log.warning("backend ping failed: %s", exc)
            return False

    async def list_dinos(self, search: str | None = None) -> list[dict]:
        params = {"search": search} if search else None
        resp = await self._client.get("/api/dinos", params=params)
        if resp.status_code != 200:
            raise BackendError(resp.status_code, resp.text or "list dinos failed")
        return resp.json()

    async def list_colors(self) -> list[dict]:
        resp = await self._client.get("/api/dinos/colors")
        if resp.status_code != 200:
            raise BackendError(resp.status_code, resp.text or "list colors failed")
        return resp.json()

    async def list_regions(self) -> list[dict]:
        resp = await self._client.get("/api/dinos/regions")
        if resp.status_code != 200:
            raise BackendError(resp.status_code, resp.text or "list regions failed")
        data = resp.json()
        return data.get("regions", [])

    async def render(self, dino_name: str, region_colors: dict[int, int]) -> bytes:
        payload = {"dinoName": dino_name, "regionColors": {int(k): int(v) for k, v in region_colors.items()}}
        resp = await self._client.post("/api/dinos/render", json=payload)
        if resp.status_code != 200:
            raise BackendError(resp.status_code, resp.text or "render failed")
        return resp.content


def is_too_large_for_discord(data: bytes, cap_bytes: int = 8 * 1024 * 1024) -> bool:
    return len(data) > cap_bytes


def convert_png_to_webp(png_bytes: bytes, quality: int = 90) -> bytes:
    from PIL import Image

    with Image.open(io.BytesIO(png_bytes)) as img:
        buf = io.BytesIO()
        img.save(buf, format="WEBP", quality=quality)
        return buf.getvalue()
