from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models


def image_payload(image: models.ImageAsset | None) -> dict[str, Any] | None:
    if not image:
        return None
    return {
        "id": image.id,
        "product_id": image.product_id,
        "batch_id": image.batch_id,
        "format": image.format,
        "width": image.width,
        "height": image.height,
        "quality": image.quality,
        "status": image.status,
        "preview_url": f"/api/v1/images/{image.id}/content",
        "created_at": image.created_at.isoformat(),
    }


def batch_payload(db: Session, batch: models.GenerationBatch) -> dict[str, Any]:
    directions = db.scalars(
        select(models.GenerationDirection)
        .where(models.GenerationDirection.batch_id == batch.id)
        .order_by(models.GenerationDirection.index)
    ).all()
    items = db.scalars(
        select(models.GenerationItem)
        .where(models.GenerationItem.batch_id == batch.id)
        .order_by(models.GenerationItem.index, models.GenerationItem.created_at)
    ).all()
    image_ids = [item.output_image_id for item in items if item.output_image_id]
    images = {
        image.id: image
        for image in db.scalars(
            select(models.ImageAsset).where(models.ImageAsset.id.in_(image_ids))
        ).all()
    }
    return {
        "id": batch.id,
        "product_id": batch.product_id,
        "prompt_plan_id": batch.prompt_plan_id,
        "generation_type": batch.generation_type,
        "image_count": batch.image_count,
        "state": batch.state,
        "progress": batch.progress,
        "error_code": batch.error_code,
        "directions": [
            {
                "id": direction.id,
                "index": direction.index,
                "title": direction.title,
                "rationale": direction.rationale,
            }
            for direction in directions
        ],
        "items": [
            {
                "id": item.id,
                "direction_id": item.direction_id,
                "index": item.index,
                "module": item.module,
                "kind": item.kind,
                "state": item.state,
                "prompt": item.prompt,
                "parent_image_id": item.parent_image_id,
                "attempts": item.attempts,
                "error_code": item.error_code,
                "error_message": item.error_message,
                "image": image_payload(images.get(item.output_image_id)),
            }
            for item in items
        ],
        "created_at": batch.created_at.isoformat(),
        "completed_at": batch.completed_at.isoformat() if batch.completed_at else None,
    }
