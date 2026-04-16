from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import admin, auth, claims, fraud_clusters, health, plans, platforms, policy, triggers, workers, zones
from .core.config import settings
from .core.db import close_db, init_db
from .core.logging import configure_logging
from .core.zone_cache import load_zone_map
from .services.trigger_monitor import trigger_monitor
from .services.co_claim_monitor import co_claim_cluster_monitor
from .services.ml_premium import initialize_premium_model
from .services.external_apis import initialize_api_client, close_api_client
from .services.fraud_isolation import initialize_fraud_model

configure_logging()
logger = logging.getLogger(__name__)
ADMIN_UI_DIR = Path(__file__).resolve().parents[1] / "admin_ui"


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("app_starting")
    await init_db()
    load_zone_map()
    
    # Initialize ML model for dynamic premium calculation
    initialize_premium_model()

    # Initialize fraud anomaly model for claim scoring
    initialize_fraud_model()
    
    # Initialize external API client for real trigger data
    await initialize_api_client()
    
    await trigger_monitor.start()
    await co_claim_cluster_monitor.start()
    logger.info("app_started")
    yield
    await co_claim_cluster_monitor.stop()
    await trigger_monitor.stop()
    await close_api_client()
    await close_db()
    logger.info("app_stopped")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_allow_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api/v1/health")
app.include_router(auth.router, prefix="/api/v1/auth")
app.include_router(platforms.router, prefix="/api/v1/platforms")
app.include_router(zones.router, prefix="/api/v1/zones")
app.include_router(plans.router, prefix="/api/v1/plans")
app.include_router(policy.router, prefix="/api/v1/policy")
app.include_router(claims.router, prefix="/api/v1/claims")
app.include_router(workers.router, prefix="/api/v1")
app.include_router(triggers.router, prefix="/api/v1/triggers")
app.include_router(fraud_clusters.router, prefix="/api/v1/fraud")
app.include_router(admin.router, prefix="/api/v1/admin")

if ADMIN_UI_DIR.exists():
    app.mount("/admin/assets", StaticFiles(directory=ADMIN_UI_DIR), name="admin-assets")


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {"service": settings.app_name, "status": "ok", "version": settings.app_version}


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    # Lightweight liveness endpoint for hosting platform probes.
    return {"status": "ok"}


@app.get("/admin", include_in_schema=False)
@app.get("/admin/{path:path}", include_in_schema=False)
async def admin_ui(path: str = "") -> FileResponse:
    _ = path
    return FileResponse(ADMIN_UI_DIR / "index.html")
