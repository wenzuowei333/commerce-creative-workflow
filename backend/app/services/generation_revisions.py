from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models
from app.config import Settings
from app.core.errors import AppError
from app.media import MediaStore
from app.providers import AIProvider, ReferenceImage
from app.services.generation_execution import process_item, reference_images


def create_derivative(
    db: Session,
    *,
    parent: models.ImageAsset,
    instruction: str,
    revision_type: str,
    provider: AIProvider,
    media_store: MediaStore,
    settings: Settings,
    request_id: str,
) -> models.ImageRevision:
    parent_item = db.get(models.GenerationItem, parent.generation_item_id)
    batch = db.get(models.GenerationBatch, parent.batch_id)
    if not parent_item or not batch:
        raise AppError(
            code="image_context_missing",
            message="图片版本上下文不存在",
            status_code=409,
        )
    next_index = (
        int(
            db.scalar(
                select(func.coalesce(func.max(models.GenerationItem.index), -1)).where(
                    models.GenerationItem.batch_id == batch.id
                )
            )
            or 0
        )
        + 1
    )
    action = "高清定稿" if revision_type == "finalize" else "调整"
    item = models.GenerationItem(
        batch_id=batch.id,
        direction_id=parent_item.direction_id,
        index=next_index,
        module=parent_item.module,
        kind=revision_type,
        state="queued",
        prompt=(
            f"{parent_item.prompt}\n{action}要求：{instruction}\n"
            "必须继续保持同一商品的品牌、包装、颜色、比例、材质和关键结构。"
        ),
        parent_image_id=parent.id,
    )
    db.add(item)
    db.commit()

    media_type = "image/png" if parent.format == "png" else "image/webp"
    parent_reference = ReferenceImage(
        name=f"selected-{parent.id}.{parent.format}",
        content_type=media_type,
        content=media_store.read_bytes(parent.object_key),
    )
    product_references = reference_images(db, batch.product_id, media_store)
    process_item(
        db,
        item=item,
        provider=provider,
        media_store=media_store,
        settings=settings,
        request_id=request_id,
        references=[parent_reference, *product_references],
        quality="high" if revision_type == "finalize" else None,
        output_format="png" if revision_type == "finalize" else "webp",
    )
    if item.state != "completed" or not item.output_image_id:
        raise AppError(
            code=item.error_code or "image_revision_failed",
            message=item.error_message or "图片调整失败，请稍后重试",
            retryable=True,
            status_code=502,
        )
    revision = models.ImageRevision(
        parent_image_id=parent.id,
        child_image_id=item.output_image_id,
        instruction=instruction,
        revision_type=revision_type,
    )
    db.add(revision)
    db.commit()
    return revision
