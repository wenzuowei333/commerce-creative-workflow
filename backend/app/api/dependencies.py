import secrets

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from app import models
from app.core.errors import AppError
from app.db import get_db

SESSION_COOKIE = "image_studio_session"


def require_user(request: Request, db: Session = Depends(get_db)) -> models.User:
    session_id = request.cookies.get(SESSION_COOKIE, "")
    session_data = request.app.state.session_store.get(session_id)
    if not session_data:
        raise AppError(
            code="authentication_required",
            message="请先登录",
            status_code=401,
        )
    user = db.get(models.User, session_data.user_id)
    if not user or not user.is_active:
        raise AppError(
            code="authentication_required",
            message="登录状态已失效",
            status_code=401,
        )
    request.state.session_data = session_data
    return user


def require_csrf(
    request: Request,
    user: models.User = Depends(require_user),
    csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> models.User:
    if not csrf_token or not secrets.compare_digest(
        csrf_token,
        request.state.session_data.csrf_token,
    ):
        raise AppError(code="csrf_failed", message="安全校验失败，请刷新页面", status_code=403)
    return user


def require_feature(name: str):
    def dependency(request: Request) -> None:
        if not request.app.state.settings.feature_enabled(name):
            raise AppError(
                code="feature_disabled",
                message="该功能当前未启用",
                status_code=404,
                details={"feature": name},
            )

    return dependency
