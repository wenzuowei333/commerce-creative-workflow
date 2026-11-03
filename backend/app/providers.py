import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Protocol

import httpx
from PIL import Image, ImageDraw

from app.config import Settings
from app.core.errors import AppError
from app.domain.generation import GenerationType, build_direction_slots


@dataclass(frozen=True)
class ReferenceImage:
    name: str
    content_type: str
    content: bytes


class AIProvider(Protocol):
    def analyze_product(
        self,
        product: dict[str, Any],
        images: list[ReferenceImage],
    ) -> dict[str, Any]: ...

    def generate_prompt_plan(
        self,
        profile: dict[str, Any],
        generation_type: GenerationType,
        image_count: int,
        instruction: str = "",
    ) -> dict[str, Any]: ...

    def generate_image(
        self,
        *,
        prompt: str,
        images: list[ReferenceImage],
        size: str,
        quality: str,
        output_format: str,
    ) -> bytes: ...


def optimized_reference(image: ReferenceImage) -> ReferenceImage:
    with Image.open(BytesIO(image.content)) as source:
        source = source.convert("RGB")
        source.thumbnail((2048, 2048))
        buffer = BytesIO()
        source.save(buffer, format="JPEG", quality=90, optimize=True)
    return ReferenceImage(
        name=f"{image.name}.jpg",
        content_type="image/jpeg",
        content=buffer.getvalue(),
    )


class MockAIProvider:
    STYLES = ("清爽白底电商", "自然生活场景", "高级质感光影")

    def analyze_product(
        self,
        product: dict[str, Any],
        images: list[ReferenceImage],
    ) -> dict[str, Any]:
        asset_ids = [image.name for image in images]
        return {
            "profile": {
                "name": product["name"],
                "category": "通用实物商品",
                "brand": product.get("brand", ""),
                "sku": product.get("sku", ""),
                "colors": ["青绿色", "白色"],
                "materials": ["以用户确认为准"],
                "packaging": "可见商品包装",
                "structure": "保持参考图中的比例、轮廓和关键结构",
                "selling_points": ["突出商品外观与使用价值"],
                "audience": "主流电商消费者",
                "scenes": ["棚拍", "生活方式场景"],
                "consistency_constraints": ["不得修改品牌、颜色、比例、包装文字和关键结构"],
                "forbidden_content": ["不得添加未经确认的功效、认证、成分和规格"],
            },
            "attributes": [
                {
                    "key": "category",
                    "value": "通用实物商品",
                    "confidence": 0.86,
                    "inference_kind": "inferred",
                    "source_asset_ids": asset_ids,
                    "user_confirmed": False,
                    "high_risk": False,
                },
                {
                    "key": "primary_color",
                    "value": "青绿色",
                    "confidence": 0.94,
                    "inference_kind": "observed",
                    "source_asset_ids": asset_ids,
                    "user_confirmed": False,
                    "high_risk": False,
                },
            ],
            "summary": "已综合多角度素材生成商品档案，请确认推测字段。",
        }

    def generate_prompt_plan(
        self,
        profile: dict[str, Any],
        generation_type: GenerationType,
        image_count: int,
        instruction: str = "",
    ) -> dict[str, Any]:
        slots = build_direction_slots(generation_type, image_count)
        directions = []
        for slot in slots:
            style = self.STYLES[slot.index]
            base_prompt = (
                f"为{profile.get('name', '参考商品')}制作{generation_type.value}电商图片。"
                f"视觉方向：{style}。严格保持商品品牌、包装、颜色、比例与关键结构。"
                f"{instruction}".strip()
            )
            variants = []
            for item in slot.items:
                module_text = f"，详情模块：{item.module}" if item.module else ""
                variants.append(
                    {
                        "index": item.index,
                        "module": item.module,
                        "prompt": f"{base_prompt}{module_text}，构图变体 {item.index + 1}。",
                    }
                )
            directions.append(
                {
                    "index": slot.index,
                    "title": style,
                    "rationale": "根据商品外观、品类和国内电商展示需求自动选择。",
                    "base_prompt": base_prompt,
                    "negative_prompt": (
                        "禁止改变商品Logo、包装文字、颜色、比例和材质；禁止重复商品、畸变、"
                        "水印以及未经确认的功效、认证、成分和规格。"
                    ),
                    "variants": variants,
                }
            )
        return {
            "generation_type": generation_type.value,
            "image_count": image_count,
            "quality": "medium",
            "size": "1024x1024" if generation_type == GenerationType.MAIN else "1024x1536",
            "directions": directions,
        }

    def generate_image(
        self,
        *,
        prompt: str,
        images: list[ReferenceImage],
        size: str,
        quality: str,
        output_format: str,
    ) -> bytes:
        width, height = (int(value) for value in size.split("x", maxsplit=1))
        digest = hashlib.sha256(prompt.encode()).digest()
        color = (80 + digest[0] // 3, 100 + digest[1] // 3, 110 + digest[2] // 3)
        canvas = Image.new("RGB", (width, height), color)
        draw = ImageDraw.Draw(canvas)
        margin = max(32, width // 12)
        draw.rounded_rectangle(
            (margin, margin, width - margin, height - margin),
            radius=max(16, width // 30),
            fill=(245, 248, 247),
        )
        draw.text((margin * 2, margin * 2), "MOCK PREVIEW - SYNTHETIC DEMO", fill=(25, 55, 52))
        buffer = BytesIO()
        format_name = "WEBP" if output_format == "webp" else "PNG"
        canvas.save(buffer, format=format_name, quality=90)
        return buffer.getvalue()


class OpenAICompatibleProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        normalized_base = settings.openai_compat_base_url.rstrip("/")
        self.api_prefix = "" if normalized_base.endswith("/v1") else "v1/"
        self.client = httpx.Client(
            base_url=f"{normalized_base}/",
            headers={"Authorization": f"Bearer {settings.openai_compat_api_key}"},
            timeout=httpx.Timeout(180.0, connect=15.0),
        )

    def _request(self, method: str, resource: str, **kwargs: Any) -> httpx.Response:
        try:
            target = (
                resource
                if resource.startswith(("http://", "https://"))
                else f"{self.api_prefix}{resource}"
            )
            return self.client.request(method, target, **kwargs)
        except httpx.RequestError as exc:
            raise AppError(
                code="provider_unavailable",
                message="模型服务暂时无法连接，请稍后重试",
                retryable=True,
                status_code=503,
            ) from exc

    @staticmethod
    def _extract_json(response: httpx.Response) -> dict[str, Any]:
        OpenAICompatibleProvider._raise_for_status(response)
        payload = response.json()
        text = payload.get("output_text")
        if not text:
            for output in payload.get("output", []):
                for content in output.get("content", []):
                    if content.get("type") in {"output_text", "text"}:
                        text = content.get("text")
                        break
        if not text:
            choices = payload.get("choices", [])
            if choices:
                text = choices[0].get("message", {}).get("content")
        if not text:
            raise AppError(
                code="provider_invalid_response",
                message="模型未返回结构化结果",
                retryable=True,
                status_code=502,
            )
        try:
            if text.startswith("```"):
                text = text.strip("`").removeprefix("json").strip()
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise AppError(
                code="provider_invalid_json",
                message="模型返回内容无法解析",
                retryable=True,
                status_code=502,
            ) from exc

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.is_success:
            return
        retryable = response.status_code == 429 or response.status_code >= 500
        code = "provider_rate_limited" if response.status_code == 429 else "provider_request_failed"
        raise AppError(
            code=code,
            message="模型服务繁忙，请稍后重试" if retryable else "模型请求被拒绝",
            retryable=retryable,
            status_code=503 if retryable else 422,
            details={"provider_status": response.status_code},
        )

    def _responses(
        self,
        prompt: str,
        images: list[ReferenceImage],
        *,
        model: str,
    ) -> dict[str, Any]:
        content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
        for image in images:
            prepared = optimized_reference(image)
            encoded = base64.b64encode(prepared.content).decode()
            content.append(
                {
                    "type": "input_image",
                    "image_url": f"data:{prepared.content_type};base64,{encoded}",
                }
            )
        response = self._request(
            "POST",
            "responses",
            json={
                "model": model,
                "input": [{"role": "user", "content": content}],
            },
        )
        return self._extract_json(response)

    def analyze_product(
        self,
        product: dict[str, Any],
        images: list[ReferenceImage],
    ) -> dict[str, Any]:
        prompt = (
            "分析这些同一SKU的商品图片，返回JSON，字段必须包含 profile、attributes、summary。"
            "attributes每项包含key、value、confidence、inference_kind、source_asset_ids、"
            "user_confirmed、high_risk。无法确认的信息允许合理推测但必须标记 inferred；"
            "功效、认证、成分、规格属于高风险字段。商品基础信息："
            + json.dumps(product, ensure_ascii=False)
        )
        return self._responses(prompt, images, model=self.settings.vision_model)

    def generate_prompt_plan(
        self,
        profile: dict[str, Any],
        generation_type: GenerationType,
        image_count: int,
        instruction: str = "",
    ) -> dict[str, Any]:
        prompt = (
            "为国内电商生成结构化生图方案JSON。必须包含generation_type、image_count、quality、"
            "size、directions；每个direction包含title、rationale、base_prompt、negative_prompt、"
            "variants，每个方向固定5个variants。详情图模块依次为hero、selling_point、detail、"
            "scene、closing。不得使用未经确认的事实。商品信息："
            + json.dumps(profile, ensure_ascii=False)
            + f"\n类型：{generation_type.value}，数量：{image_count}，补充要求：{instruction}"
        )
        return self._responses(prompt, [], model=self.settings.prompt_model)

    def generate_image(
        self,
        *,
        prompt: str,
        images: list[ReferenceImage],
        size: str,
        quality: str,
        output_format: str,
    ) -> bytes:
        files = []
        for image in images:
            prepared = optimized_reference(image)
            files.append(("image[]", (prepared.name, prepared.content, prepared.content_type)))
        response = self._request(
            "POST",
            "images/edits",
            data={
                "model": self.settings.image_model,
                "prompt": prompt,
                "n": "1",
                "size": size,
                "quality": quality,
                "output_format": output_format,
            },
            files=files,
        )
        self._raise_for_status(response)
        try:
            result = response.json()["data"][0]
            if result.get("b64_json"):
                return base64.b64decode(result["b64_json"], validate=True)
            if result.get("url"):
                download = self._request("GET", result["url"])
                self._raise_for_status(download)
                if len(download.content) > 40 * 1024 * 1024:
                    raise ValueError("generated image is too large")
                return download.content
            raise KeyError("image payload")
        except (KeyError, ValueError, binascii.Error) as exc:
            raise AppError(
                code="provider_invalid_image",
                message="模型未返回有效图片",
                retryable=True,
                status_code=502,
            ) from exc


def build_ai_provider(settings: Settings) -> AIProvider:
    if settings.ai_mode == "mock":
        return MockAIProvider()
    if not settings.openai_compat_base_url or not settings.openai_compat_api_key:
        raise RuntimeError("OpenAI-compatible provider configuration is incomplete")
    return OpenAICompatibleProvider(settings)
