import dramatiq
from dramatiq.brokers.redis import RedisBroker

from app import models
from app.config import get_settings
from app.db import build_session_factory
from app.media import build_media_store
from app.providers import build_ai_provider
from app.services.generation import process_item, refresh_batch_state
from app.services.workflow_lock import workflow_lock
from app.services.generation_events import add_event

settings = get_settings()
broker = RedisBroker(url=settings.redis_url)
# API exposes its own metrics; omit Dramatiq's auxiliary global HTTP listener
# so isolated test/demo workers can coexist without sharing a port.
broker.middleware = [m for m in broker.middleware if m.__class__.__name__ != "Prometheus"]
dramatiq.set_broker(broker)


@dramatiq.actor(queue_name="image-generation", max_retries=2, min_backoff=10_000)
def generate_image_item(item_id: str, request_id: str) -> None:
    session_factory = build_session_factory(settings.database_url)
    with session_factory() as db:
        item = db.get(models.GenerationItem, item_id)
        if not item or item.state != "queued":
            return
        owned_result = process_item(
            db,
            item=item,
            provider=build_ai_provider(settings),
            media_store=build_media_store(settings),
            settings=settings,
            request_id=request_id,
        )
        if not owned_result:
            return
        workflow_lock(db)
        db.refresh(item)
        batch = db.get(models.GenerationBatch, item.batch_id)
        if item.state == "failed" and item.retryable and item.attempts < 3:
            item.state = "queued"
            add_event(db, item.batch_id, "item_auto_retry_scheduled", "queued",
                      {"item_id": item.id, "attempt": item.attempts})
            db.commit()
            if batch:
                refresh_batch_state(db, batch)
            raise dramatiq.Retry(delay=10_000 * item.attempts)
        if batch:
            refresh_batch_state(db, batch)
