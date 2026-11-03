from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.api.common import envelope, request_id
from app.api.dependencies import require_csrf
from app.api.serializers import prompt_plan_payload
from app.core.errors import AppError
from app.db import get_db
from app.domain.generation import GenerationType

router = APIRouter(prefix="/api/v1", tags=["prompts"])


class PromptPlanCreate(BaseModel):
    product_id: str
    generation_type: GenerationType
    image_count: int


class PromptRegenerate(BaseModel):
    instruction: str = Field(default="", max_length=1000)


class PromptConfirmation(BaseModel):
    plan: dict


def _owned_plan(
    db: Session,
    plan_id: str,
    user: models.User,
) -> tuple[models.PromptPlan, models.Product]:
    plan = db.get(models.PromptPlan, plan_id)
    product = db.get(models.Product, plan.product_id) if plan else None
    if not plan or not product or product.owner_id != user.id:
        raise AppError(
            code="prompt_plan_not_found",
            message="提示词方案不存在",
            status_code=404,
        )
    return plan, product


@router.post("/prompt-plans", status_code=201)
def create_prompt_plan(
    payload: PromptPlanCreate,
    request: Request,
    _: str = Header(alias="Idempotency-Key", min_length=8, max_length=200),
    user: models.User = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    product = db.get(models.Product, payload.product_id)
    if not product or product.owner_id != user.id:
        raise AppError(code="product_not_found", message="商品不存在", status_code=404)
    if product.status != "product_confirmed":
        raise AppError(
            code="analysis_not_confirmed",
            message="请先确认商品识别信息",
            status_code=409,
        )
    if payload.image_count not in {5, 10, 15}:
        raise AppError(
            code="image_count_invalid",
            message="图片数量必须为5、10或15",
            status_code=422,
        )
    attributes = db.scalars(
        select(models.ProductAttribute).where(models.ProductAttribute.product_id == product.id)
    ).all()
    safe_attributes = {
        attribute.key: attribute.value_json
        for attribute in attributes
        if not attribute.high_risk or attribute.user_confirmed
    }
    profile = {**product.profile_json, "attributes": safe_attributes}
    generated = request.app.state.ai_provider.generate_prompt_plan(
        profile,
        payload.generation_type,
        payload.image_count,
    )
    plan = models.PromptPlan(
        product_id=product.id,
        generation_type=payload.generation_type.value,
        image_count=payload.image_count,
        state="awaiting_prompt_confirmation",
        plan_json=generated,
        active_version=1,
    )
    db.add(plan)
    db.flush()
    db.add(
        models.PromptVersion(
            prompt_plan_id=plan.id,
            version=1,
            content_json=generated,
            source="ai",
        )
    )
    db.commit()
    return JSONResponse(
        status_code=201,
        content=envelope(prompt_plan_payload(plan), request_id(request)),
    )


@router.post("/prompt-plans/{plan_id}/regenerate")
def regenerate_prompt_plan(
    plan_id: str,
    payload: PromptRegenerate,
    request: Request,
    _: str = Header(alias="Idempotency-Key", min_length=8, max_length=200),
    user: models.User = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    plan, product = _owned_plan(db, plan_id, user)
    generated = request.app.state.ai_provider.generate_prompt_plan(
        product.profile_json,
        GenerationType(plan.generation_type),
        plan.image_count,
        payload.instruction,
    )
    plan.active_version += 1
    plan.plan_json = generated
    plan.state = "awaiting_prompt_confirmation"
    db.add(
        models.PromptVersion(
            prompt_plan_id=plan.id,
            version=plan.active_version,
            content_json=generated,
            source="ai_regenerated",
        )
    )
    db.commit()
    return envelope(prompt_plan_payload(plan), request_id(request))


@router.post("/prompt-plans/{plan_id}/confirm")
def confirm_prompt_plan(
    plan_id: str,
    payload: PromptConfirmation,
    request: Request,
    _: str = Header(alias="Idempotency-Key", min_length=8, max_length=200),
    user: models.User = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    plan, _ = _owned_plan(db, plan_id, user)
    if payload.plan != plan.plan_json:
        plan.active_version += 1
        plan.plan_json = payload.plan
        db.add(
            models.PromptVersion(
                prompt_plan_id=plan.id,
                version=plan.active_version,
                content_json=payload.plan,
                source="user",
            )
        )
    plan.state = "confirmed"
    plan.confirmed_at = datetime.now(UTC)
    db.commit()
    return envelope(prompt_plan_payload(plan), request_id(request))
