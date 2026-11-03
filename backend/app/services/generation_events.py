from typing import Any

from sqlalchemy.orm import Session

from app import models


def add_event(
    db: Session,
    batch_id: str,
    event_type: str,
    state: str,
    payload: dict[str, Any],
) -> None:
    db.add(
        models.TaskEvent(
            aggregate_type="generation_batch",
            aggregate_id=batch_id,
            event_type=event_type,
            state=state,
            payload_json=payload,
        )
    )
