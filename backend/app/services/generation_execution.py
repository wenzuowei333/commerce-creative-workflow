import hashlib
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from threading import Event, Thread

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import models
from app.config import Settings
from app.core.errors import AppError
from app.media import MediaStore
from app.providers import AIProvider, ReferenceImage
from app.services.generation_events import add_event
from app.services.generation_limits import ensure_daily_capacity
from app.services.workflow_lock import workflow_lock
from app.demo_provider import before_demo_generation


class LeaseHeartbeat:
    def __init__(
        self,
        db: Session,
        *,
        item_id: str,
        lease_token: str,
        lease_seconds: float,
        heartbeat_seconds: float,
    ) -> None:
        self.bind = db.get_bind()
        self.item_id = item_id
        self.lease_token = lease_token
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.stopped = Event()
        self.thread = Thread(target=self._run, daemon=True, name=f"lease-{item_id[:8]}")

    def _run(self) -> None:
        while not self.stopped.wait(self.heartbeat_seconds):
            with Session(self.bind) as heartbeat_db:
                result = heartbeat_db.execute(
                    update(models.GenerationItem)
                    .where(
                        models.GenerationItem.id == self.item_id,
                        models.GenerationItem.state == "generating",
                        models.GenerationItem.lease_token == self.lease_token,
                        models.GenerationItem.lease_expires_at > datetime.now(UTC),
                    )
                    .values(
                        lease_expires_at=datetime.now(UTC) + timedelta(seconds=self.lease_seconds)
                    )
                    .execution_options(synchronize_session=False)
                )
                heartbeat_db.commit()
                if result.rowcount != 1:
                    return

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stopped.set()
        self.thread.join(timeout=2)


def reference_images(
    db: Session,
    product_id: str,
    media_store: MediaStore,
) -> list[ReferenceImage]:
    assets = db.scalars(
        select(models.ProductAsset)
        .where(
            models.ProductAsset.product_id == product_id,
            models.ProductAsset.status == "ready",
            models.ProductAsset.deleted_at.is_(None),
        )
        .order_by(models.ProductAsset.is_primary.desc(), models.ProductAsset.position)
    ).all()
    if not assets:
        raise AppError(
            code="product_assets_required",
            message="商品缺少可用参考图",
            status_code=409,
        )
    return [
        ReferenceImage(
            name=asset.original_name,
            content_type=asset.content_type,
            content=media_store.read_bytes(asset.object_key),
        )
        for asset in assets
    ]


def generation_parameters(
    plan: models.PromptPlan,
    *,
    quality: str | None = None,
    output_format: str | None = None,
) -> tuple[str, str, str]:
    plan_data = plan.plan_json
    size = str(plan_data.get("size", "1024x1024"))
    return (
        size,
        quality or str(plan_data.get("quality", "medium")),
        output_format or "webp",
    )


def validate_generated_image(content: bytes) -> tuple[int, int]:
    if not content:
        raise AppError(
            code="generated_image_empty",
            message="模型返回了空图片",
            retryable=True,
            status_code=502,
        )
    try:
        with Image.open(BytesIO(content)) as image:
            image.verify()
        with Image.open(BytesIO(content)) as image:
            width, height = image.size
    except (UnidentifiedImageError, OSError):
        raise AppError(
            code="generated_image_invalid",
            message="模型返回的图片文件已损坏",
            retryable=True,
            status_code=502,
        ) from None
    if width < 512 or height < 512:
        raise AppError(
            code="generated_image_too_small",
            message="模型返回的图片分辨率过低",
            retryable=True,
            status_code=502,
        )
    return width, height


def process_item(
    db: Session,
    *,
    item: models.GenerationItem,
    provider: AIProvider,
    media_store: MediaStore,
    settings: Settings,
    request_id: str,
    references: list[ReferenceImage] | None = None,
    quality: str | None = None,
    output_format: str | None = None,
) -> bool:
    """Adapted source execution: CAS claim and fenced terminal writes.

    The short global lock orders claim/recovery/refresh mutations. No database
    transaction stays open during Provider generation. A stale owner never
    inserts an ImageAsset, updates the item or clears a replacement's lease.
    """
    item_id = item.id
    workflow_lock(db)
    db.refresh(item)
    if item.state != "queued":
        db.rollback()
        return False
    batch = db.get(models.GenerationBatch, item.batch_id)
    plan = db.get(models.PromptPlan, batch.prompt_plan_id) if batch else None
    if not batch or not plan:
        db.rollback()
        raise AppError(code="generation_context_missing", message="生成任务上下文不存在", status_code=409)
    lease_token = hashlib.sha256(f"{item.id}:{request_id}:{datetime.now(UTC).isoformat()}".encode()).hexdigest()
    claim = db.execute(
        update(models.GenerationItem)
        .where(models.GenerationItem.id == item_id, models.GenerationItem.state == "queued")
        .values(state="generating", attempts=models.GenerationItem.attempts + 1,
                retryable=False, error_code=None, error_message=None, lease_token=lease_token,
                lease_expires_at=datetime.now(UTC) + timedelta(seconds=settings.generation_lease_seconds),
                started_at=datetime.now(UTC), completed_at=None)
        .execution_options(synchronize_session=False)
    )
    if claim.rowcount != 1:
        db.rollback()
        return False
    db.refresh(item)
    generation = item.attempts
    batch_id = batch.id
    if item.kind == "initial":
        batch.state = "generating"
    error = None
    try:
        ensure_daily_capacity(db, settings, 1)
        db.add(models.UsageLedger(usage_date=datetime.now(UTC).date(), operation="image_generation",
                                 model=settings.image_model, units=1, request_id=request_id))
    except AppError as exc:
        error = exc
    add_event(db, batch_id, "item_generating", "generating",
              {"item_id": item_id, "attempt": generation, "request_id": request_id})
    db.commit()

    heartbeat = LeaseHeartbeat(db, item_id=item_id, lease_token=lease_token,
        lease_seconds=settings.generation_lease_seconds, heartbeat_seconds=settings.generation_heartbeat_seconds)
    heartbeat.start()
    content = None
    try:
        if error is None:
            source_images = references or reference_images(db, batch.product_id, media_store)
            # Freeze settings at batch creation instead of reading a later edited plan.
            snapshot = batch.plan_snapshot_json or plan.plan_json
            size = str(snapshot.get("size", "1024x1024"))
            active_quality = quality or str(snapshot.get("quality", "medium"))
            active_format = output_format or "webp"
            prompt = item.prompt
            before_demo_generation(settings, batch, item)
            db.commit()  # Release reference-read transaction before Provider call.
            content = provider.generate_image(prompt=prompt, images=source_images, size=size,
                quality=active_quality, output_format=active_format)
            width, height = validate_generated_image(content)
    except AppError as exc:
        error = exc
    except Exception:
        error = AppError(code="generation_unexpected_error", message="图片生成失败，请稍后重试", retryable=True, status_code=502)
    finally:
        heartbeat.stop()
        db.rollback()

    workflow_lock(db)
    owned = db.scalar(select(models.GenerationItem).where(
        models.GenerationItem.id == item_id, models.GenerationItem.state == "generating",
        models.GenerationItem.lease_token == lease_token, models.GenerationItem.attempts == generation,
        models.GenerationItem.lease_expires_at > datetime.now(UTC),
    ).with_for_update().execution_options(populate_existing=True))
    if owned is None:
        add_event(db, batch_id, "stale_result_rejected", "unchanged",
                  {"item_id": item_id, "rejected_attempt": generation, "request_id": request_id})
        db.commit()
        return False
    if error is not None:
        owned.state = "failed"
        owned.error_code = error.code
        owned.error_message = error.message
        owned.retryable = error.retryable
        add_event(db, batch_id, "item_failed", "generating",
                  {"item_id": item_id, "attempt": generation, "code": error.code, "retryable": error.retryable})
    else:
        image = models.ImageAsset(product_id=batch.product_id, batch_id=batch_id,
            generation_item_id=item_id, object_key="pending", format=active_format,
            width=width, height=height, quality=active_quality, sha256=hashlib.sha256(content).hexdigest())
        db.add(image)
        db.flush()
        extension = "png" if active_format == "png" else "webp"
        image.object_key = f"products/{batch.product_id}/generated/{batch_id}/{image.id}.{extension}"
        media_store.put_bytes(image.object_key, content, "image/png" if active_format == "png" else "image/webp")
        owned.output_image_id = image.id
        owned.state = "completed"
        owned.retryable = False
        add_event(db, batch_id, "item_completed", "generating",
                  {"item_id": item_id, "image_id": image.id, "attempt": generation, "request_id": request_id})
    owned.completed_at = datetime.now(UTC)
    owned.lease_token = None
    owned.lease_expires_at = None
    db.commit()
    return True
