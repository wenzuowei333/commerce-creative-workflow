import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app import models
from app.api.analysis import router as analysis_router
from app.api.assets import router as assets_router
from app.api.auth import router as auth_router
from app.api.downloads import router as downloads_router
from app.api.generation import router as generation_router
from app.api.history import router as history_router
from app.api.products import router as products_router
from app.api.prompts import router as prompts_router
from app.api.results import router as results_router
from app.api.system import router as system_router
from app.api.templates import router as templates_router
from app.config import Settings, get_settings
from app.core.errors import AppError
from app.db import Base, build_session_factory
from app.media import build_media_store
from app.metrics import HTTP_DURATION, HTTP_REQUESTS
from app.providers import build_ai_provider
from app.queueing import dispatch_generation_items
from app.security import build_login_limiter, build_session_store, hash_password
from app.services.generation import queued_item_ids, recover_stale_items


def _build_lifespan(settings: Settings, session_factory):
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        engine = session_factory.kw["bind"]
        if settings.environment != "production":
            Base.metadata.create_all(engine)
        with session_factory() as db:
            user = db.scalar(
                select(models.User).where(models.User.username == settings.admin_username)
            )
            if not user:
                db.add(
                    models.User(
                        username=settings.admin_username,
                        password_hash=hash_password(settings.admin_password),
                    )
                )
                db.commit()
            recover_stale_items(db)
            if settings.queue_mode == "dramatiq":
                dispatch_generation_items(settings, queued_item_ids(db), "startup-recovery")
        yield

    return lifespan


def _configure_state(app: FastAPI, settings: Settings, session_factory) -> None:
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.login_limiter = build_login_limiter(settings)
    app.state.session_store = build_session_store(settings)
    app.state.media_store = build_media_store(settings)
    app.state.ai_provider = build_ai_provider(settings)


def _register_routers(app: FastAPI) -> None:
    routers = (
        auth_router,
        system_router,
        products_router,
        assets_router,
        analysis_router,
        prompts_router,
        downloads_router,
        generation_router,
        history_router,
        results_router,
        templates_router,
    )
    for router in routers:
        app.include_router(router)


def _register_middleware(app: FastAPI, settings: Settings) -> None:
    @app.middleware("http")
    async def request_context(request: Request, call_next):
        started_at = time.monotonic()
        request.state.request_id = request.headers.get("X-Request-ID") or uuid4().hex
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if settings.environment == "production":
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; img-src 'self' data: blob: https:; "
                "style-src 'self' 'unsafe-inline'; script-src 'self'; "
                "connect-src 'self' https:; frame-ancestors 'none'"
            )
            if settings.session_cookie_secure:
                response.headers["Strict-Transport-Security"] = (
                    "max-age=31536000; includeSubDomains"
                )
        if settings.metrics_enabled:
            route = request.scope.get("route")
            route_path = getattr(route, "path", "unmatched")
            HTTP_REQUESTS.labels(request.method, route_path, response.status_code).inc()
            HTTP_DURATION.labels(request.method, route_path).observe(time.monotonic() - started_at)
        return response


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.to_payload(request.state.request_id),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        details = [
            {"location": list(error["loc"]), "type": error["type"]} for error in exc.errors()
        ]
        error = AppError(
            code="request_validation_failed",
            message="请求参数不符合要求",
            status_code=422,
            details={"fields": details},
        )
        return JSONResponse(
            status_code=422,
            content=error.to_payload(request.state.request_id),
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, _: Exception):
        error = AppError(
            code="internal_error",
            message="服务暂时无法处理该请求，请稍后重试",
            retryable=True,
            status_code=500,
        )
        return JSONResponse(
            status_code=500,
            content=error.to_payload(request.state.request_id),
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or get_settings()
    session_factory = build_session_factory(active_settings.database_url)
    app = FastAPI(
        title=active_settings.app_name,
        version="0.2.0",
        lifespan=_build_lifespan(active_settings, session_factory),
    )
    _configure_state(app, active_settings, session_factory)
    _register_routers(app)
    _register_middleware(app, active_settings)
    _register_exception_handlers(app)
    return app


app = create_app()
