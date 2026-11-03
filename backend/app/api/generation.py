import hashlib
import json
import time
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict
from typing import Literal
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.api.common import envelope, request_id
from app.api.dependencies import require_csrf, require_user
from app.core.errors import AppError
from app.db import get_db
from app.services.workflow_lock import workflow_lock
from app.services.plan_validation import require_current_plan
from app.services.generation_batches import refresh_batch_state
from app.services.generation_events import add_event
from app.media import LocalMediaStore
from app.queueing import dispatch_generation_items
from app.services.generation import (
    TERMINAL_BATCH_STATES,
    batch_payload,
    create_batch,
    ensure_daily_capacity,
    image_attempts_today,
    prepare_failed_items,
    process_batch_inline,
    queued_item_ids,
    retry_failed_inline,
)

router = APIRouter(prefix="/api/v1", tags=["generation"])


class GenerationBatchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt_plan_id: str
    demo_scenario: Literal["success", "partial_once"] = "success"


def _owned_batch(
    db: Session,
    batch_id: str,
    user: models.User,
) -> models.GenerationBatch:
    batch = db.get(models.GenerationBatch, batch_id)
    product = db.get(models.Product, batch.product_id) if batch else None
    if not batch or not product or product.owner_id != user.id or product.deleted_at is not None:
        raise AppError(code="generation_batch_not_found", message="生成任务不存在", status_code=404)
    return batch


@router.post("/generation-batches", status_code=201)
def start_generation_batch(
    payload: GenerationBatchCreate,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=200),
    user: models.User = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    workflow_lock(db)
    path = "/api/v1/generation-batches"
    body_hash = hashlib.sha256(
        json.dumps(payload.model_dump(mode="json"), sort_keys=True).encode()
    ).hexdigest()
    existing = db.scalar(
        select(models.IdempotencyRecord).where(
            models.IdempotencyRecord.owner_id == user.id,
            models.IdempotencyRecord.key == idempotency_key,
            models.IdempotencyRecord.method == "POST",
            models.IdempotencyRecord.path == path,
        )
    )
    if existing:
        if existing.request_hash != body_hash:
            raise AppError(
                code="idempotency_conflict",
                message="该操作标识已用于不同请求",
                status_code=409,
            )
        batch_id = existing.response_json.get("data", {}).get("id")
        batch = _owned_batch(db, batch_id, user)
        dispatch_generation_items(request.app.state.settings, queued_item_ids(db, batch.id), request_id(request))
        return JSONResponse(
            status_code=existing.status_code,
            content=envelope(batch_payload(db, batch), request_id(request)),
        )

    plan = db.get(models.PromptPlan, payload.prompt_plan_id)
    product = db.get(models.Product, plan.product_id) if plan else None
    if not plan or not product or product.owner_id != user.id or product.deleted_at is not None:
        raise AppError(code="prompt_plan_not_found", message="提示词方案不存在", status_code=404)
    if plan.state != "confirmed":
        raise AppError(
            code="prompt_plan_not_confirmed",
            message="请先确认提示词方案",
            status_code=409,
        )
    require_current_plan(db, plan, product)
    settings = request.app.state.settings
    ensure_daily_capacity(db, settings, plan.image_count, include_pending=True)
    batch = create_batch(db, plan=plan)
    batch.demo_scenario = payload.demo_scenario
    initial_response = envelope(batch_payload(db, batch), request_id(request))
    record = models.IdempotencyRecord(
        owner_id=user.id,
        key=idempotency_key,
        method="POST",
        path=path,
        request_hash=body_hash,
        status_code=201,
        response_json=initial_response,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    db.add(record)
    db.commit()

    if settings.queue_mode == "inline":
        process_batch_inline(
            db,
            batch=batch,
            provider=request.app.state.ai_provider,
            media_store=request.app.state.media_store,
            settings=settings,
            request_id=request_id(request),
        )
    else:
        dispatch_generation_items(
            settings,
            queued_item_ids(db, batch.id),
            request_id(request),
        )
    final_response = envelope(batch_payload(db, batch), request_id(request))
    record.response_json = final_response
    db.commit()
    return JSONResponse(status_code=201, content=final_response)


@router.get("/generation-batches/{batch_id}")
def get_generation_batch(
    batch_id: str,
    request: Request,
    user: models.User = Depends(require_user),
    db: Session = Depends(get_db),
):
    batch = _owned_batch(db, batch_id, user)
    return envelope(batch_payload(db, batch), request_id(request))


@router.post("/generation-batches/{batch_id}/retry-failed")
def retry_failed_items(
    batch_id: str,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=200),
    user: models.User = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    workflow_lock(db)
    batch = _owned_batch(db, batch_id, user)
    settings = request.app.state.settings
    path = f"/api/v1/generation-batches/{batch_id}/retry-failed"
    existing = db.scalar(select(models.IdempotencyRecord).where(
        models.IdempotencyRecord.owner_id == user.id,
        models.IdempotencyRecord.key == idempotency_key,
        models.IdempotencyRecord.method == "POST", models.IdempotencyRecord.path == path,
    ))
    if existing:
        return envelope(batch_payload(db, batch), request_id(request))
    item_ids = prepare_failed_items(db, batch=batch, settings=settings, commit=False)
    db.add(models.IdempotencyRecord(owner_id=user.id, key=idempotency_key, method="POST", path=path,
        request_hash=hashlib.sha256(b"{}").hexdigest(), status_code=200,
        response_json={"item_ids": item_ids}, expires_at=datetime.now(UTC) + timedelta(days=1)))
    add_event(db, batch.id, "failed_items_requeued", "queued", {"item_ids": item_ids})
    db.commit()
    if settings.queue_mode == "inline":
        process_batch_inline(db, batch=batch, provider=request.app.state.ai_provider,
            media_store=request.app.state.media_store, settings=settings, request_id=request_id(request))
    else:
        dispatch_generation_items(settings, item_ids, request_id(request))
    return envelope(batch_payload(db, batch), request_id(request))


@router.post("/generation-batches/{batch_id}/cancel")
def cancel_generation_batch(
    batch_id: str,
    request: Request,
    _: str = Header(alias="Idempotency-Key", min_length=8, max_length=200),
    user: models.User = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    workflow_lock(db)
    batch = _owned_batch(db, batch_id, user)
    if batch.state in TERMINAL_BATCH_STATES:
        return envelope(batch_payload(db, batch), request_id(request))
    items = db.scalars(
        select(models.GenerationItem).where(
            models.GenerationItem.batch_id == batch.id,
            models.GenerationItem.state.in_(["queued", "generating"]),
        ).with_for_update().execution_options(populate_existing=True)
    ).all()
    for item in items:
        item.state = "cancelled"
        item.lease_token = None
        item.lease_expires_at = None
    batch.state = "cancelled"
    batch.progress = 100
    batch.completed_at = datetime.now(UTC)
    db.commit()
    return envelope(batch_payload(db, batch), request_id(request))


@router.get("/generation-batches/{batch_id}/events")
def generation_batch_events(
    batch_id: str,
    request: Request,
    user: models.User = Depends(require_user),
    db: Session = Depends(get_db),
):
    _owned_batch(db, batch_id, user)
    session_factory = request.app.state.session_factory
    last_event_id = request.headers.get("Last-Event-ID")
    session_id = request.cookies.get("image_studio_session", "")

    def stream():
        seen: set[str] = set()
        first_read = True
        while True:
            with session_factory() as event_db:
                active_session = request.app.state.session_store.get(session_id)
                active_user = event_db.get(models.User, user.id)
                current_batch = event_db.get(models.GenerationBatch, batch_id)
                product = event_db.get(models.Product, current_batch.product_id) if current_batch else None
                if not active_session or not active_user or not active_user.is_active or not product or product.owner_id != user.id or product.deleted_at is not None:
                    break
                events = event_db.scalars(
                    select(models.TaskEvent)
                    .where(
                        models.TaskEvent.aggregate_type == "generation_batch",
                        models.TaskEvent.aggregate_id == batch_id,
                    )
                    .order_by(models.TaskEvent.created_at, models.TaskEvent.id)
                ).all()
                if first_read and last_event_id:
                    ids = [event.id for event in events]
                    if last_event_id in ids:
                        seen.update(ids[:ids.index(last_event_id) + 1])
                first_read = False
                for event in events:
                    if event.id in seen:
                        continue
                    seen.add(event.id)
                    event_data = {
                        "id": event.id,
                        "type": event.event_type,
                        "state": event.state,
                        **event.payload_json,
                    }
                    yield f"id: {event.id}\nevent: {event.event_type}\n"
                    yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"
                batch = event_db.get(models.GenerationBatch, batch_id)
                if not batch or batch.state in TERMINAL_BATCH_STATES:
                    break
            yield ": keep-alive\n\n"
            time.sleep(1)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/images/{image_id}/content")
def get_generated_image_content(
    image_id: str,
    request: Request,
    user: models.User = Depends(require_user),
    db: Session = Depends(get_db),
):
    image = db.get(models.ImageAsset, image_id)
    product = db.get(models.Product, image.product_id) if image else None
    if not image or not product or product.owner_id != user.id:
        raise AppError(code="image_not_found", message="图片不存在", status_code=404)
    store = request.app.state.media_store
    media_type = "image/png" if image.format == "png" else "image/webp"
    if isinstance(store, LocalMediaStore):
        return FileResponse(store._path(image.object_key), media_type=media_type)
    return RedirectResponse(store.download_url(image.object_key))


@router.get("/usage/daily")
def get_daily_usage(
    request: Request,
    _: models.User = Depends(require_user),
    db: Session = Depends(get_db),
):
    attempts = image_attempts_today(db)
    limit = request.app.state.settings.image_daily_limit
    return envelope(
        {
            "date": datetime.now(UTC).date().isoformat(),
            "image_attempts": attempts,
            "limit": limit,
            "remaining": max(limit - attempts, 0),
        },
        request_id(request),
    )
