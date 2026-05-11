"""FastAPI application entry point."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator

from app.core.config import settings
from app.core.database import (
    ACTIVE_DATABASE_URL,
    SessionLocal,
    active_backend_name,
    init_db,
)
from app.routers import (
    analytics, auth, cctv, dashboard, inventory,
    orders, promotions, sales, security, soc, stock,
)
from app.utils.logger import logger
from app.utils.monitoring import MonitoringMiddleware
from app.utils.seed import seed_all


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if settings.SEED_ON_STARTUP:
        db = SessionLocal()
        try:
            seed_all(db)
        except Exception as exc:  # pragma: no cover - never block boot on a seed bug
            logger.exception("Seeding failed (non-fatal): %s", exc)
        finally:
            db.close()
    logger.info(
        "SSMS started -- backend: %s (%s)",
        active_backend_name(),
        ACTIVE_DATABASE_URL.split("@")[-1],
    )
    yield
    logger.info("SSMS shutdown.")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Smart Store Management System",
    lifespan=lifespan,
)

# Prometheus FastAPI instrumentation -- exposes /metrics
Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(MonitoringMiddleware)

app.include_router(auth.router)
app.include_router(sales.router)
app.include_router(stock.router)
app.include_router(cctv.router)
app.include_router(orders.router)
app.include_router(promotions.router)
app.include_router(dashboard.router)
app.include_router(inventory.router)
app.include_router(analytics.router)
app.include_router(soc.router)
app.include_router(security.router)


@app.get("/health", tags=["meta"])
def health():
    return JSONResponse(
        {
            "status": "ok",
            "version": settings.APP_VERSION,
            "database": active_backend_name(),
        }
    )


_HERE = os.path.dirname(os.path.abspath(__file__))
_FRONTEND_CANDIDATES = [
    os.path.normpath(os.path.join(_HERE, "..", "..", "frontend")),
    "/app/frontend",
]
FRONTEND_DIR = next((p for p in _FRONTEND_CANDIDATES if os.path.isdir(p)), None)

if FRONTEND_DIR:
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def root_index():
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

    @app.get("/shop", include_in_schema=False)
    def shop_page():
        return FileResponse(os.path.join(FRONTEND_DIR, "shop.html"))

    @app.get("/scanner", include_in_schema=False)
    def scanner_page():
        path = os.path.join(FRONTEND_DIR, "scanner.html")
        if os.path.exists(path):
            return FileResponse(path)
        return JSONResponse(status_code=404, content={"detail": "Scanner not deployed."})
else:
    @app.get("/", include_in_schema=False)
    def root_fallback():
        return JSONResponse({"app": settings.APP_NAME, "version": settings.APP_VERSION, "docs": "/docs"})
