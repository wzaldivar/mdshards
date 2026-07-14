from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The prebuilt frontend bundle, when present, lives in a `static/` directory
# next to the `app/` package. The single-container image copies Vite's `dist/`
# there; local dev has no such directory (Vite serves the frontend instead).
# This is a convention, not a configurable path — see `Settings.static_dir`.
_BUNDLED_STATIC = Path(__file__).resolve().parent.parent / "static"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    vault_dir: Path
    # Window the in-memory Doc lingers after the last client disconnects.
    # Clients send a periodic awareness heartbeat (see Editor.tsx) so any tab
    # that's still alive — even when backgrounded — keeps the Doc resident.
    # A truly closed tab stops heartbeating and the state evicts after this
    # window. Overridable via GRACE_PERIOD_SECONDS.
    grace_period_seconds: float = 30.0
    # Where the binary Yjs cache lives. The cache preserves CRDT item IDs
    # across grace evictions and server restarts so reconnecting clients
    # don't end up with the same characters merged in twice. Lives outside
    # the vault so the vault itself stays strictly plain `.md`. Overridable
    # via CACHE_DIR; `~` is expanded so `CACHE_DIR=~/.local/share/...` works.
    cache_dir: Path = Path("~/.cache/mdshards").expanduser()
    # Interface + port uvicorn binds to. Internal to the process — these are
    # NOT the public-facing URL when running behind a reverse proxy; use the
    # `base_url` setting below for a sub-path mount.
    host: str = "127.0.0.1"
    port: int = 8000
    # Reverse-proxy / sub-path mount support. When the app is served from a
    # sub-path of the public origin (e.g. `https://notes.example.com/wiki/`),
    # set `BASE_URL=/wiki`. Wired into FastAPI's `root_path`, which per the
    # ASGI spec means incoming `path`s INCLUDE the prefix and the app strips
    # it itself — so the proxy must forward `/wiki/...` UNSTRIPPED. Routes
    # tolerate the unprefixed form too, but the `/assets` static mount does
    # not: the proxy must ADD the prefix to the origin-rooted URLs the
    # bundle fetches (`/api/*`, `/ws/*`, `/assets/*`, `/favicon.svg`, vault
    # assets) — e.g. Traefik's `addprefix` middleware; see README
    # "Serving from a sub-path". Leading slash, no trailing slash. Empty
    # string = mounted at root. Surfaced to the frontend bundle via
    # `/api/config`'s `homePath` field — the frontend uses it solely as
    # React Router's `basename` so internal pushState navigation lands at
    # the right URL bar value; outgoing API/WS/asset URLs are NOT prefixed
    # by the client (the proxy is responsible for routing those).
    base_url: str = ""

    @property
    def static_dir(self) -> Path | None:
        """Directory the prebuilt frontend is served from, or `None` when it
        isn't bundled (local dev). When set, `/assets/*` and `/favicon.svg`
        are served from here and the catch-all's SPA shell is the real
        script-tagged `index.html` instead of the dev placeholder. Not
        configurable — it's the fixed `static/` convention next to `app/`, so
        the single-container image needs no env var to enable serving."""
        return _BUNDLED_STATIC if _BUNDLED_STATIC.is_dir() else None

    @field_validator("cache_dir", "vault_dir", mode="before")
    @classmethod
    def _expand_user(cls, v: object) -> object:
        # Honor `~` in env-supplied paths — pydantic's default Path coercion
        # leaves the tilde literal.
        if isinstance(v, str):
            return Path(v).expanduser()
        if isinstance(v, Path):
            return v.expanduser()
        return v

    @field_validator("base_url")
    @classmethod
    def _normalise_base_url(cls, v: str) -> str:
        # Allow empty (mounted at root) or any `/prefix` shape.
        if v == "" or v == "/":
            return ""
        if not v.startswith("/"):
            v = "/" + v
        return v.rstrip("/")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
