from tests.support import build_client, create_product, login, upload_ready_asset


def test_analysis_confirmation_and_prompt_plan_flow(tmp_path):
    with build_client(tmp_path) as client:
        csrf = login(client)
        product = create_product(client, csrf)
        asset = upload_ready_asset(client, csrf, product["id"])

        analysis_response = client.post(
            f"/api/v1/products/{product['id']}/analysis",
            headers={"Idempotency-Key": "analysis-start-1", "X-CSRF-Token": csrf},
        )
        assert analysis_response.status_code == 201
        analysis = analysis_response.json()["data"]
        assert analysis["status"] == "awaiting_product_confirmation"
        assert analysis["result"]["attributes"]

        profile = analysis["result"]["profile"]
        attributes = analysis["result"]["attributes"]
        attributes.append(
            {
                "key": "unverified_claim",
                "value": "低糖",
                "confidence": 0.4,
                "inference_kind": "inferred",
                "source_asset_ids": [asset["id"]],
                "user_confirmed": False,
                "high_risk": True,
            }
        )
        confirmed = client.post(
            f"/api/v1/analysis/{analysis['id']}/confirm",
            headers={"Idempotency-Key": "analysis-confirm-1", "X-CSRF-Token": csrf},
            json={"profile": profile, "attributes": attributes},
        )
        assert confirmed.status_code == 409
        assert confirmed.json()["error"]["code"] == "risk_confirmation_required"
        # Drop the unverified claim before explicitly confirming the product.
        attributes.pop()
        confirmed = client.post(
            f"/api/v1/analysis/{analysis['id']}/confirm",
            headers={"Idempotency-Key": "analysis-confirm-safe", "X-CSRF-Token": csrf},
            json={"profile": profile, "attributes": attributes},
        )
        assert confirmed.status_code == 200

        prompt_response = client.post(
            "/api/v1/prompt-plans",
            headers={"Idempotency-Key": "prompt-plan-1", "X-CSRF-Token": csrf},
            json={"product_id": product["id"], "generation_type": "main", "image_count": 15},
        )
        prompt_plan = prompt_response.json()["data"]

        assert prompt_response.status_code == 201
        assert prompt_plan["state"] == "awaiting_prompt_confirmation"
        assert prompt_plan["active_version"] == 1
        assert len(prompt_plan["plan"]["directions"]) == 3
        assert "低糖" not in str(prompt_plan["plan"])

        regenerated = client.post(
            f"/api/v1/prompt-plans/{prompt_plan['id']}/regenerate",
            headers={"Idempotency-Key": "prompt-regenerate-1", "X-CSRF-Token": csrf},
            json={"instruction": "整体更高级，减少装饰元素"},
        )
        assert regenerated.status_code == 200
        assert regenerated.json()["data"]["active_version"] == 2

        final_plan = regenerated.json()["data"]["plan"]
        confirmation = client.post(
            f"/api/v1/prompt-plans/{prompt_plan['id']}/confirm",
            headers={"Idempotency-Key": "prompt-confirm-1", "X-CSRF-Token": csrf},
            json={"plan": final_plan},
        )
        assert confirmation.status_code == 200
        assert confirmation.json()["data"]["state"] == "confirmed"


def test_prompt_plan_requires_confirmed_analysis(tmp_path):
    with build_client(tmp_path) as client:
        csrf = login(client)
        product = create_product(client, csrf)
        response = client.post(
            "/api/v1/prompt-plans",
            headers={"Idempotency-Key": "prompt-too-early", "X-CSRF-Token": csrf},
            json={"product_id": product["id"], "generation_type": "detail", "image_count": 5},
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "analysis_not_confirmed"
