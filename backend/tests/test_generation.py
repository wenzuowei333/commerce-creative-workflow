from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app import models
from app.core.errors import AppError
from app.providers import MockAIProvider
from app.services.generation import recover_stale_items
from tests.support import build_client, login, prepare_confirmed_prompt


class CountingProvider(MockAIProvider):
    def __init__(self, fail_calls: set[int] | None = None) -> None:
        self.calls = 0
        self.fail_calls = fail_calls or set()

    def generate_image(self, **kwargs) -> bytes:
        self.calls += 1
        if self.calls in self.fail_calls:
            raise AppError(
                code="provider_temporary_failure",
                message="模型服务暂时不可用",
                retryable=True,
                status_code=503,
            )
        return super().generate_image(**kwargs)


def test_generation_batch_is_split_into_independent_items_and_is_idempotent(tmp_path):
    with build_client(tmp_path) as client:
        csrf = login(client)
        _, plan = prepare_confirmed_prompt(client, csrf)
        provider = CountingProvider()
        client.app.state.ai_provider = provider

        response = client.post(
            "/api/v1/generation-batches",
            headers={"Idempotency-Key": "generate-five-once", "X-CSRF-Token": csrf},
            json={"prompt_plan_id": plan["id"]},
        )
        duplicate = client.post(
            "/api/v1/generation-batches",
            headers={"Idempotency-Key": "generate-five-once", "X-CSRF-Token": csrf},
            json={"prompt_plan_id": plan["id"]},
        )

        assert response.status_code == 201
        batch = response.json()["data"]
        assert batch["state"] == "completed"
        assert batch["progress"] == 100
        assert len(batch["directions"]) == 1
        assert len(batch["items"]) == 5
        assert all(item["state"] == "completed" for item in batch["items"])
        assert all(item["image"] for item in batch["items"])
        assert duplicate.status_code == 201
        assert duplicate.json()["data"]["id"] == batch["id"]
        assert provider.calls == 5

        events = client.get(f"/api/v1/generation-batches/{batch['id']}/events")
        assert events.status_code == 200
        assert "event: batch_progress" in events.text
        assert '"progress": 100' in events.text


def test_partial_batch_retries_only_failed_items_and_reaches_100_percent(tmp_path):
    with build_client(tmp_path) as client:
        csrf = login(client)
        _, plan = prepare_confirmed_prompt(client, csrf, suffix="partial")
        provider = CountingProvider({2, 4})
        client.app.state.ai_provider = provider

        response = client.post(
            "/api/v1/generation-batches",
            headers={"Idempotency-Key": "generate-partial", "X-CSRF-Token": csrf},
            json={"prompt_plan_id": plan["id"]},
        )
        batch = response.json()["data"]
        assert batch["state"] == "partial"
        assert batch["progress"] == 100
        assert sum(item["state"] == "failed" for item in batch["items"]) == 2

        retry = client.post(
            f"/api/v1/generation-batches/{batch['id']}/retry-failed",
            headers={"Idempotency-Key": "retry-partial", "X-CSRF-Token": csrf},
        )
        retried = retry.json()["data"]
        assert retry.status_code == 200
        assert retried["state"] == "completed"
        assert retried["progress"] == 100
        assert all(item["state"] == "completed" for item in retried["items"])
        assert provider.calls == 7

        usage = client.get("/api/v1/usage/daily")
        assert usage.status_code == 200
        assert usage.json()["data"]["image_attempts"] == 7


def test_daily_limit_blocks_batch_before_any_provider_call(tmp_path):
    with build_client(tmp_path, image_daily_limit=4) as client:
        csrf = login(client)
        _, plan = prepare_confirmed_prompt(client, csrf, suffix="quota")
        provider = CountingProvider()
        client.app.state.ai_provider = provider

        response = client.post(
            "/api/v1/generation-batches",
            headers={"Idempotency-Key": "generate-over-quota", "X-CSRF-Token": csrf},
            json={"prompt_plan_id": plan["id"]},
        )

        assert response.status_code == 429
        assert response.json()["error"]["code"] == "daily_image_limit_exceeded"
        assert provider.calls == 0


def test_expired_worker_lease_is_recovered_after_restart(tmp_path):
    with build_client(tmp_path, queue_mode="deferred") as client:
        csrf = login(client)
        _, plan = prepare_confirmed_prompt(client, csrf, suffix="lease")
        response = client.post(
            "/api/v1/generation-batches",
            headers={"Idempotency-Key": "generate-deferred", "X-CSRF-Token": csrf},
            json={"prompt_plan_id": plan["id"]},
        )
        batch = response.json()["data"]
        item_id = batch["items"][0]["id"]

        with client.app.state.session_factory() as db:
            item = db.get(models.GenerationItem, item_id)
            item.state = "generating"
            item.lease_token = "expired-lease"
            item.lease_expires_at = datetime.now(UTC) - timedelta(minutes=1)
            db.commit()
            recovered = recover_stale_items(db)
            db.refresh(item)
            event = db.scalar(
                select(models.TaskEvent).where(
                    models.TaskEvent.aggregate_id == batch["id"],
                    models.TaskEvent.event_type == "item_recovered",
                )
            )

        assert recovered == [item_id]
        assert item.state == "queued"
        assert item.lease_token is None
        assert event is not None


def test_deferred_queue_retry_requeues_only_failed_items(tmp_path, monkeypatch):
    dispatched: list[str] = []

    def capture_dispatch(_settings, item_ids, _request_id):
        dispatched.extend(item_ids)

    monkeypatch.setattr("app.api.generation.dispatch_generation_items", capture_dispatch)
    with build_client(tmp_path, queue_mode="deferred") as client:
        csrf = login(client)
        _, plan = prepare_confirmed_prompt(client, csrf, suffix="deferred-retry")
        created = client.post(
            "/api/v1/generation-batches",
            headers={"Idempotency-Key": "deferred-create", "X-CSRF-Token": csrf},
            json={"prompt_plan_id": plan["id"]},
        ).json()["data"]
        failed_ids = [created["items"][1]["id"], created["items"][3]["id"]]
        with client.app.state.session_factory() as db:
            for item_id in failed_ids:
                item = db.get(models.GenerationItem, item_id)
                item.state = "failed"
                item.retryable = True
            batch = db.get(models.GenerationBatch, created["id"])
            batch.state = "partial"
            batch.progress = 100
            db.commit()

        dispatched.clear()
        response = client.post(
            f"/api/v1/generation-batches/{created['id']}/retry-failed",
            headers={"Idempotency-Key": "deferred-retry", "X-CSRF-Token": csrf},
        )

        assert response.status_code == 200
        assert set(dispatched) == set(failed_ids)
        items = {item["id"]: item for item in response.json()["data"]["items"]}
        assert all(items[item_id]["state"] == "queued" for item_id in failed_ids)
