from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.services.generation_events import add_event
from app.services.workflow_lock import workflow_lock


def recover_stale_items(db: Session) -> list[str]:
    workflow_lock(db)
    now = datetime.now(UTC)
    stale = db.scalars(
        select(models.GenerationItem).where(
            models.GenerationItem.state == "generating",
            models.GenerationItem.lease_expires_at.is_not(None),
            models.GenerationItem.lease_expires_at < now,
        ).with_for_update(skip_locked=True).execution_options(populate_existing=True)
    ).all()
    recovered_ids = []
    for item in stale:
        item.state = "queued"
        item.lease_token = None
        item.lease_expires_at = None
        item.error_code = "worker_lease_expired"
        item.error_message = "任务执行中断，已自动重新排队"
        item.retryable = True
        recovered_ids.append(item.id)
        add_event(
            db,
            item.batch_id,
            "item_recovered",
            "queued",
            {"item_id": item.id, "reason": "lease_expired"},
        )
    db.commit()
    return recovered_ids


def queued_item_ids(db: Session, batch_id: str | None = None) -> list[str]:
    statement = select(models.GenerationItem.id).where(models.GenerationItem.state == "queued")
    if batch_id:
        statement = statement.where(models.GenerationItem.batch_id == batch_id)
    return list(db.scalars(statement).all())
