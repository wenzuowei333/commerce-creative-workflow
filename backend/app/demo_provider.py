"""Explicit showcase Mock adapter. No network and no state shortcuts."""
import time

from app.core.errors import AppError
from app.providers import MockAIProvider


class ShowcaseMockProvider(MockAIProvider):
    def analyze_product(self, product, images):
        result = super().analyze_product(product, images)
        result["attributes"].append({
            "key": "material_needs_confirmation", "value": "未知，请人工填写或保留未知",
            "confidence": 0.2, "inference_kind": "inferred",
            "source_asset_ids": [image.name for image in images],
            "user_confirmed": False, "high_risk": True,
        })
        result["summary"] = "Mock 固定示例，不代表模型识别效果；材质未知，需要人工确认。"
        return result


def before_demo_generation(settings, batch, item):
    if settings.environment != "demo" or settings.ai_mode != "mock":
        return
    time.sleep(settings.demo_generation_delay_seconds)
    if batch.demo_scenario == "partial_once" and item.kind == "initial" and item.index == 2 and item.attempts == 1:
        # Deliberately requires manual retry so broker automatic retries do not hide the failure.
        raise AppError(code="demo_manual_retry_required", message="Mock 演示：第 3 张首次失败，请仅重试失败项", retryable=False, status_code=503)
