import json
import zipfile
from datetime import UTC, datetime, timedelta
from io import BytesIO

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import models
from app.api.common import envelope, request_id
from app.api.dependencies import require_csrf, require_user
from app.core.errors import AppError
from app.db import get_db
from app.media import LocalMediaStore

router = APIRouter(prefix="/api/v1", tags=["downloads"])


class DownloadCreate(BaseModel):
    image_ids: list[str] = Field(min_length=1, max_length=100)


def _bundle_payload(bundle: models.DownloadBundle) -> dict:
    return {
        "id": bundle.id,
        "status": bundle.status,
        "image_ids": bundle.image_ids,
        "download_url": f"/api/v1/downloads/{bundle.id}/content",
        "expires_at": bundle.expires_at.isoformat() if bundle.expires_at else None,
    }


@router.post("/downloads", status_code=201)
def create_download(
    payload: DownloadCreate,
    request: Request,
    _: str = Header(alias="Idempotency-Key", min_length=8, max_length=200),
    user: models.User = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    if len(set(payload.image_ids)) != len(payload.image_ids):
        raise AppError(
            code="duplicate_image_selection",
            message="下载图片不能重复",
            status_code=422,
        )
    images: list[models.ImageAsset] = []
    for image_id in payload.image_ids:
        image = db.get(models.ImageAsset, image_id)
        product = db.get(models.Product, image.product_id) if image else None
        if not image or not product or product.owner_id != user.id:
            raise AppError(code="image_not_found", message="图片不存在", status_code=404)
        images.append(image)

    bundle = models.DownloadBundle(
        owner_id=user.id,
        status="building",
        image_ids=payload.image_ids,
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    db.add(bundle)
    db.flush()
    archive_buffer = BytesIO()
    manifest = []
    with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index, image in enumerate(images, start=1):
            extension = "png" if image.format == "png" else "webp"
            filename = f"product-image-{index:02d}.{extension}"
            archive.writestr(
                filename,
                request.app.state.media_store.read_bytes(image.object_key),
            )
            manifest.append(
                {
                    "image_id": image.id,
                    "filename": filename,
                    "sha256": image.sha256,
                    "quality": image.quality,
                }
            )
        archive.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )
    bundle.object_key = f"downloads/{user.id}/{bundle.id}.zip"
    request.app.state.media_store.put_bytes(
        bundle.object_key,
        archive_buffer.getvalue(),
        "application/zip",
    )
    bundle.status = "ready"
    db.commit()
    return envelope(_bundle_payload(bundle), request_id(request))


@router.get("/downloads/{bundle_id}/content")
def get_download(
    bundle_id: str,
    request: Request,
    user: models.User = Depends(require_user),
    db: Session = Depends(get_db),
):
    bundle = db.get(models.DownloadBundle, bundle_id)
    if not bundle or bundle.owner_id != user.id or bundle.status != "ready":
        raise AppError(code="download_not_found", message="下载文件不存在", status_code=404)
    expires_at = bundle.expires_at
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at and expires_at < datetime.now(UTC):
        raise AppError(code="download_expired", message="下载文件已过期", status_code=410)
    store = request.app.state.media_store
    if isinstance(store, LocalMediaStore):
        return FileResponse(
            store._path(bundle.object_key),
            media_type="application/zip",
            filename="product-images.zip",
        )
    return RedirectResponse(store.download_url(bundle.object_key))
