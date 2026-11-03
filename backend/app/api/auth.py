import hashlib

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.api.common import envelope, request_id
from app.api.dependencies import SESSION_COOKIE, require_csrf, require_user
from app.core.errors import AppError
from app.db import get_db
from app.security import verify_password

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


def _cookie_path(request: Request) -> str:
    settings = request.app.state.settings
    return settings.app_base_path if settings.environment == "production" else "/"


@router.post("/login")
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    client_host = request.client.host if request.client else "unknown"
    limiter_key = hashlib.sha256(f"{client_host}:{payload.username.lower()}".encode()).hexdigest()
    allowed, retry_after = request.app.state.login_limiter.check(limiter_key)
    if not allowed:
        raise AppError(
            code="login_rate_limited",
            message="登录尝试过多，请稍后再试",
            retryable=True,
            status_code=429,
            details={"retry_after_seconds": retry_after},
        )
    user = db.scalar(select(models.User).where(models.User.username == payload.username))
    if not user or not verify_password(user.password_hash, payload.password):
        request.app.state.login_limiter.record_failure(limiter_key)
        raise AppError(code="invalid_credentials", message="账号或密码错误", status_code=401)
    request.app.state.login_limiter.reset(limiter_key)
    session_id, session_data = request.app.state.session_store.create(user.id)
    settings = request.app.state.settings
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path=_cookie_path(request),
        max_age=settings.session_ttl_seconds,
    )
    return envelope(
        {
            "user": {"id": user.id, "username": user.username},
            "csrf_token": session_data.csrf_token,
        },
        request_id(request),
    )


@router.get("/session")
def auth_session(request: Request, user: models.User = Depends(require_user)):
    return envelope(
        {
            "user": {"id": user.id, "username": user.username},
            "csrf_token": request.state.session_data.csrf_token,
        },
        request_id(request),
    )


@router.post("/logout")
def logout(request: Request, response: Response, _: models.User = Depends(require_csrf)):
    session_id = request.cookies.get(SESSION_COOKIE, "")
    request.app.state.session_store.delete(session_id)
    response.delete_cookie(SESSION_COOKIE, path=_cookie_path(request))
    return envelope({"logged_out": True}, request_id(request))
