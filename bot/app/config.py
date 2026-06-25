import os
import sys
from dataclasses import dataclass


NEUTRAL_COLOR_ID = 18
REGION_COUNT = 6


@dataclass(frozen=True)
class Config:
    discord_bot_token: str
    backend_url: str
    guild_id: int | None
    log_level: str
    healthcheck_host: str
    healthcheck_port: int

    @property
    def render_url(self) -> str:
        return f"{self.backend_url.rstrip('/')}/api/dinos/render"

    @property
    def dinos_url(self) -> str:
        return f"{self.backend_url.rstrip('/')}/api/dinos"

    @property
    def colors_url(self) -> str:
        return f"{self.backend_url.rstrip('/')}/api/dinos/colors"

    @property
    def regions_url(self) -> str:
        return f"{self.backend_url.rstrip('/')}/api/dinos/regions"


def _parse_optional_int(value: str | None) -> int | None:
    if value is None or value.strip() == "":
        return None
    return int(value)


def load_config() -> Config:
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        print("DISCORD_BOT_TOKEN is required but was not set.", file=sys.stderr)
        sys.exit(1)

    return Config(
        discord_bot_token=token,
        backend_url=os.environ.get("BACKEND_URL", "http://backend:8000").strip(),
        guild_id=_parse_optional_int(os.environ.get("GUILD_ID")),
        log_level=os.environ.get("BOT_LOG_LEVEL", "INFO").strip().upper(),
        healthcheck_host=os.environ.get("HEALTHCHECK_HOST", "0.0.0.0").strip(),
        healthcheck_port=int(os.environ.get("HEALTHCHECK_PORT", "8080")),
    )
