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
from .security import APP_PREFIX, OriginGuard
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
    # Every mdshards-owned surface lives under APP_PREFIX (`/_mdshards`) so the
    # entire top-level namespace belongs to the vault — a note or folder can be
    # named `assets`, `api`, `ws`, anything (see CLAUDE.md "App-surface
    # namespace"). The routers carry their own `/api` (or `/ws`) segment, so
    # prefixing here yields `/_mdshards/api/...` and `/_mdshards/ws/...`. Only
    # the catch-all (pages) stays at the root, where vault paths live.
    app.include_router(tree.router, prefix=APP_PREFIX)
    app.include_router(files.router, prefix=APP_PREFIX)
    app.include_router(assets.router, prefix=APP_PREFIX)
    app.include_router(resolve.router, prefix=APP_PREFIX)
    app.include_router(config_router.router, prefix=APP_PREFIX)
    app.include_router(ws.router, prefix=APP_PREFIX)
    # Frontend bundle. `<APP_PREFIX>/assets/*` and the favicon come straight off
    # disk (Vite emits the hashed bundle under `_mdshards/assets/` and the
    # favicon under `_mdshards/`; see the frontend's vite.config.ts assetsDir
    # and public/ layout). Registered BEFORE the catch-all so the md-vs-asset
    # router never sees them. The catch-all reads `index.html` from the bundle
    # root (see pages.py).
    if settings.static_dir is not None:
        assets_dir = settings.static_dir / "_mdshards" / "assets"
        if assets_dir.is_dir():
            app.mount(
                f"{APP_PREFIX}/assets", StaticFiles(directory=assets_dir), name="frontend-assets"
            )

        def _public_file(name: str):
            def handler():
                path = settings.static_dir / "_mdshards" / name
                if not path.is_file():
                    raise HTTPException(404)
                return FileResponse(path)

            handler.__name__ = f"_serve_{name.replace('.', '_')}"
            return handler

        for filename in ("favicon.svg",):
            app.add_api_route(f"{APP_PREFIX}/{filename}", _public_file(filename), methods=["GET"])
    app.include_router(pages.router)
    return app


app = create_app()
