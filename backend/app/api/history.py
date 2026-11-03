from datetime import date, datetime, time

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.api.common import envelope, request_id
from app.api.dependencies import require_user
from app.core.errors import AppError
from app.db import get_db
from app.services.generation import batch_payload

router = APIRouter(prefix="/api/v1", tags=["history"])


@router.get("/history")
def list_history(
    request: Request,
    product_id: str | None = None,
    generation_type: str | None = None,
    state: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: models.User = Depends(require_user),
    db: Session = Depends(get_db),
):
    statement = (
        select(models.GenerationBatch)
        .join(models.Product, models.GenerationBatch.product_id == models.Product.id)
        .where(models.Product.owner_id == user.id)
    )
    if product_id:
        statement = statement.where(models.GenerationBatch.product_id == product_id)
    if generation_type:
        statement = statement.where(models.GenerationBatch.generation_type == generation_type)
    if state:
        statement = statement.where(models.GenerationBatch.state == state)
    if date_from:
        statement = statement.where(
            models.GenerationBatch.created_at >= datetime.combine(date_from, time.min)
        )
    if date_to:
        statement = statement.where(
            models.GenerationBatch.created_at <= datetime.combine(date_to, time.max)
        )
    batches = db.scalars(
        statement.order_by(models.GenerationBatch.created_at.desc()).offset(offset).limit(limit)
    ).all()
    items = []
    for batch in batches:
        product = db.get(models.Product, batch.product_id)
        payload = batch_payload(db, batch)
        payload["product"] = {"id": product.id, "name": product.name, "sku": product.sku}
        items.append(payload)
    return envelope(
        {"items": items, "limit": limit, "offset": offset, "has_more": len(items) == limit},
        request_id(request),
    )


@router.get("/history/{batch_id}")
def history_detail(
    batch_id: str,
    request: Request,
    user: models.User = Depends(require_user),
    db: Session = Depends(get_db),
):
    batch = db.get(models.GenerationBatch, batch_id)
    product = db.get(models.Product, batch.product_id) if batch else None
    if not batch or not product or product.owner_id != user.id:
        raise AppError(code="generation_batch_not_found", message="生成任务不存在", status_code=404)
    events = db.scalars(
        select(models.TaskEvent)
        .where(
            models.TaskEvent.aggregate_type == "generation_batch",
            models.TaskEvent.aggregate_id == batch.id,
        )
        .order_by(models.TaskEvent.created_at, models.TaskEvent.id)
    ).all()
    payload = batch_payload(db, batch)
    payload["product"] = {"id": product.id, "name": product.name, "sku": product.sku}
    payload["timeline"] = [
        {
            "id": event.id,
            "type": event.event_type,
            "state": event.state,
            "details": event.payload_json,
            "created_at": event.created_at.isoformat(),
        }
        for event in events
    ]
    return envelope(payload, request_id(request))
