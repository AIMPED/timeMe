from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .db import init_db
from .routers import admin, auth, clock, days, reports


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="timeMe", version="1.0.0", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(clock.router)
app.include_router(days.router)
app.include_router(reports.router)
app.include_router(admin.router)


@app.get("/api/health")
def health() -> dict:
    settings = get_settings()
    return {"status": "ok", "timezone": settings.timezone}


settings = get_settings()
static_dir = os.path.abspath(settings.static_dir) if settings.static_dir else ""

if static_dir and os.path.isdir(static_dir):
    assets = os.path.join(static_dir, "assets")
    if os.path.isdir(assets):
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str, request: Request):
        # Anything that is not an API route is handed to the SPA router.
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        candidate = os.path.normpath(os.path.join(static_dir, full_path))
        if full_path and candidate.startswith(static_dir) and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(static_dir, "index.html"))
