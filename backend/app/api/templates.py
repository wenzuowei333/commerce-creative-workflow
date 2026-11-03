import copy
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.api.common import envelope, request_id
from app.api.dependencies import require_csrf, require_feature, require_user
from app.api.serializers import prompt_plan_payload
from app.core.errors import AppError
from app.db import get_db

router = APIRouter(
    prefix="/api/v1",
    tags=["templates"],
    dependencies=[Depends(require_feature("templates"))],
)


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    prompt_plan_id: str


class TemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    recipe: dict[str, Any] | None = None


class TemplateApply(BaseModel):
    product_id: str


def _walk_strings(value: Any, transform) -> Any:
    if isinstance(value, dict):
        return {key: _walk_strings(item, transform) for key, item in value.items()}
    if isinstance(value, list):
        return [_walk_strings(item, transform) for item in value]
    if isinstance(value, str):
        return transform(value)
    return value


def _neutral_recipe(plan: models.PromptPlan, product: models.Product) -> dict[str, Any]:
    replacements = {
        product.name: "{{ product.name }}",
        product.brand: "{{ product.brand }}",
        product.sku: "{{ product.sku }}",
    }

    def neutralize(text: str) -> str:
        result = text
        for source, target in replacements.items():
            if source:
                result = result.replace(source, target)
        return result

    recipe = _walk_strings(copy.deepcopy(plan.plan_json), neutralize)
    recipe["generation_type"] = plan.generation_type
    recipe["image_count"] = plan.image_count
    return recipe


def _render_recipe(recipe: dict[str, Any], product: models.Product) -> dict[str, Any]:
    profile = product.profile_json
    values = {
        "{{ product.name }}": str(profile.get("name", product.name)),
        "{{ product.brand }}": str(profile.get("brand", product.brand)),
        "{{ product.sku }}": str(profile.get("sku", product.sku)),
    }

    def render(text: str) -> str:
        result = text
        for source, target in values.items():
            result = result.replace(source, target)
        return result

    return _walk_strings(copy.deepcopy(recipe), render)


def _template_payload(template: models.Template) -> dict[str, Any]:
    return {
        "id": template.id,
        "name": template.name,
        "generation_type": template.generation_type,
        "recipe": template.recipe_json,
        "is_protected": template.is_protected,
        "created_at": template.created_at.isoformat(),
        "updated_at": template.updated_at.isoformat(),
    }


def _owned_template(db: Session, template_id: str, user: models.User) -> models.Template:
    template = db.get(models.Template, template_id)
    if not template or template.owner_id != user.id or template.deleted_at is not None:
        raise AppError(code="template_not_found", message="模板不存在", status_code=404)
    return template


@router.get("/templates")
def list_templates(
    request: Request,
    user: models.User = Depends(require_user),
    db: Session = Depends(get_db),
):
    templates = db.scalars(
        select(models.Template)
        .where(models.Template.owner_id == user.id, models.Template.deleted_at.is_(None))
        .order_by(models.Template.updated_at.desc())
    ).all()
    return envelope([_template_payload(item) for item in templates], request_id(request))


@router.post("/templates", status_code=201)
def create_template(
    payload: TemplateCreate,
    request: Request,
    _: str = Header(alias="Idempotency-Key", min_length=8, max_length=200),
    user: models.User = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    plan = db.get(models.PromptPlan, payload.prompt_plan_id)
    product = db.get(models.Product, plan.product_id) if plan else None
    if not plan or not product or product.owner_id != user.id:
        raise AppError(code="prompt_plan_not_found", message="提示词方案不存在", status_code=404)
    template = models.Template(
        owner_id=user.id,
        name=payload.name,
        generation_type=plan.generation_type,
        recipe_json=_neutral_recipe(plan, product),
    )
    db.add(template)
    db.commit()
    return JSONResponse(
        status_code=201,
        content=envelope(_template_payload(template), request_id(request)),
    )


@router.patch("/templates/{template_id}")
def update_template(
    template_id: str,
    payload: TemplateUpdate,
    request: Request,
    user: models.User = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    template = _owned_template(db, template_id, user)
    if payload.name is not None:
        template.name = payload.name
    if payload.recipe is not None:
        template.recipe_json = payload.recipe
    db.commit()
    return envelope(_template_payload(template), request_id(request))


@router.post("/templates/{template_id}/copy", status_code=201)
def copy_template(
    template_id: str,
    request: Request,
    _: str = Header(alias="Idempotency-Key", min_length=8, max_length=200),
    user: models.User = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    source = _owned_template(db, template_id, user)
    copied = models.Template(
        owner_id=user.id,
        name=f"{source.name} 副本",
        generation_type=source.generation_type,
        recipe_json=copy.deepcopy(source.recipe_json),
    )
    db.add(copied)
    db.commit()
    return JSONResponse(
        status_code=201,
        content=envelope(_template_payload(copied), request_id(request)),
    )


@router.delete("/templates/{template_id}")
def delete_template(
    template_id: str,
    request: Request,
    user: models.User = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    template = _owned_template(db, template_id, user)
    if template.is_protected:
        raise AppError(
            code="template_protected",
            message="系统模板不能删除，可以先复制后编辑",
            status_code=409,
        )
    template.deleted_at = datetime.now(UTC)
    db.commit()
    return envelope({"deleted": True, "id": template.id}, request_id(request))


@router.post("/templates/{template_id}/apply", status_code=201)
def apply_template(
    template_id: str,
    payload: TemplateApply,
    request: Request,
    _: str = Header(alias="Idempotency-Key", min_length=8, max_length=200),
    user: models.User = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    template = _owned_template(db, template_id, user)
    product = db.get(models.Product, payload.product_id)
    if not product or product.owner_id != user.id:
        raise AppError(code="product_not_found", message="商品不存在", status_code=404)
    if product.status != "product_confirmed":
        raise AppError(
            code="analysis_not_confirmed",
            message="请先确认商品识别信息",
            status_code=409,
        )
    rendered = _render_recipe(template.recipe_json, product)
    plan = models.PromptPlan(
        product_id=product.id,
        generation_type=template.generation_type,
        image_count=int(rendered.get("image_count", 5)),
        state="awaiting_prompt_confirmation",
        plan_json=rendered,
        active_version=1,
    )
    db.add(plan)
    db.flush()
    db.add(
        models.PromptVersion(
            prompt_plan_id=plan.id,
            version=1,
            content_json=rendered,
            source="template",
        )
    )
    db.commit()
    return JSONResponse(
        status_code=201,
        content=envelope(prompt_plan_payload(plan), request_id(request)),
    )
