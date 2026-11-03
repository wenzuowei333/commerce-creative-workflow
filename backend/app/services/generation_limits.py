from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models
from app.config import Settings
from app.core.errors import AppError


def image_attempts_today(db: Session) -> int:
    return int(
        db.scalar(
            select(func.coalesce(func.sum(models.UsageLedger.units), 0)).where(
                models.UsageLedger.usage_date == date.today(),
                models.UsageLedger.operation == "image_generation",
            )
        )
        or 0
    )


def ensure_daily_capacity(db: Session, settings: Settings, requested: int) -> None:
    used = image_attempts_today(db)
    if used + requested > settings.image_daily_limit:
        raise AppError(
            code="daily_image_limit_exceeded",
            message="今日图片生成额度不足",
            retryable=False,
            status_code=429,
            details={
                "limit": settings.image_daily_limit,
                "used": used,
                "requested": requested,
                "remaining": max(settings.image_daily_limit - used, 0),
            },
        )
