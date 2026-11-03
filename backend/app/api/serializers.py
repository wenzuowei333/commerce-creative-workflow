from app import models


def product_payload(product: models.Product) -> dict:
    return {
        "id": product.id,
        "name": product.name,
        "sku": product.sku,
        "brand": product.brand,
        "status": product.status,
        "profile": product.profile_json,
        "created_at": product.created_at.isoformat(),
        "updated_at": product.updated_at.isoformat(),
    }


def asset_payload(asset: models.ProductAsset) -> dict:
    return {
        "id": asset.id,
        "product_id": asset.product_id,
        "name": asset.original_name,
        "content_type": asset.content_type,
        "size_bytes": asset.size_bytes,
        "sha256": asset.sha256,
        "width": asset.width,
        "height": asset.height,
        "position": asset.position,
        "is_primary": asset.is_primary,
        "angle": asset.angle,
        "status": asset.status,
        "preview_url": f"/api/v1/assets/{asset.id}/content",
        "thumbnail_url": f"/api/v1/assets/{asset.id}/thumbnail",
    }


def analysis_payload(analysis: models.AnalysisVersion | None) -> dict | None:
    if not analysis:
        return None
    return {
        "id": analysis.id,
        "product_id": analysis.product_id,
        "version": analysis.version,
        "status": analysis.status,
        "result": analysis.result_json,
        "confirmed_at": analysis.confirmed_at.isoformat() if analysis.confirmed_at else None,
    }


def prompt_plan_payload(plan: models.PromptPlan | None) -> dict | None:
    if not plan:
        return None
    return {
        "id": plan.id,
        "product_id": plan.product_id,
        "generation_type": plan.generation_type,
        "image_count": plan.image_count,
        "state": plan.state,
        "plan": plan.plan_json,
        "active_version": plan.active_version,
        "confirmed_at": plan.confirmed_at.isoformat() if plan.confirmed_at else None,
    }
