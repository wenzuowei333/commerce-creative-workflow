"""Showcase input/output validation around the retained Provider contract."""
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from app.core.errors import AppError
from app.domain.generation import DETAIL_MODULES


class Variant(BaseModel):
    index: int = Field(ge=0, le=4)
    module: str | None = None
    prompt: str = Field(min_length=1, max_length=8000)


class Direction(BaseModel):
    index: int = Field(ge=0, le=2)
    title: str = Field(min_length=1, max_length=200)
    rationale: str = Field(default="", max_length=4000)
    base_prompt: str = Field(min_length=1, max_length=8000)
    negative_prompt: str = Field(default="", max_length=4000)
    variants: list[Variant] = Field(min_length=5, max_length=5)


class Recipe(BaseModel):
    generation_type: Literal["main", "detail"]
    image_count: Literal[5, 10, 15]
    quality: Literal["low", "medium", "high"]
    size: Literal["1024x1024", "1024x1536", "1536x1024"]
    directions: list[Direction] = Field(min_length=1, max_length=3)


def validate_plan(data: dict, generation_type: str, image_count: int) -> dict:
    try:
        recipe = Recipe.model_validate(data)
        if recipe.generation_type != generation_type or recipe.image_count != image_count:
            raise ValueError("mismatched plan")
        if [d.index for d in recipe.directions] != list(range(image_count // 5)):
            raise ValueError("direction layout")
        for direction in recipe.directions:
            if [v.index for v in direction.variants] != list(range(5)) or any(not v.prompt.strip() for v in direction.variants):
                raise ValueError("variant layout")
            expected = list(DETAIL_MODULES) if generation_type == "detail" else [None] * 5
            if [v.module for v in direction.variants] != expected:
                raise ValueError("module layout")
    except (ValidationError, ValueError):
        raise AppError(code="prompt_plan_invalid", message="提示词方案结构或图片数量不符合要求", status_code=422) from None
    return recipe.model_dump(mode="json")



def current_analysis(db, product):
    from sqlalchemy import select
    from app import models
    analysis = db.scalar(select(models.AnalysisVersion).where(models.AnalysisVersion.product_id == product.id).order_by(models.AnalysisVersion.version.desc()).limit(1))
    if not analysis or analysis.status != "confirmed" or product.status != "product_confirmed":
        raise AppError(code="analysis_not_confirmed", message="请先确认最新商品识别信息", status_code=409)
    return analysis


def require_current_plan(db, plan, product):
    analysis = current_analysis(db, product)
    if plan.analysis_version_id != analysis.id:
        raise AppError(code="prompt_plan_obsolete", message="商品信息已更新，请重新策划并确认方案", status_code=409)
