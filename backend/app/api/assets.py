import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.api.common import envelope, request_id
from app.api.dependencies import require_csrf, require_user
from app.api.serializers import asset_payload
from app.core.errors import AppError
from app.db import get_db
from app.media import LocalMediaStore

router = APIRouter(prefix="/api/v1", tags=["assets"])


class UploadFileSpec(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    content_type: str
    size_bytes: int = Field(gt=0, le=20 * 1024 * 1024)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class UploadRequest(BaseModel):
    product_id: str
    files: list[UploadFileSpec]


class AssetUpdate(BaseModel):
    is_primary: bool | None = None
    angle: str | None = Field(default=None, max_length=50)
    position: int | None = Field(default=None, ge=0, le=7)


def _owned_asset(
    db: Session,
    asset_id: str,
    user: models.User,
    *,
    allow_deleted: bool = False,
) -> tuple[models.ProductAsset, models.Product]:
    asset = db.get(models.ProductAsset, asset_id)
    product = db.get(models.Product, asset.product_id) if asset else None
    if (
        not asset
        or not product
        or product.owner_id != user.id
        or (asset.deleted_at is not None and not allow_deleted)
    ):
        raise AppError(code="asset_not_found", message="素材不存在", status_code=404)
    return asset, product


@router.post("/assets/upload-requests", status_code=201)
def create_upload_requests(
    payload: UploadRequest,
    request: Request,
    _: str = Header(alias="Idempotency-Key", min_length=8, max_length=200),
    user: models.User = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    product = db.get(models.Product, payload.product_id)
    if not product or product.owner_id != user.id or product.deleted_at is not None:
        raise AppError(code="product_not_found", message="商品不存在", status_code=404)
    existing_count = len(
        db.scalars(
            select(models.ProductAsset).where(
                models.ProductAsset.product_id == product.id,
                models.ProductAsset.deleted_at.is_(None),
            )
        ).all()
    )
    if not payload.files or len(payload.files) + existing_count > 8:
        raise AppError(
            code="asset_limit_exceeded",
            message="每个商品最多上传 8 张图片",
            status_code=422,
            details={"limit": 8, "current": existing_count},
        )

    supported_types = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
    created = []
    for position, file in enumerate(payload.files, start=existing_count):
        extension = supported_types.get(file.content_type)
        if not extension:
            raise AppError(
                code="asset_type_unsupported",
                message="仅支持 JPG、PNG 和 WebP",
                status_code=422,
            )
        duplicate = db.scalar(
            select(models.ProductAsset).where(
                models.ProductAsset.product_id == product.id,
                models.ProductAsset.sha256 == file.sha256,
                models.ProductAsset.deleted_at.is_(None),
            )
        )
        if duplicate:
            raise AppError(code="asset_duplicate", message="该图片已存在", status_code=409)
        asset_id = str(uuid4())
        upload_token = secrets.token_urlsafe(32)
        object_key = f"products/{product.id}/originals/{asset_id}{extension}"
        asset = models.ProductAsset(
            id=asset_id,
            product_id=product.id,
            object_key=object_key,
            original_name=Path(file.name).name,
            content_type=file.content_type,
            size_bytes=file.size_bytes,
            sha256=file.sha256,
            position=position,
            upload_token=upload_token,
        )
        db.add(asset)
        upload_url, headers = request.app.state.media_store.upload_url(
            asset_id=asset.id,
            object_key=asset.object_key,
            upload_token=upload_token,
        )
        created.append({"asset_id": asset.id, "upload_url": upload_url, "headers": headers})
    db.commit()
    return JSONResponse(status_code=201, content=envelope(created, request_id(request)))


@router.put("/assets/{asset_id}/content", status_code=204)
async def upload_local_asset_content(
    asset_id: str,
    request: Request,
    upload_token: str = Header(alias="X-Upload-Token"),
    db: Session = Depends(get_db),
):
    if not isinstance(request.app.state.media_store, LocalMediaStore):
        raise AppError(code="local_upload_disabled", message="本地上传接口未启用", status_code=404)
    asset = db.get(models.ProductAsset, asset_id)
    if (
        not asset
        or not asset.upload_token
        or not secrets.compare_digest(upload_token, asset.upload_token)
    ):
        raise AppError(code="upload_token_invalid", message="上传链接已失效", status_code=403)
    content = await request.body()
    if len(content) != asset.size_bytes:
        raise AppError(code="asset_size_mismatch", message="上传文件大小不一致", status_code=422)
    request.app.state.media_store.put_bytes(asset.object_key, content, asset.content_type)
    return Response(status_code=204)


@router.post("/assets/{asset_id}/confirm")
def confirm_asset(
    asset_id: str,
    request: Request,
    _: str = Header(alias="Idempotency-Key", min_length=8, max_length=200),
    user: models.User = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    asset, product = _owned_asset(db, asset_id, user)
    if not request.app.state.media_store.exists(asset.object_key):
        raise AppError(code="asset_upload_missing", message="尚未完成文件上传", status_code=409)
    content = request.app.state.media_store.read_bytes(asset.object_key)
    if hashlib.sha256(content).hexdigest() != asset.sha256:
        raise AppError(code="asset_hash_mismatch", message="图片完整性校验失败", status_code=422)
    try:
        with Image.open(BytesIO(content)) as image:
            image.verify()
        with Image.open(BytesIO(content)) as image:
            width, height = image.size
    except (UnidentifiedImageError, OSError):
        raise AppError(
            code="asset_decode_failed", message="文件不是有效图片", status_code=422
        ) from None
    if min(width, height) < 512:
        raise AppError(
            code="asset_resolution_too_small", message="图片短边不能小于 512 像素", status_code=422
        )
    if max(width, height) > 8192:
        raise AppError(
            code="asset_resolution_too_large", message="图片长边不能超过 8192 像素", status_code=422
        )

    asset.width = width
    asset.height = height
    with Image.open(BytesIO(content)) as source:
        thumbnail = source.convert("RGB")
        thumbnail.thumbnail((480, 480))
        thumbnail_buffer = BytesIO()
        thumbnail.save(thumbnail_buffer, format="WEBP", quality=82)
    asset.thumbnail_object_key = f"products/{product.id}/thumbnails/{asset.id}.webp"
    request.app.state.media_store.put_bytes(
        asset.thumbnail_object_key,
        thumbnail_buffer.getvalue(),
        "image/webp",
    )
    asset.status = "ready"
    asset.upload_token = None
    ready_assets = db.scalars(
        select(models.ProductAsset).where(
            models.ProductAsset.product_id == product.id,
            models.ProductAsset.status == "ready",
            models.ProductAsset.id != asset.id,
        )
    ).all()
    if not ready_assets:
        asset.is_primary = True
    db.commit()
    return envelope(asset_payload(asset), request_id(request))


@router.patch("/assets/{asset_id}")
def update_asset(
    asset_id: str,
    payload: AssetUpdate,
    request: Request,
    user: models.User = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    asset, product = _owned_asset(db, asset_id, user)
    updates = payload.model_dump(exclude_none=True)
    if updates.get("is_primary"):
        for sibling in db.scalars(
            select(models.ProductAsset).where(models.ProductAsset.product_id == product.id)
        ).all():
            sibling.is_primary = sibling.id == asset.id
    for key, value in updates.items():
        setattr(asset, key, value)
    db.commit()
    return envelope(asset_payload(asset), request_id(request))


@router.get("/assets/{asset_id}/content")
def get_asset_content(
    asset_id: str,
    request: Request,
    user: models.User = Depends(require_user),
    db: Session = Depends(get_db),
):
    asset, _ = _owned_asset(db, asset_id, user)
    store = request.app.state.media_store
    if isinstance(store, LocalMediaStore):
        return FileResponse(store._path(asset.object_key), media_type=asset.content_type)
    return RedirectResponse(store.download_url(asset.object_key))


@router.get("/assets/{asset_id}/thumbnail")
def get_asset_thumbnail(
    asset_id: str,
    request: Request,
    user: models.User = Depends(require_user),
    db: Session = Depends(get_db),
):
    asset, _ = _owned_asset(db, asset_id, user)
    object_key = asset.thumbnail_object_key or asset.object_key
    store = request.app.state.media_store
    if isinstance(store, LocalMediaStore):
        return FileResponse(store._path(object_key), media_type="image/webp")
    return RedirectResponse(store.download_url(object_key))


@router.delete("/assets/{asset_id}")
def delete_asset(
    asset_id: str,
    request: Request,
    user: models.User = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    asset, _ = _owned_asset(db, asset_id, user)
    now = datetime.now(UTC)
    asset.deleted_at = now
    deleted = models.DeletedObject(
        object_type="product_asset",
        object_id=asset.id,
        object_key=asset.object_key,
        deleted_at=now,
        purge_after=now + timedelta(days=7),
    )
    db.add(deleted)
    db.commit()
    return envelope(
        {
            "deleted": True,
            "recycle_entry_id": deleted.id,
            "purge_after": deleted.purge_after.isoformat(),
        },
        request_id(request),
    )


@router.get("/recycle-bin")
def list_recycle_bin(
    request: Request,
    user: models.User = Depends(require_user),
    db: Session = Depends(get_db),
):
    entries = db.scalars(
        select(models.DeletedObject)
        .where(models.DeletedObject.restored_at.is_(None))
        .order_by(models.DeletedObject.deleted_at.desc())
    ).all()
    payload = []
    for entry in entries:
        if entry.object_type != "product_asset":
            continue
        asset = db.get(models.ProductAsset, entry.object_id)
        product = db.get(models.Product, asset.product_id) if asset else None
        if not asset or not product or product.owner_id != user.id:
            continue
        payload.append(
            {
                "id": entry.id,
                "object_type": entry.object_type,
                "object_id": entry.object_id,
                "name": asset.original_name,
                "deleted_at": entry.deleted_at.isoformat(),
                "purge_after": entry.purge_after.isoformat(),
            }
        )
    return envelope(payload, request_id(request))


@router.post("/recycle-bin/{entry_id}/restore")
def restore_recycle_entry(
    entry_id: str,
    request: Request,
    _: str = Header(alias="Idempotency-Key", min_length=8, max_length=200),
    user: models.User = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    entry = db.get(models.DeletedObject, entry_id)
    asset = db.get(models.ProductAsset, entry.object_id) if entry else None
    product = db.get(models.Product, asset.product_id) if asset else None
    if (
        not entry
        or entry.object_type != "product_asset"
        or entry.restored_at is not None
        or not asset
        or not product
        or product.owner_id != user.id
    ):
        raise AppError(code="recycle_entry_not_found", message="回收记录不存在", status_code=404)
    purge_after = entry.purge_after
    if purge_after.tzinfo is None:
        purge_after = purge_after.replace(tzinfo=UTC)
    if purge_after <= datetime.now(UTC):
        raise AppError(code="recycle_entry_expired", message="素材已超过恢复期限", status_code=410)
    asset.deleted_at = None
    entry.restored_at = datetime.now(UTC)
    db.commit()
    return envelope({"restored": True, "asset": asset_payload(asset)}, request_id(request))
