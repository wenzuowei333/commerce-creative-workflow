import base64
from io import BytesIO

import httpx
import pytest
from PIL import Image

from app.config import Settings
from app.core.errors import AppError
from app.domain.generation import GenerationType
from app.providers import OpenAICompatibleProvider, ReferenceImage


def _settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "ai_mode": "compatible",
        "openai_compat_base_url": "https://gateway.example/openai/v1",
        "openai_compat_api_key": "test-provider-key",
        "vision_model": "vision-model",
        "prompt_model": "prompt-model",
        "image_model": "image-model",
    }
    values.update(overrides)
    return Settings(**values)


def _reference() -> ReferenceImage:
    buffer = BytesIO()
    Image.new("RGB", (640, 640), "#34a89a").save(buffer, "PNG")
    return ReferenceImage("front.png", "image/png", buffer.getvalue())


def test_prompt_generation_uses_prompt_model_and_preserves_gateway_prefix():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "output_text": (
                    '{"generation_type":"main","image_count":5,"quality":"medium",'
                    '"size":"1024x1024","directions":[]}'
                )
            },
        )

    provider = OpenAICompatibleProvider(_settings())
    provider.client = httpx.Client(
        base_url="https://gateway.example/openai/v1/",
        transport=httpx.MockTransport(handler),
    )

    provider.generate_prompt_plan({"name": "测试商品"}, GenerationType.MAIN, 5)

    assert requests[0].url.path == "/openai/v1/responses"
    assert requests[0].read()
    assert b'"model":"prompt-model"' in requests[0].content


def test_image_generation_accepts_base64_image_response():
    expected = _reference().content

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/openai/v1/images/edits"
        return httpx.Response(
            200,
            json={"data": [{"b64_json": base64.b64encode(expected).decode()}]},
        )

    provider = OpenAICompatibleProvider(_settings())
    provider.client = httpx.Client(
        base_url="https://gateway.example/openai/v1/",
        transport=httpx.MockTransport(handler),
    )

    result = provider.generate_image(
        prompt="保持商品一致",
        images=[_reference()],
        size="1024x1024",
        quality="medium",
        output_format="webp",
    )

    assert result == expected


def test_provider_timeout_is_safe_and_retryable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    provider = OpenAICompatibleProvider(_settings())
    provider.client = httpx.Client(
        base_url="https://gateway.example/openai/v1/",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(AppError) as error:
        provider.analyze_product({"name": "测试商品"}, [_reference()])

    assert error.value.code == "provider_unavailable"
    assert error.value.retryable is True
    assert "timed out" not in error.value.message


def test_detail_prompt_uses_supported_portrait_size():
    from app.providers import MockAIProvider

    plan = MockAIProvider().generate_prompt_plan({"name": "测试商品"}, GenerationType.DETAIL, 5)

    assert plan["size"] == "1024x1536"
