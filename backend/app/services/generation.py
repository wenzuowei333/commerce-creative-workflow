"""Compatibility facade for image-generation services.

Callers keep importing from this module while the implementation is divided by
responsibility. New code should import the focused service module directly.
"""

from app.services.generation_batches import (
    TERMINAL_BATCH_STATES,
    TERMINAL_ITEM_STATES,
    create_batch,
    prepare_failed_items,
    process_batch_inline,
    refresh_batch_state,
    retry_failed_inline,
)
from app.services.generation_events import add_event
from app.services.generation_execution import (
    LeaseHeartbeat,
    generation_parameters,
    process_item,
    reference_images,
    validate_generated_image,
)
from app.services.generation_limits import ensure_daily_capacity, image_attempts_today
from app.services.generation_payloads import batch_payload, image_payload
from app.services.generation_recovery import queued_item_ids, recover_stale_items
from app.services.generation_revisions import create_derivative

_reference_images = reference_images
_generation_parameters = generation_parameters
_validate_generated_image = validate_generated_image

__all__ = [
    "TERMINAL_BATCH_STATES",
    "TERMINAL_ITEM_STATES",
    "LeaseHeartbeat",
    "_generation_parameters",
    "_reference_images",
    "_validate_generated_image",
    "add_event",
    "batch_payload",
    "create_batch",
    "create_derivative",
    "ensure_daily_capacity",
    "image_attempts_today",
    "image_payload",
    "prepare_failed_items",
    "process_batch_inline",
    "process_item",
    "queued_item_ids",
    "recover_stale_items",
    "refresh_batch_state",
    "retry_failed_inline",
]
