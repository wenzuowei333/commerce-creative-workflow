"""Owned child-process fault fixture; only test PostgreSQL port 25437 is allowed."""
import argparse
import json
import time
from urllib.parse import urlparse

from app.config import Settings
from app.db import build_session_factory
from app import models
from app.providers import MockAIProvider
from app.core.errors import AppError
from app.media import build_media_store
from app.services.generation_execution import process_item
from app.services.generation_batches import refresh_batch_state


class FaultProvider(MockAIProvider):
    def __init__(self, wait_seconds, raise_after):
        self.wait_seconds = wait_seconds
        self.raise_after = raise_after

    def generate_image(self, **kwargs):
        content = super().generate_image(**kwargs)
        print(json.dumps({"event": "provider_result_ready"}), flush=True)
        time.sleep(self.wait_seconds)
        if self.raise_after:
            raise AppError(code="test_late_failure", message="Local fault injection", retryable=True, status_code=503)
        return content


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--item", required=True)
    parser.add_argument("--wait-after-provider", type=float, default=0)
    parser.add_argument("--raise-after", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    if urlparse(settings.database_url).port != 25437 or not 0 <= args.wait_after_provider <= 30:
        raise SystemExit("Fault worker only accepts the dedicated local test DB and bounded delay")
    with build_session_factory(settings.database_url)() as db:
        item = db.get(models.GenerationItem, args.item)
        owned = process_item(db, item=item, provider=FaultProvider(args.wait_after_provider, args.raise_after),
            media_store=build_media_store(settings), settings=settings, request_id="fault-worker")
        if owned:
            refresh_batch_state(db, db.get(models.GenerationBatch, item.batch_id))
        print(json.dumps({"event": "finished", "owned_write": owned}), flush=True)


if __name__ == "__main__":
    main()
