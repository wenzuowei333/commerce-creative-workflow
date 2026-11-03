import hashlib
from io import BytesIO

from PIL import Image

from tests.support import build_client, create_product, login


def make_png(size: tuple[int, int] = (640, 640), color: str = "#39a89b") -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def test_upload_and_confirm_product_asset(tmp_path):
    image_bytes = make_png()
    sha256 = hashlib.sha256(image_bytes).hexdigest()

    with build_client(tmp_path) as client:
        csrf = login(client)
        product = create_product(client, csrf)
        request_upload = client.post(
            "/api/v1/assets/upload-requests",
            headers={"Idempotency-Key": "asset-upload-request-1", "X-CSRF-Token": csrf},
            json={
                "product_id": product["id"],
                "files": [
                    {
                        "name": "front.png",
                        "content_type": "image/png",
                        "size_bytes": len(image_bytes),
                        "sha256": sha256,
                    }
                ],
            },
        )
        assert request_upload.status_code == 201
        upload = request_upload.json()["data"][0]

        put_response = client.put(
            upload["upload_url"],
            content=image_bytes,
            headers={"Content-Type": "image/png", **upload["headers"]},
        )
        confirmed = client.post(
            f"/api/v1/assets/{upload['asset_id']}/confirm",
            headers={"Idempotency-Key": "asset-confirm-1", "X-CSRF-Token": csrf},
        )
        primary = client.patch(
            f"/api/v1/assets/{upload['asset_id']}",
            headers={"X-CSRF-Token": csrf},
            json={"is_primary": True, "angle": "front", "position": 0},
        )

    assert put_response.status_code == 204
    assert confirmed.status_code == 200
    assert confirmed.json()["data"]["status"] == "ready"
    assert confirmed.json()["data"]["width"] == 640
    assert primary.json()["data"]["is_primary"] is True
    assert primary.json()["data"]["angle"] == "front"


def test_asset_upload_rejects_ninth_image(tmp_path):
    image_bytes = make_png()
    with build_client(tmp_path) as client:
        csrf = login(client)
        product = create_product(client, csrf)
        files = [
            {
                "name": f"view-{index}.png",
                "content_type": "image/png",
                "size_bytes": len(image_bytes),
                "sha256": hashlib.sha256(image_bytes + bytes([index])).hexdigest(),
            }
            for index in range(9)
        ]
        response = client.post(
            "/api/v1/assets/upload-requests",
            headers={"Idempotency-Key": "asset-upload-request-9", "X-CSRF-Token": csrf},
            json={"product_id": product["id"], "files": files},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "asset_limit_exceeded"


def test_confirm_rejects_image_below_minimum_resolution(tmp_path):
    image_bytes = make_png((128, 128))
    with build_client(tmp_path) as client:
        csrf = login(client)
        product = create_product(client, csrf)
        request_upload = client.post(
            "/api/v1/assets/upload-requests",
            headers={"Idempotency-Key": "asset-upload-small", "X-CSRF-Token": csrf},
            json={
                "product_id": product["id"],
                "files": [
                    {
                        "name": "small.png",
                        "content_type": "image/png",
                        "size_bytes": len(image_bytes),
                        "sha256": hashlib.sha256(image_bytes).hexdigest(),
                    }
                ],
            },
        )
        upload = request_upload.json()["data"][0]
        client.put(
            upload["upload_url"],
            content=image_bytes,
            headers={"Content-Type": "image/png", **upload["headers"]},
        )
        response = client.post(
            f"/api/v1/assets/{upload['asset_id']}/confirm",
            headers={"Idempotency-Key": "asset-confirm-small", "X-CSRF-Token": csrf},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "asset_resolution_too_small"
