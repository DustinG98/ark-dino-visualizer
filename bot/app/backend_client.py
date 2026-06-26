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

    async def get_welcome_settings(self, guild_id: int) -> dict | None:
        resp = await self._client.get(f"/api/welcome/{guild_id}")
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise BackendError(resp.status_code, resp.text or "get welcome settings failed")
        return resp.json()

    async def set_welcome_settings(self, guild_id: int, channel_id: int, message: str, enabled: bool = False) -> dict:
        payload = {"guild_id": guild_id, "channel_id": channel_id, "message": message, "enabled": enabled}
        resp = await self._client.post("/api/welcome", json=payload)
        if resp.status_code != 200:
            raise BackendError(resp.status_code, resp.text or "set welcome settings failed")
        return resp.json()

    async def get_giveaway_settings(self, guild_id: int) -> dict | None:
        resp = await self._client.get(f"/api/giveaway/settings/{guild_id}")
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise BackendError(resp.status_code, resp.text or "get giveaway settings failed")
        return resp.json()

    async def set_giveaway_settings(self, guild_id: int, enabled: bool, channel_id: int | None = None) -> dict:
        payload: dict = {"guild_id": guild_id, "enabled": enabled}
        if channel_id is not None:
            payload["channel_id"] = channel_id
        resp = await self._client.post("/api/giveaway/settings", json=payload)
        if resp.status_code != 200:
            raise BackendError(resp.status_code, resp.text or "set giveaway settings failed")
        return resp.json()

    async def create_giveaway(
        self,
        guild_id: int,
        creator_id: int,
        channel_id: int,
        message_id: int | None,
        title: str,
        description: str,
        image_url: str | None,
        winner_count: int,
        end_at_iso: str,
    ) -> dict:
        payload = {
            "guild_id": guild_id,
            "creator_id": creator_id,
            "channel_id": channel_id,
            "message_id": message_id,
            "title": title,
            "description": description,
            "image_url": image_url,
            "winner_count": winner_count,
            "end_at": end_at_iso,
        }
        resp = await self._client.post("/api/giveaway", json=payload)
        if resp.status_code != 200:
            raise BackendError(resp.status_code, resp.text or "create giveaway failed")
        return resp.json()

    async def get_giveaway(self, giveaway_id: str) -> dict | None:
        resp = await self._client.get(f"/api/giveaway/{giveaway_id}")
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise BackendError(resp.status_code, resp.text or "get giveaway failed")
        return resp.json()

    async def list_active_giveaways(self, guild_id: int) -> list[dict]:
        resp = await self._client.get(f"/api/giveaway/active/{guild_id}")
        if resp.status_code != 200:
            raise BackendError(resp.status_code, resp.text or "list active giveaways failed")
        data = resp.json()
        return data.get("giveaways", []) if isinstance(data, dict) else data

    async def list_active_giveaways_for_sweep(self) -> list[dict]:
        resp = await self._client.get("/api/giveaway/active")
        if resp.status_code != 200:
            raise BackendError(resp.status_code, resp.text or "sweep giveaways failed")
        data = resp.json()
        return data.get("giveaways", []) if isinstance(data, dict) else data

    async def enter_giveaway(self, giveaway_id: str, user_id: int) -> dict:
        resp = await self._client.post(f"/api/giveaway/{giveaway_id}/enter", json={"user_id": user_id})
        if resp.status_code != 200:
            raise BackendError(resp.status_code, resp.text or "enter giveaway failed")
        return resp.json()

    async def leave_giveaway(self, giveaway_id: str, user_id: int) -> dict:
        resp = await self._client.post(f"/api/giveaway/{giveaway_id}/leave", json={"user_id": user_id})
        if resp.status_code != 200:
            raise BackendError(resp.status_code, resp.text or "leave giveaway failed")
        return resp.json()

    async def cancel_giveaway(self, giveaway_id: str) -> dict:
        resp = await self._client.post(f"/api/giveaway/{giveaway_id}/cancel")
        if resp.status_code != 200:
            raise BackendError(resp.status_code, resp.text or "cancel giveaway failed")
        return resp.json()

    async def end_giveaway(self, giveaway_id: str, winner_ids: list[int]) -> dict:
        resp = await self._client.post(
            f"/api/giveaway/{giveaway_id}/end",
            json={"winner_ids": winner_ids},
        )
        if resp.status_code != 200:
            raise BackendError(resp.status_code, resp.text or "end giveaway failed")
        return resp.json()

    async def update_giveaway_message_id(self, giveaway_id: str, message_id: int) -> dict:
        resp = await self._client.patch(
            f"/api/giveaway/{giveaway_id}",
            json={"message_id": message_id},
        )
        if resp.status_code != 200:
            raise BackendError(resp.status_code, resp.text or "update giveaway failed")
        return resp.json()

    async def mark_winners_posted(self, giveaway_id: str) -> dict:
        resp = await self._client.post(f"/api/giveaway/{giveaway_id}/winners-posted")
        if resp.status_code != 200:
            raise BackendError(resp.status_code, resp.text or "mark winners posted failed")
        return resp.json()

    async def list_ended_unposted(self) -> list[dict]:
        resp = await self._client.get("/api/giveaway/ended-unposted")
        if resp.status_code != 200:
            raise BackendError(resp.status_code, resp.text or "list ended unposted failed")
        data = resp.json()
        return data.get("giveaways", []) if isinstance(data, dict) else data

    async def update_giveaway_category(self, guild_id: int, category_id: int | None) -> dict:
        resp = await self._client.post(
            "/api/giveaway/settings/category",
            params={"guild_id": guild_id, "category_id": category_id} if category_id is not None else {"guild_id": guild_id},
        )
        if resp.status_code != 200:
            raise BackendError(resp.status_code, resp.text or "update category failed")
        return resp.json()

    async def update_giveaway_ping_role(self, guild_id: int, ping_role_id: int | None) -> dict:
        params: dict = {"guild_id": guild_id}
        if ping_role_id is not None:
            params["ping_role_id"] = ping_role_id
        resp = await self._client.post("/api/giveaway/settings/ping-role", params=params)
        if resp.status_code != 200:
            raise BackendError(resp.status_code, resp.text or "update ping role failed")
        return resp.json()

    async def update_giveaway_admin_panel_channel(self, guild_id: int, channel_id: int | None) -> dict:
        params: dict = {"guild_id": guild_id}
        if channel_id is not None:
            params["channel_id"] = channel_id
        resp = await self._client.post("/api/giveaway/settings/admin-panel-channel", params=params)
        if resp.status_code != 200:
            raise BackendError(resp.status_code, resp.text or "update admin panel channel failed")
        return resp.json()

    async def update_giveaway_admin_panel_message(self, guild_id: int, message_id: int | None) -> dict:
        params: dict = {"guild_id": guild_id}
        if message_id is not None:
            params["message_id"] = message_id
        resp = await self._client.post("/api/giveaway/settings/admin-panel-message", params=params)
        if resp.status_code != 200:
            raise BackendError(resp.status_code, resp.text or "update admin panel message failed")
        return resp.json()

    async def update_giveaway_public_panel_channel(self, guild_id: int, channel_id: int | None) -> dict:
        params: dict = {"guild_id": guild_id}
        if channel_id is not None:
            params["channel_id"] = channel_id
        resp = await self._client.post("/api/giveaway/settings/public-panel-channel", params=params)
        if resp.status_code != 200:
            raise BackendError(resp.status_code, resp.text or "update public panel channel failed")
        return resp.json()

    async def update_giveaway_public_panel_message(self, guild_id: int, message_id: int | None) -> dict:
        params: dict = {"guild_id": guild_id}
        if message_id is not None:
            params["message_id"] = message_id
        resp = await self._client.post("/api/giveaway/settings/public-panel-message", params=params)
        if resp.status_code != 200:
            raise BackendError(resp.status_code, resp.text or "update public panel message failed")
        return resp.json()

    async def create_exchange(
        self,
        giveaway_id: str,
        winner_id: int,
        creator_id: int,
        channel_id: int,
        guild_id: int | None = None,
        exchange_message_id: int | None = None,
        winners_message_id: int | None = None,
    ) -> dict:
        payload: dict = {
            "giveaway_id": giveaway_id,
            "winner_id": winner_id,
            "creator_id": creator_id,
            "channel_id": channel_id,
            "exchange_message_id": exchange_message_id,
            "winners_message_id": winners_message_id,
        }
        if guild_id is not None:
            payload["guild_id"] = guild_id
        resp = await self._client.post("/api/giveaway/exchanges", json=payload)
        if resp.status_code != 200:
            raise BackendError(resp.status_code, resp.text or "create exchange failed")
        return resp.json()


    async def get_exchange(self, exchange_id: str) -> dict | None:
        resp = await self._client.get(f"/api/giveaway/exchanges/{exchange_id}")
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise BackendError(resp.status_code, resp.text or "get exchange failed")
        return resp.json()

    async def update_exchange_messages(
        self,
        exchange_id: str,
        *,
        exchange_message_id: int | None = None,
        winners_message_id: int | None = None,
    ) -> dict:
        resp = await self._client.patch(
            f"/api/giveaway/exchanges/{exchange_id}/messages",
            json={
                "exchange_message_id": exchange_message_id,
                "winners_message_id": winners_message_id,
            },
        )
        if resp.status_code != 200:
            raise BackendError(resp.status_code, resp.text or "update exchange messages failed")
        return resp.json()

    async def find_exchange_for_winner(self, giveaway_id: str, winner_id: int) -> dict | None:
        resp = await self._client.get(
            "/api/giveaway/exchanges",
            params={"giveaway_id": giveaway_id, "winner_id": winner_id},
        )
        if resp.status_code != 200:
            raise BackendError(resp.status_code, resp.text or "find exchange failed")
        data = resp.json()
        if isinstance(data, list):
            exchanges = data
        else:
            exchanges = data.get("exchanges", []) if isinstance(data, dict) else []
        for ex in exchanges or []:
            if not isinstance(ex, dict):
                continue
            if ex.get("status") == "pending":
                return ex
        return None

    async def list_exchanges_for_giveaway(self, giveaway_id: str) -> list[dict]:
        resp = await self._client.get(
            "/api/giveaway/exchanges",
            params={"giveaway_id": giveaway_id},
        )
        if resp.status_code != 200:
            raise BackendError(resp.status_code, resp.text or "list exchanges failed")
        data = resp.json()
        if isinstance(data, list):
            return [ex for ex in data if isinstance(ex, dict)]
        return [ex for ex in (data.get("exchanges", []) or []) if isinstance(ex, dict)]

    async def confirm_exchange(self, exchange_id: str, by: str) -> dict:
        resp = await self._client.post(
            f"/api/giveaway/exchanges/{exchange_id}/confirm",
            json={"by": by},
        )
        if resp.status_code != 200:
            raise BackendError(resp.status_code, resp.text or "confirm exchange failed")
        return resp.json()

    async def cancel_exchange(self, exchange_id: str) -> dict:
        resp = await self._client.post(f"/api/giveaway/exchanges/{exchange_id}/cancel")
        if resp.status_code != 200:
            raise BackendError(resp.status_code, resp.text or "cancel exchange failed")
        return resp.json()


def is_too_large_for_discord(data: bytes, cap_bytes: int = 8 * 1024 * 1024) -> bool:
    return len(data) > cap_bytes


def convert_png_to_webp(png_bytes: bytes, quality: int = 90) -> bytes:
    from PIL import Image

    with Image.open(io.BytesIO(png_bytes)) as img:
        buf = io.BytesIO()
        img.save(buf, format="WEBP", quality=quality)
        return buf.getvalue()
