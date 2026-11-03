import json

from app.providers import MockAIProvider
from tests.support import build_client, login, prepare_confirmed_prompt


class CountingProvider(MockAIProvider):
    def __init__(self) -> None:
        self.image_calls = 0

    def generate_image(self, **kwargs) -> bytes:
        self.image_calls += 1
        return super().generate_image(**kwargs)


def generate_five(client, csrf, plan, key="generate-results"):
    response = client.post(
        "/api/v1/generation-batches",
        headers={"Idempotency-Key": key, "X-CSRF-Token": csrf},
        json={"prompt_plan_id": plan["id"]},
    )
    assert response.status_code == 201
    return response.json()["data"]


def test_bulk_revisions_preserve_parents_and_finalize_creates_png_child(tmp_path):
    with build_client(tmp_path) as client:
        csrf = login(client)
        _, plan = prepare_confirmed_prompt(client, csrf, suffix="versions")
        provider = CountingProvider()
        client.app.state.ai_provider = provider
        batch = generate_five(client, csrf, plan)
        parent_ids = [item["image"]["id"] for item in batch["items"][:2]]

        revision_response = client.post(
            "/api/v1/image-revisions",
            headers={"Idempotency-Key": "bulk-revise-two", "X-CSRF-Token": csrf},
            json={"image_ids": parent_ids, "instruction": "背景更明亮，减少装饰元素"},
        )
        assert revision_response.status_code == 201
        revisions = revision_response.json()["data"]
        assert len(revisions) == 2
        assert {revision["parent_image_id"] for revision in revisions} == set(parent_ids)
        assert all(revision["child_image"]["format"] == "webp" for revision in revisions)
        assert all(revision["child_image"]["quality"] == "medium" for revision in revisions)

        final_response = client.post(
            f"/api/v1/images/{revisions[0]['child_image']['id']}/finalize",
            headers={"Idempotency-Key": "finalize-one", "X-CSRF-Token": csrf},
        )
        assert final_response.status_code == 201
        finalized = final_response.json()["data"]
        assert finalized["parent_image_id"] == revisions[0]["child_image"]["id"]
        assert finalized["child_image"]["format"] == "png"
        assert finalized["child_image"]["quality"] == "high"
        assert provider.image_calls == 8

        original = client.get(f"/api/v1/images/{parent_ids[0]}/content")
        final_file = client.get(f"/api/v1/images/{finalized['child_image']['id']}/content")
        assert original.status_code == 200
        assert original.headers["content-type"] == "image/webp"
        assert final_file.status_code == 200
        assert final_file.headers["content-type"] == "image/png"


def test_template_is_product_neutral_and_can_be_applied_to_another_product(tmp_path):
    with build_client(tmp_path) as client:
        csrf = login(client)
        old_product, old_plan = prepare_confirmed_prompt(
            client,
            csrf,
            suffix="old-template",
        )
        template_response = client.post(
            "/api/v1/templates",
            headers={"Idempotency-Key": "save-template-one", "X-CSRF-Token": csrf},
            json={"name": "清爽主图模板", "prompt_plan_id": old_plan["id"]},
        )
        assert template_response.status_code == 201
        template = template_response.json()["data"]
        assert old_product["name"] not in json.dumps(template["recipe"], ensure_ascii=False)
        assert "{{ product.name }}" in json.dumps(template["recipe"], ensure_ascii=False)

        new_product, _ = prepare_confirmed_prompt(
            client,
            csrf,
            suffix="new-template",
        )
        applied_response = client.post(
            f"/api/v1/templates/{template['id']}/apply",
            headers={"Idempotency-Key": "apply-template-new", "X-CSRF-Token": csrf},
            json={"product_id": new_product["id"]},
        )
        assert applied_response.status_code == 201
        applied = applied_response.json()["data"]
        applied_text = json.dumps(applied["plan"], ensure_ascii=False)
        assert applied["state"] == "awaiting_prompt_confirmation"
        assert new_product["name"] in applied_text
        assert old_product["name"] not in applied_text

        copy_response = client.post(
            f"/api/v1/templates/{template['id']}/copy",
            headers={"Idempotency-Key": "copy-template-one", "X-CSRF-Token": csrf},
        )
        assert copy_response.status_code == 201
        assert copy_response.json()["data"]["name"].endswith("副本")


def test_history_timeline_and_zip_download(tmp_path):
    with build_client(tmp_path) as client:
        csrf = login(client)
        product, plan = prepare_confirmed_prompt(client, csrf, suffix="history")
        batch = generate_five(client, csrf, plan, "generate-history")
        image_ids = [item["image"]["id"] for item in batch["items"][:3]]

        history = client.get(
            "/api/v1/history",
            params={
                "product_id": product["id"],
                "generation_type": "main",
                "state": "completed",
            },
        )
        assert history.status_code == 200
        assert [item["id"] for item in history.json()["data"]["items"]] == [batch["id"]]

        detail = client.get(f"/api/v1/history/{batch['id']}")
        assert detail.status_code == 200
        assert detail.json()["data"]["timeline"]
        assert detail.json()["data"]["timeline"][-1]["state"] == "completed"

        download = client.post(
            "/api/v1/downloads",
            headers={"Idempotency-Key": "download-three", "X-CSRF-Token": csrf},
            json={"image_ids": image_ids},
        )
        assert download.status_code == 201
        bundle = download.json()["data"]
        assert bundle["status"] == "ready"
        archive = client.get(bundle["download_url"])
        assert archive.status_code == 200
        assert archive.content.startswith(b"PK")
        assert "attachment" in archive.headers["content-disposition"]
