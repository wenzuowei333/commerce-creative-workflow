from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import models
from app.api.common import envelope, request_id
from app.api.dependencies import require_csrf, require_feature
from app.core.errors import AppError
from app.db import get_db
from app.services.generation import create_derivative, ensure_daily_capacity, image_payload

router = APIRouter(prefix="/api/v1", tags=["results"])


class BulkRevisionCreate(BaseModel):
    image_ids: list[str] = Field(min_length=1, max_length=15)
    instruction: str = Field(min_length=1, max_length=1500)


def _owned_image(db: Session, image_id: str, user: models.User) -> models.ImageAsset:
    image = db.get(models.ImageAsset, image_id)
    product = db.get(models.Product, image.product_id) if image else None
    if not image or not product or product.owner_id != user.id:
        raise AppError(code="image_not_found", message="图片不存在", status_code=404)
    return image


def _revision_payload(db: Session, revision: models.ImageRevision) -> dict:
    child = db.get(models.ImageAsset, revision.child_image_id)
    return {
        "id": revision.id,
        "parent_image_id": revision.parent_image_id,
        "instruction": revision.instruction,
        "revision_type": revision.revision_type,
        "child_image": image_payload(child),
        "created_at": revision.created_at.isoformat(),
    }


@router.post(
    "/image-revisions",
    status_code=201,
    dependencies=[Depends(require_feature("image_revisions"))],
)
def create_bulk_revisions(
    payload: BulkRevisionCreate,
    request: Request,
    _: str = Header(alias="Idempotency-Key", min_length=8, max_length=200),
    user: models.User = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    if len(set(payload.image_ids)) != len(payload.image_ids):
        raise AppError(
            code="duplicate_image_selection",
            message="选中的图片不能重复",
            status_code=422,
        )
    parents = [_owned_image(db, image_id, user) for image_id in payload.image_ids]
    ensure_daily_capacity(db, request.app.state.settings, len(parents))
    revisions = [
        create_derivative(
            db,
            parent=parent,
            instruction=payload.instruction,
            revision_type="edit",
            provider=request.app.state.ai_provider,
            media_store=request.app.state.media_store,
            settings=request.app.state.settings,
            request_id=request_id(request),
        )
        for parent in parents
    ]
    return envelope([_revision_payload(db, item) for item in revisions], request_id(request))


@router.post(
    "/images/{image_id}/revisions",
    status_code=201,
    dependencies=[Depends(require_feature("image_revisions"))],
)
def create_single_revision(
    image_id: str,
    payload: BulkRevisionCreate,
    request: Request,
    _: str = Header(alias="Idempotency-Key", min_length=8, max_length=200),
    user: models.User = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    parent = _owned_image(db, image_id, user)
    ensure_daily_capacity(db, request.app.state.settings, 1)
    revision = create_derivative(
        db,
        parent=parent,
        instruction=payload.instruction,
        revision_type="edit",
        provider=request.app.state.ai_provider,
        media_store=request.app.state.media_store,
        settings=request.app.state.settings,
        request_id=request_id(request),
    )
    return envelope(_revision_payload(db, revision), request_id(request))


@router.post(
    "/images/{image_id}/finalize",
    status_code=201,
    dependencies=[Depends(require_feature("hd_finalize"))],
)
def finalize_image(
    image_id: str,
    request: Request,
    _: str = Header(alias="Idempotency-Key", min_length=8, max_length=200),
    user: models.User = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    parent = _owned_image(db, image_id, user)
    ensure_daily_capacity(db, request.app.state.settings, 1)
    revision = create_derivative(
        db,
        parent=parent,
        instruction="提高细节清晰度与质感，保持原构图和商品完全一致",
        revision_type="finalize",
        provider=request.app.state.ai_provider,
        media_store=request.app.state.media_store,
        settings=request.app.state.settings,
        request_id=request_id(request),
    )
    return envelope(_revision_payload(db, revision), request_id(request))
