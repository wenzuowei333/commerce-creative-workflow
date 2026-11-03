from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from redis import Redis
from sqlalchemy import text

from app import models
from app.api.common import envelope, request_id
from app.api.dependencies import require_user
from app.core.errors import AppError

router = APIRouter(tags=["system"])


@router.get("/health/live")
def health_live():
    return {"status": "ok"}


@router.get("/health/ready")
def health_ready(request: Request):
    settings = request.app.state.settings
    blockers = settings.production_readiness_errors()
    checks = {"database": False, "redis": False, "configuration": not blockers}
    try:
        with request.app.state.session_factory() as db:
            db.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:
        blockers.append("Database connection")
    try:
        Redis.from_url(settings.redis_url).ping()
        checks["redis"] = True
    except Exception:
        blockers.append("Redis connection")
    blockers = sorted(set(blockers))
    return JSONResponse(
        status_code=200 if not blockers else 503,
        content={
            "status": "ready" if not blockers else "degraded",
            "checks": checks,
            "blockers": blockers,
        },
    )


@router.get("/metrics", include_in_schema=False)
def metrics(request: Request):
    if not request.app.state.settings.metrics_enabled:
        raise AppError(code="metrics_disabled", message="指标接口未启用", status_code=404)
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/api/v1/system")
def system_info(request: Request, _: models.User = Depends(require_user)):
    settings = request.app.state.settings
    return envelope(
        {
            "mode": "demo" if settings.ai_mode == "mock" else "live",
            "persistent_queue": settings.queue_mode == "dramatiq",
            "external_media": settings.media_backend == "cos",
            "features": settings.public_feature_flags(),
        },
        request_id(request),
    )


@router.get("/health/demo")
def health_demo(request: Request):
    settings = request.app.state.settings
    checks = {"database": False, "redis": False, "mock": settings.ai_mode == "mock"}
    try:
        with request.app.state.session_factory() as db:
            db.execute(text("SELECT 1"))
        checks["database"] = True
        checks["redis"] = bool(Redis.from_url(settings.redis_url).ping())
    except Exception:
        pass
    ready = all(checks.values()) and settings.environment == "demo"
    return JSONResponse(status_code=200 if ready else 503,
        content={"status": "ready" if ready else "degraded", "scope": "local_synthetic_demo", "checks": checks})
