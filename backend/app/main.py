import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import router
from app.config import get_settings
from app.db import Base, engine
from app.scheduler import scheduler_loop

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    Base.metadata.create_all(engine)
    task = None
    if settings.scheduler_enabled:
        task = asyncio.create_task(scheduler_loop(settings))
    yield
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def create_app() -> FastAPI:
    app = FastAPI(
        title="Put Scanner",
        version="1.0.0",
        description="Scheduled put selling setup scanner on Webull market data. Alerts only.",
        lifespan=lifespan,
    )
    app.include_router(router)

    @app.middleware("http")
    async def headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    if STATIC_DIR.is_dir():
        app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str):
            candidate = (STATIC_DIR / full_path).resolve()
            if full_path and candidate.is_file() and STATIC_DIR in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()
