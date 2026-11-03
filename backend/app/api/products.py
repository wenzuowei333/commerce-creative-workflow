import hashlib
import json
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.api.common import envelope, request_id
from app.api.dependencies import require_csrf, require_user
from app.api.serializers import (
    analysis_payload,
    asset_payload,
    product_payload,
    prompt_plan_payload,
)
from app.core.errors import AppError
from app.db import get_db

router = APIRouter(prefix="/api/v1", tags=["products"])


class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    sku: str = Field(min_length=1, max_length=100)
    brand: str = Field(default="", max_length=200)


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    sku: str | None = Field(default=None, min_length=1, max_length=100)
    brand: str | None = Field(default=None, max_length=200)


def _owned_product(db: Session, product_id: str, user: models.User) -> models.Product:
    product = db.get(models.Product, product_id)
    if not product or product.owner_id != user.id or product.deleted_at is not None:
        raise AppError(code="product_not_found", message="商品不存在", status_code=404)
    return product


@router.get("/products")
def list_products(
    request: Request,
    user: models.User = Depends(require_user),
    db: Session = Depends(get_db),
):
    products = db.scalars(
        select(models.Product)
        .where(models.Product.owner_id == user.id, models.Product.deleted_at.is_(None))
        .order_by(models.Product.created_at.desc())
    ).all()
    return envelope([product_payload(product) for product in products], request_id(request))


@router.post("/products", status_code=201)
def create_product(
    payload: ProductCreate,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=200),
    user: models.User = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    body = payload.model_dump(mode="json")
    body_hash = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    existing = db.scalar(
        select(models.IdempotencyRecord).where(
            models.IdempotencyRecord.owner_id == user.id,
            models.IdempotencyRecord.key == idempotency_key,
            models.IdempotencyRecord.method == "POST",
            models.IdempotencyRecord.path == "/api/v1/products",
        )
    )
    if existing:
        if existing.request_hash != body_hash:
            raise AppError(
                code="idempotency_conflict",
                message="该操作标识已用于不同请求",
                status_code=409,
            )
        return JSONResponse(status_code=existing.status_code, content=existing.response_json)

    product = models.Product(owner_id=user.id, **body)
    db.add(product)
    db.flush()
    response_body = envelope(product_payload(product), request_id(request))
    db.add(
        models.IdempotencyRecord(
            owner_id=user.id,
            key=idempotency_key,
            method="POST",
            path="/api/v1/products",
            request_hash=body_hash,
            status_code=201,
            response_json=response_body,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
    )
    db.commit()
    return JSONResponse(status_code=201, content=response_body)


@router.get("/products/{product_id}")
def product_workspace(
    product_id: str,
    request: Request,
    user: models.User = Depends(require_user),
    db: Session = Depends(get_db),
):
    product = _owned_product(db, product_id, user)
    assets = db.scalars(
        select(models.ProductAsset)
        .where(
            models.ProductAsset.product_id == product.id,
            models.ProductAsset.status == "ready",
            models.ProductAsset.deleted_at.is_(None),
        )
        .order_by(models.ProductAsset.position)
    ).all()
    analysis = db.scalar(
        select(models.AnalysisVersion)
        .where(models.AnalysisVersion.product_id == product.id)
        .order_by(models.AnalysisVersion.version.desc())
        .limit(1)
    )
    prompt_plan = db.scalar(
        select(models.PromptPlan)
        .where(models.PromptPlan.product_id == product.id)
        .order_by(models.PromptPlan.created_at.desc())
        .limit(1)
    )
    return envelope(
        {
            "product": product_payload(product),
            "assets": [asset_payload(asset) for asset in assets],
            "latest_analysis": analysis_payload(analysis),
            "latest_prompt_plan": prompt_plan_payload(prompt_plan),
        },
        request_id(request),
    )


@router.patch("/products/{product_id}")
def update_product(
    product_id: str,
    payload: ProductUpdate,
    request: Request,
    user: models.User = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    product = _owned_product(db, product_id, user)
    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(product, key, value)
    db.commit()
    return envelope(product_payload(product), request_id(request))
