import hashlib
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import create_app


def build_client(tmp_path: Path, **overrides) -> TestClient:
    values = {
        "_env_file": None,
        "environment": "test",
        "database_url": f"sqlite:///{tmp_path / 'test.db'}",
        "media_backend": "local",
        "media_root": str(tmp_path / "media"),
        "queue_mode": "inline",
        "session_backend": "memory",
        "ai_mode": "mock",
        "feature_hd_finalize": True,
        "feature_templates": True,
        "admin_username": "admin",
        "admin_password": "test-password",
        "session_secret": "test-secret-that-is-long-enough",
    }
    values.update(overrides)
    return TestClient(create_app(Settings(**values)))


def login(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "test-password"},
    )
    assert response.status_code == 200
    return response.json()["data"]["csrf_token"]


def create_product(client: TestClient, csrf_token: str, suffix: str = "1") -> dict:
    response = client.post(
        "/api/v1/products",
        headers={"Idempotency-Key": f"create-product-{suffix}", "X-CSRF-Token": csrf_token},
        json={
            "name": f"测试商品-{suffix}",
            "sku": f"SKU-{suffix}",
            "brand": "测试品牌",
        },
    )
    assert response.status_code == 201
    return response.json()["data"]


def upload_ready_asset(client: TestClient, csrf_token: str, product_id: str) -> dict:
    buffer = BytesIO()
    Image.new("RGB", (640, 640), "#39a89b").save(buffer, format="PNG")
    content = buffer.getvalue()
    upload_request = client.post(
        "/api/v1/assets/upload-requests",
        headers={"Idempotency-Key": "upload-ready-asset", "X-CSRF-Token": csrf_token},
        json={
            "product_id": product_id,
            "files": [
                {
                    "name": "front.png",
                    "content_type": "image/png",
                    "size_bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            ],
        },
    )
    upload = upload_request.json()["data"][0]
    response = client.put(upload["upload_url"], content=content, headers=upload["headers"])
    assert response.status_code == 204
    confirmed = client.post(
        f"/api/v1/assets/{upload['asset_id']}/confirm",
        headers={"Idempotency-Key": "confirm-ready-asset", "X-CSRF-Token": csrf_token},
    )
    assert confirmed.status_code == 200
    return confirmed.json()["data"]


def prepare_confirmed_prompt(
    client: TestClient,
    csrf_token: str,
    *,
    image_count: int = 5,
    generation_type: str = "main",
    suffix: str = "generation",
) -> tuple[dict, dict]:
    product = create_product(client, csrf_token, suffix)
    upload_ready_asset(client, csrf_token, product["id"])
    analysis_response = client.post(
        f"/api/v1/products/{product['id']}/analysis",
        headers={
            "Idempotency-Key": f"analysis-{suffix}",
            "X-CSRF-Token": csrf_token,
        },
    )
    assert analysis_response.status_code == 201
    analysis = analysis_response.json()["data"]
    confirmation = client.post(
        f"/api/v1/analysis/{analysis['id']}/confirm",
        headers={
            "Idempotency-Key": f"analysis-confirm-{suffix}",
            "X-CSRF-Token": csrf_token,
        },
        json={
            "profile": analysis["result"]["profile"],
            "attributes": analysis["result"]["attributes"],
        },
    )
    assert confirmation.status_code == 200
    prompt_response = client.post(
        "/api/v1/prompt-plans",
        headers={
            "Idempotency-Key": f"prompt-{suffix}",
            "X-CSRF-Token": csrf_token,
        },
        json={
            "product_id": product["id"],
            "generation_type": generation_type,
            "image_count": image_count,
        },
    )
    assert prompt_response.status_code == 201
    plan = prompt_response.json()["data"]
    prompt_confirmation = client.post(
        f"/api/v1/prompt-plans/{plan['id']}/confirm",
        headers={
            "Idempotency-Key": f"prompt-confirm-{suffix}",
            "X-CSRF-Token": csrf_token,
        },
        json={"plan": plan["plan"]},
    )
    assert prompt_confirmation.status_code == 200
    return product, prompt_confirmation.json()["data"]
