from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app import models
from app.api.common import envelope, request_id
from app.api.dependencies import require_csrf
from app.api.serializers import analysis_payload, product_payload
from app.core.errors import AppError
from app.db import get_db
from app.providers import ReferenceImage
from app.services.workflow_lock import workflow_lock

router = APIRouter(prefix="/api/v1", tags=["analysis"])


class AttributeInput(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    value: object
    confidence: float = Field(ge=0, le=1)
    inference_kind: str
    source_asset_ids: list[str] = Field(default_factory=list)
    user_confirmed: bool = False
    high_risk: bool = False


class AnalysisConfirmation(BaseModel):
    profile: dict
    attributes: list[AttributeInput]


@router.post("/products/{product_id}/analysis", status_code=201)
def start_analysis(
    product_id: str,
    request: Request,
    _: str = Header(alias="Idempotency-Key", min_length=8, max_length=200),
    user: models.User = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    product = db.get(models.Product, product_id)
    if not product or product.owner_id != user.id or product.deleted_at is not None:
        raise AppError(code="product_not_found", message="商品不存在", status_code=404)
    assets = db.scalars(
        select(models.ProductAsset)
        .where(
            models.ProductAsset.product_id == product.id,
            models.ProductAsset.status == "ready",
            models.ProductAsset.deleted_at.is_(None),
        )
        .order_by(models.ProductAsset.is_primary.desc(), models.ProductAsset.position)
    ).all()
    if not assets:
        raise AppError(
            code="product_assets_required",
            message="请先上传并确认至少一张商品图片",
            status_code=409,
        )
    latest_version = db.scalar(
        select(func.max(models.AnalysisVersion.version)).where(
            models.AnalysisVersion.product_id == product.id
        )
    )
    version = (latest_version or 0) + 1
    analysis = models.AnalysisVersion(
        product_id=product.id,
        version=version,
        status="analyzing",
    )
    db.add(analysis)
    product.status = "analyzing"
    db.flush()
    references = [
        ReferenceImage(
            name=asset.id,
            content_type=asset.content_type,
            content=request.app.state.media_store.read_bytes(asset.object_key),
        )
        for asset in assets
    ]
    result = request.app.state.ai_provider.analyze_product(product_payload(product), references)
    analysis.result_json = result
    analysis.status = "awaiting_product_confirmation"
    product.status = "awaiting_product_confirmation"
    db.add(
        models.TaskEvent(
            aggregate_type="analysis",
            aggregate_id=analysis.id,
            event_type="analysis_completed",
            state=analysis.status,
            payload_json={"version": version},
        )
    )
    db.commit()
    return JSONResponse(
        status_code=201,
        content=envelope(analysis_payload(analysis), request_id(request)),
    )


@router.post("/analysis/{analysis_id}/confirm")
def confirm_analysis(
    analysis_id: str,
    payload: AnalysisConfirmation,
    request: Request,
    _: str = Header(alias="Idempotency-Key", min_length=8, max_length=200),
    user: models.User = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    analysis = db.get(models.AnalysisVersion, analysis_id)
    product = db.get(models.Product, analysis.product_id) if analysis else None
    if not analysis or not product or product.owner_id != user.id:
        raise AppError(code="analysis_not_found", message="识图记录不存在", status_code=404)
    workflow_lock(db)
    latest_version = db.scalar(select(func.max(models.AnalysisVersion.version)).where(models.AnalysisVersion.product_id == product.id))
    if analysis.version != latest_version:
        raise AppError(code="analysis_obsolete", message="识图版本已更新，请重新载入", status_code=409)
    submitted = {a.key: a for a in payload.attributes}
    source_risks = {a["key"] for a in analysis.result_json.get("attributes", []) if a.get("high_risk")}
    if any(key not in submitted or not submitted[key].high_risk or not submitted[key].user_confirmed for key in source_risks):
        raise AppError(code="risk_confirmation_required", message="请保留并人工确认原高风险字段", status_code=409)
    if any(a.high_risk and not a.user_confirmed for a in payload.attributes):
        raise AppError(code="risk_confirmation_required", message="请人工确认高风险字段；未知值可保留未知", status_code=409)
    asset_ids = set(db.scalars(select(models.ProductAsset.id).where(models.ProductAsset.product_id == product.id, models.ProductAsset.status == "ready", models.ProductAsset.deleted_at.is_(None))))
    if any(not set(a.source_asset_ids).issubset(asset_ids) for a in payload.attributes):
        raise AppError(code="analysis_reference_invalid", message="属性引用了无效的商品素材", status_code=422)
    db.execute(
        delete(models.ProductAttribute).where(models.ProductAttribute.product_id == product.id)
    )
    for attribute in payload.attributes:
        db.add(
            models.ProductAttribute(
                product_id=product.id,
                key=attribute.key,
                value_json=attribute.value,
                confidence=attribute.confidence,
                inference_kind=attribute.inference_kind,
                source_asset_ids=attribute.source_asset_ids,
                user_confirmed=attribute.user_confirmed,
                high_risk=attribute.high_risk,
            )
        )
    product.profile_json = payload.profile
    product.status = "product_confirmed"
    analysis.result_json = {
        "profile": payload.profile,
        "attributes": [attribute.model_dump(mode="json") for attribute in payload.attributes],
    }
    analysis.status = "confirmed"
    analysis.confirmed_at = datetime.now(UTC)
    db.commit()
    return envelope(analysis_payload(analysis), request_id(request))
