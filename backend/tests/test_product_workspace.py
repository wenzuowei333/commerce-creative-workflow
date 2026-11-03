from tests.support import build_client, create_product, login, upload_ready_asset


def test_product_workspace_detail_contains_assets_and_latest_workflow(tmp_path):
    with build_client(tmp_path) as client:
        csrf = login(client)
        product = create_product(client, csrf, "workspace")
        asset = upload_ready_asset(client, csrf, product["id"])

        detail = client.get(f"/api/v1/products/{product['id']}")

        assert detail.status_code == 200
        workspace = detail.json()["data"]
        assert workspace["product"]["id"] == product["id"]
        assert workspace["assets"][0]["id"] == asset["id"]
        assert workspace["assets"][0]["thumbnail_url"]
        thumbnail = client.get(workspace["assets"][0]["thumbnail_url"])
        assert thumbnail.status_code == 200
        assert thumbnail.headers["content-type"] == "image/webp"
        assert workspace["latest_analysis"] is None
        assert workspace["latest_prompt_plan"] is None


def test_asset_can_be_restored_during_seven_day_recycle_window(tmp_path):
    with build_client(tmp_path) as client:
        csrf = login(client)
        product = create_product(client, csrf, "recycle")
        asset = upload_ready_asset(client, csrf, product["id"])

        deleted = client.delete(
            f"/api/v1/assets/{asset['id']}",
            headers={"X-CSRF-Token": csrf},
        )
        assert deleted.status_code == 200
        recycle_bin = client.get("/api/v1/recycle-bin")
        entry = recycle_bin.json()["data"][0]
        assert entry["object_id"] == asset["id"]

        restored = client.post(
            f"/api/v1/recycle-bin/{entry['id']}/restore",
            headers={"Idempotency-Key": "restore-one-asset", "X-CSRF-Token": csrf},
        )
        assert restored.status_code == 200
        detail = client.get(f"/api/v1/products/{product['id']}")
        assert [item["id"] for item in detail.json()["data"]["assets"]] == [asset["id"]]
