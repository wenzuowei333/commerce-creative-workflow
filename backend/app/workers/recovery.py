"""Local queue reconciler: recover expired leases and redispatch committed queues.

Redis delivery is at least once; database CAS claims make duplicates harmless.
Only this candidate's database and broker are accepted in demo configuration.
"""
import signal
from threading import Event

from app.config import get_settings
from app.db import build_session_factory
from app.queueing import dispatch_generation_items
from app.services.generation_recovery import recover_stale_items, queued_item_ids
from app.services.generation_batches import refresh_batch_state
from app import models


def main():
    settings = get_settings()
    if settings.environment != "demo" or settings.queue_mode != "dramatiq":
        raise SystemExit("Recovery daemon is scoped to the local Dramatiq demo")
    factory = build_session_factory(settings.database_url)
    stopped = Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopped.set())
    while not stopped.is_set():
        with factory() as db:
            recovered = recover_stale_items(db)
            for item_id in recovered:
                item = db.get(models.GenerationItem, item_id)
                batch = db.get(models.GenerationBatch, item.batch_id)
                refresh_batch_state(db, batch)
            ids = queued_item_ids(db)
            db.commit()
        dispatch_generation_items(settings, ids, "queue-reconciliation")
        stopped.wait(settings.recovery_interval_seconds)


if __name__ == "__main__":
    main()
