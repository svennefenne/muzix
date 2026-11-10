"""The Muzix web application."""

import logging
import os

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import API_VERSION, __version__, db, env, jobs, modules, network, settings, tunnel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


class NoProxyBuffering:
    """Ask nginx-style reverse proxies to pass audio straight through instead of
    spooling every track to a temporary file first."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                ctype = next((v for k, v in headers if k.lower() == b"content-type"), b"")
                if ctype.startswith((b"audio/", b"application/ogg")):
                    message = {**message, "headers": [*headers, (b"x-accel-buffering", b"no")]}
            await send(message)

        await self.app(scope, receive, send_wrapper)


def create_app() -> FastAPI:
    db.init()
    jobs.recover()
    tunnel.startup()

    # job implementations register themselves on import
    from . import books, enrich, maintenance, mirror, podcasts, scanner  # noqa: F401
    from .organize import importer  # noqa: F401
    from .api import admin, android, auth, books as books_api, library, me, podcasts as podcasts_api
    from .api import connect, manage as manage_api, network as network_api, online, radio, setup
    from .api import stream, tags, upload

    app = FastAPI(title="Muzix", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.add_middleware(NoProxyBuffering)
    # the requests of a module answer only while it's on
    module_of = {books_api: "audiobooks", podcasts_api: "podcasts", radio: "radio", online: "vgm", network_api: "network"}
    for mod in (auth, setup, library, stream, me, admin, books_api, podcasts_api, radio, upload,
                online, manage_api, connect, android, network_api, tags):
        needs = [Depends(modules.needed(module_of[mod]))] if mod in module_of else []
        app.include_router(mod.router, dependencies=needs)
        if hasattr(mod, "art_router"):
            app.include_router(mod.art_router, dependencies=needs)
    app.include_router(android.desktop_router)

    @app.get("/api/health")
    def health():
        # the outside address: the app goes there when the one at home doesn't answer (docs/app-plan.md)
        return {"ok": True, "version": __version__, "api": API_VERSION, "address": settings.get("public_url") or ""}

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def manifest(request: Request):
        """Makes Muzix installable: a home screen icon that opens without browser bars. Installed
        on a phone it stays upright; tablets turn freely (Android tablets' browsers leave "Mobile"
        out of their user agent)."""
        name = settings.get("site_name") or "Muzix"
        icon = {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"}
        ua = request.headers.get("user-agent", "")
        phone = ("Android" in ua and "Mobile" in ua) or "iPhone" in ua
        return JSONResponse({
            **({"orientation": "portrait"} if phone else {}),
            "id": "/", "name": name, "short_name": name[:12],
            "description": "Your music, chiptunes, audiobooks, podcasts and radio",
            "start_url": "/", "scope": "/", "display": "standalone",
            "background_color": "#0a1020", "theme_color": "#0a1020", "categories": ["music", "entertainment"],
            "icons": [
                {**icon, "purpose": "any"},
                {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
                {"src": "/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
            ],
            "shortcuts": [{"name": label, "url": url, "icons": [icon]} for label, url, module in (
                ("Library", "/library", None), ("VGM", "/vgm", "vgm"), ("Audiobooks", "/audiobooks", "audiobooks"),
                ("Podcasts", "/podcasts", "podcasts"), ("Radio", "/radio", "radio")) if module is None or modules.on(module)],
        }, media_type="application/manifest+json", headers={"Cache-Control": "no-cache", "Vary": "User-Agent"})

    @app.exception_handler(404)
    async def not_found(request: Request, exc):
        if request.url.path.startswith("/api/"):
            detail = getattr(exc, "detail", "Not found")
            return JSONResponse({"detail": detail}, status_code=404)
        return _index()

    static = env.STATIC_DIR
    if (static / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

    def _index():
        index = static / "index.html"
        if index.exists():
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return JSONResponse({"detail": "The web interface isn't built (frontend/ → npm run build)"}, 404)

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        f = static / path
        if path and f.is_file() and static in f.resolve().parents:
            return FileResponse(f)
        return _index()

    jobs.every("scan", lambda: int(settings.get("scan_interval_hours")) * 3600)
    jobs.every("refresh_feeds", lambda: int(settings.get("podcast_refresh_hours")) * 3600 if modules.on("podcasts") else 0)
    jobs.every("artist_tags", lambda: 24 * 3600 if settings.get("artist_tags") != "off" else 0)
    jobs.every("prune_cache", lambda: 24 * 3600)
    jobs.every("network_sync", lambda: 24 * 3600 if modules.on("network") and network.linked() else 0)
    if not os.environ.get("MUZIX_NO_SCHEDULER"):
        jobs.start_scheduler()
    return app


app = None


def get_app():
    global app
    if app is None:
        app = create_app()
    return app
