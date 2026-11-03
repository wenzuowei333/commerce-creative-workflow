from datetime import UTC, datetime
from copy import deepcopy

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.config import Settings
from app.core.errors import AppError
from app.media import MediaStore
from app.providers import AIProvider
from app.services.generation_events import add_event
from app.services.generation_execution import process_item, reference_images
from app.services.generation_limits import ensure_daily_capacity
from app.services.workflow_lock import workflow_lock
from app.services.plan_validation import validate_plan

TERMINAL_ITEM_STATES = {"completed", "failed", "cancelled"}
TERMINAL_BATCH_STATES = {"completed", "partial", "failed", "cancelled"}


def create_batch(
    db: Session,
    *,
    plan: models.PromptPlan,
) -> models.GenerationBatch:
    validate_plan(plan.plan_json, plan.generation_type, plan.image_count)
    directions = plan.plan_json.get("directions", [])
    variant_count = sum(len(direction.get("variants", [])) for direction in directions)
    if variant_count != plan.image_count:
        raise AppError(
            code="prompt_plan_invalid",
            message="提示词方案中的图片数量不完整，请重新生成提示词",
            status_code=422,
            details={"expected": plan.image_count, "actual": variant_count},
        )

    batch = models.GenerationBatch(
        product_id=plan.product_id,
        prompt_plan_id=plan.id,
        plan_version=plan.active_version,
        plan_snapshot_json=deepcopy(plan.plan_json),
        generation_type=plan.generation_type,
        image_count=plan.image_count,
        state="queued",
        progress=0,
    )
    db.add(batch)
    db.flush()
    global_index = 0
    for direction_index, direction_data in enumerate(directions):
        direction = models.GenerationDirection(
            batch_id=batch.id,
            index=int(direction_data.get("index", direction_index)),
            title=str(direction_data.get("title", f"方向 {direction_index + 1}")),
            rationale=str(direction_data.get("rationale", "")),
        )
        db.add(direction)
        db.flush()
        negative_prompt = str(direction_data.get("negative_prompt", "")).strip()
        for variant in direction_data.get("variants", []):
            prompt = str(variant.get("prompt", direction_data.get("base_prompt", ""))).strip()
            if negative_prompt:
                prompt = f"{prompt}\n负面约束：{negative_prompt}"
            db.add(
                models.GenerationItem(
                    batch_id=batch.id,
                    direction_id=direction.id,
                    index=global_index,
                    module=variant.get("module"),
                    prompt=prompt,
                    kind="initial",
                    state="queued",
                )
            )
            global_index += 1
    add_event(
        db,
        batch.id,
        "batch_queued",
        "queued",
        {"image_count": batch.image_count, "progress": 0},
    )
    return batch


def refresh_batch_state(db: Session, batch: models.GenerationBatch, *, commit: bool = True) -> None:
    workflow_lock(db)
    db.refresh(batch)
    items = db.scalars(
        select(models.GenerationItem).where(
            models.GenerationItem.batch_id == batch.id,
            models.GenerationItem.kind == "initial",
        ).execution_options(populate_existing=True)
    ).all()
    total = len(items)
    terminal = sum(item.state in TERMINAL_ITEM_STATES for item in items)
    completed = sum(item.state == "completed" for item in items)
    failed = sum(item.state == "failed" for item in items)
    cancelled = sum(item.state == "cancelled" for item in items)
    batch.progress = round(terminal * 100 / total) if total else 0

    if terminal == total and total:
        batch.progress = 100
        batch.completed_at = datetime.now(UTC)
        if completed == total:
            batch.state = "completed"
            batch.error_code = None
        elif completed:
            batch.state = "partial"
            batch.error_code = "some_items_failed"
        elif cancelled == total:
            batch.state = "cancelled"
            batch.error_code = None
        else:
            batch.state = "failed"
            batch.error_code = "all_items_failed"
    elif any(item.state == "generating" for item in items):
        batch.state = "generating"
        batch.completed_at = None
    else:
        batch.state = "queued"
        batch.completed_at = None

    add_event(
        db,
        batch.id,
        "batch_progress",
        batch.state,
        {
            "progress": batch.progress,
            "completed": completed,
            "failed": failed,
            "cancelled": cancelled,
            "total": total,
        },
    )
    if commit:
        db.commit()
    else:
        db.flush()


def process_batch_inline(
    db: Session,
    *,
    batch: models.GenerationBatch,
    provider: AIProvider,
    media_store: MediaStore,
    settings: Settings,
    request_id: str,
) -> None:
    references = reference_images(db, batch.product_id, media_store)
    items = db.scalars(
        select(models.GenerationItem)
        .where(
            models.GenerationItem.batch_id == batch.id,
            models.GenerationItem.state == "queued",
            models.GenerationItem.kind == "initial",
        )
        .order_by(models.GenerationItem.index)
    ).all()
    for item in items:
        process_item(
            db,
            item=item,
            provider=provider,
            media_store=media_store,
            settings=settings,
            request_id=request_id,
            references=references,
        )
        refresh_batch_state(db, batch)


def retry_failed_inline(
    db: Session,
    *,
    batch: models.GenerationBatch,
    provider: AIProvider,
    media_store: MediaStore,
    settings: Settings,
    request_id: str,
) -> int:
    failed_ids = prepare_failed_items(db, batch=batch, settings=settings)
    process_batch_inline(
        db,
        batch=batch,
        provider=provider,
        media_store=media_store,
        settings=settings,
        request_id=request_id,
    )
    return len(failed_ids)


def prepare_failed_items(
    db: Session,
    *,
    batch: models.GenerationBatch,
    settings: Settings,
    commit: bool = True,
) -> list[str]:
    workflow_lock(db)
    db.refresh(batch)
    failed = db.scalars(
        select(models.GenerationItem).where(
            models.GenerationItem.batch_id == batch.id,
            models.GenerationItem.kind == "initial",
            models.GenerationItem.state == "failed",
        ).with_for_update().execution_options(populate_existing=True)
    ).all()
    if not failed:
        raise AppError(
            code="no_failed_items",
            message="当前任务没有可重试的失败图片",
            status_code=409,
        )
    ensure_daily_capacity(db, settings, len(failed), include_pending=True)
    for item in failed:
        item.state = "queued"
        item.error_code = None
        item.error_message = None
    batch.state = "queued"
    batch.completed_at = None
    refresh_batch_state(db, batch, commit=commit)
    return [item.id for item in failed]
