from app.config import Settings


def dispatch_generation_items(
    settings: Settings,
    item_ids: list[str],
    request_id: str,
) -> None:
    if settings.queue_mode != "dramatiq" or not item_ids:
        return
    from app.workers.tasks import generate_image_item

    for item_id in item_ids:
        generate_image_item.send(item_id, request_id)
