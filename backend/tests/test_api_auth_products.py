from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def build_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        media_backend="local",
        media_root=str(tmp_path / "media"),
        queue_mode="inline",
        session_backend="memory",
        ai_mode="mock",
        admin_username="admin",
        admin_password="test-password",
        session_secret="test-secret-that-is-long-enough",
    )
    return TestClient(create_app(settings))


def login(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "test-password"},
    )
    assert response.status_code == 200
    return response.json()["data"]["csrf_token"]


def test_products_require_authentication(tmp_path):
    with build_client(tmp_path) as client:
        response = client.get("/api/v1/products")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"
    assert response.json()["error"]["request_id"]


def test_login_create_and_list_product(tmp_path):
    with build_client(tmp_path) as client:
        csrf_token = login(client)
        response = client.post(
            "/api/v1/products",
            headers={"Idempotency-Key": "create-product-1", "X-CSRF-Token": csrf_token},
            json={"name": "柑橘气泡饮", "sku": "CITRUS-330", "brand": "清爽研究所"},
        )
        replay = client.post(
            "/api/v1/products",
            headers={"Idempotency-Key": "create-product-1", "X-CSRF-Token": csrf_token},
            json={"name": "柑橘气泡饮", "sku": "CITRUS-330", "brand": "清爽研究所"},
        )
        listing = client.get("/api/v1/products")

    assert response.status_code == 201
    assert replay.status_code == 201
    assert replay.json()["data"]["id"] == response.json()["data"]["id"]
    assert listing.status_code == 200
    assert len(listing.json()["data"]) == 1
    assert listing.json()["data"][0]["sku"] == "CITRUS-330"


def test_write_request_rejects_missing_csrf(tmp_path):
    with build_client(tmp_path) as client:
        login(client)
        response = client.post(
            "/api/v1/products",
            headers={"Idempotency-Key": "create-product-2"},
            json={"name": "便携榨汁杯", "sku": "JUICER-01"},
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"


def test_login_is_rate_limited_after_repeated_failures(tmp_path):
    with build_client(tmp_path) as client:
        for _ in range(5):
            response = client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": "wrong-password"},
            )
            assert response.status_code == 401
        blocked = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "wrong-password"},
        )

    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "login_rate_limited"
