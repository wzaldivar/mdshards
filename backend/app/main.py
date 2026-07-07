import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import ws
from .config import get_settings
from .docs import DocumentManager
from .files import ensure_index_exists
from .routers import assets, files, pages, resolve, tree
from .routers import config as config_router
from .security import OriginGuard
from .watcher import VaultWatcher


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.vault_dir.mkdir(parents=True, exist_ok=True)
    ensure_index_exists(settings.vault_dir)
    app.state.doc_manager = DocumentManager(
        settings.vault_dir,
        settings.grace_period_seconds,
        settings.cache_dir,
    )
    # Files deleted while the server was offline leave behind orphan cache
    # entries; clear them so the next acquire doesn't resurrect old CRDT state.
    app.state.doc_manager.prune_orphaned_cache()
    # Stage-2 external-writer reconciliation: watch the vault and ghost-merge
    # external edits to actively-loaded `.md` files into their CRDT Docs.
    watcher = VaultWatcher(app.state.doc_manager, settings.vault_dir)
    watcher.start(asyncio.get_running_loop())
    app.state.vault_watcher = watcher
    try:
        yield
    finally:
        watcher.stop()
        await app.state.doc_manager.shutdown()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(lifespan=lifespan, title="mdshards", root_path=settings.base_url)
    # Outermost middleware — gates every state-changing HTTP request and
    # every WebSocket upgrade on Origin / Sec-Fetch-Site. See security.py.
    app.add_middleware(OriginGuard)
    app.include_router(tree.router)
    app.include_router(files.router)
    app.include_router(assets.router)
    app.include_router(resolve.router)
    app.include_router(config_router.router)
    app.include_router(ws.router)
    # Frontend bundle. `/assets/*` and the two top-level public/ files
    # (favicon.svg, icons.svg) come straight off disk. These prefixes are
    # reserved for the frontend and registered BEFORE the catch-all so the
    # md-vs-asset router never sees them. The catch-all itself reads
    # `index.html` from the same dir as its SPA shell (see pages.py).
    if settings.static_dir is not None:
        assets_dir = settings.static_dir / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

        def _public_file(name: str):
            def handler():
                path = settings.static_dir / name
                if not path.is_file():
                    raise HTTPException(404)
                return FileResponse(path)

            handler.__name__ = f"_serve_{name.replace('.', '_')}"
            return handler

        for filename in ("favicon.svg", "icons.svg"):
            app.add_api_route(f"/{filename}", _public_file(filename), methods=["GET"])
    app.include_router(pages.router)
    return app


app = create_app()
