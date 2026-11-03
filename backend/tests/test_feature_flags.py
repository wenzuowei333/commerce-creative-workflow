from tests.support import build_client, login


def test_system_exposes_public_feature_flags(tmp_path):
    with build_client(tmp_path, feature_templates=False) as client:
        login(client)

        response = client.get("/api/v1/system")

    assert response.status_code == 200
    assert response.json()["data"]["features"]["templates"] is False
    assert response.json()["data"]["features"]["image_revisions"] is True


def test_disabled_features_are_blocked_at_the_api_boundary(tmp_path):
    with build_client(
        tmp_path,
        feature_templates=False,
        feature_hd_finalize=False,
    ) as client:
        csrf = login(client)
        headers = {
            "Idempotency-Key": "disabled-feature-check",
            "X-CSRF-Token": csrf,
        }

        templates = client.get("/api/v1/templates")
        finalize = client.post("/api/v1/images/missing/finalize", headers=headers)

    assert templates.status_code == 404
    assert templates.json()["error"]["code"] == "feature_disabled"
    assert finalize.status_code == 404
    assert finalize.json()["error"]["code"] == "feature_disabled"
