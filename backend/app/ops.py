import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app import models
from app.config import get_settings
from app.db import build_session_factory
from app.media import build_media_store
from app.queueing import dispatch_generation_items
from app.services.generation import recover_stale_items


def cleanup() -> dict[str, int]:
    settings = get_settings()
    session_factory = build_session_factory(settings.database_url)
    media_store = build_media_store(settings)
    now = datetime.now(UTC)
    counts = {
        "pending_uploads": 0,
        "expired_downloads": 0,
        "purged_assets": 0,
        "idempotency_records": 0,
    }
    with session_factory() as db:
        pending_assets = db.scalars(
            select(models.ProductAsset).where(
                models.ProductAsset.status == "pending",
                models.ProductAsset.created_at < now - timedelta(hours=24),
            )
        ).all()
        for asset in pending_assets:
            if media_store.exists(asset.object_key):
                media_store.delete(asset.object_key)
            db.delete(asset)
            counts["pending_uploads"] += 1

        expired_downloads = db.scalars(
            select(models.DownloadBundle).where(
                models.DownloadBundle.expires_at.is_not(None),
                models.DownloadBundle.expires_at < now,
                models.DownloadBundle.status == "ready",
            )
        ).all()
        for bundle in expired_downloads:
            if bundle.object_key and media_store.exists(bundle.object_key):
                media_store.delete(bundle.object_key)
            bundle.status = "expired"
            counts["expired_downloads"] += 1

        deleted_entries = db.scalars(
            select(models.DeletedObject).where(
                models.DeletedObject.restored_at.is_(None),
                models.DeletedObject.purge_after < now,
            )
        ).all()
        for entry in deleted_entries:
            if entry.object_type == "product_asset":
                asset = db.get(models.ProductAsset, entry.object_id)
                if asset:
                    for object_key in (asset.object_key, asset.thumbnail_object_key):
                        if object_key and media_store.exists(object_key):
                            media_store.delete(object_key)
                    db.delete(asset)
            db.delete(entry)
            counts["purged_assets"] += 1

        expired_idempotency = db.scalars(
            select(models.IdempotencyRecord).where(models.IdempotencyRecord.expires_at < now)
        ).all()
        for record in expired_idempotency:
            db.delete(record)
            counts["idempotency_records"] += 1
        db.commit()
    return counts


def upload_backup(path: str) -> dict[str, str]:
    settings = get_settings()
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(path)
    if settings.media_backend != "cos":
        return {"status": "retained_locally", "path": str(source)}
    media_store = build_media_store(settings)
    object_key = f"{settings.backup_cos_prefix.strip('/')}/{source.name}"
    media_store.put_bytes(object_key, source.read_bytes(), "application/gzip")
    return {"status": "uploaded", "object_key": object_key}


def recover_stale() -> dict[str, int]:
    settings = get_settings()
    session_factory = build_session_factory(settings.database_url)
    with session_factory() as db:
        item_ids = recover_stale_items(db)
    dispatch_generation_items(settings, item_ids, "maintenance-recovery")
    return {"requeued": len(item_ids)}


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.ops")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("cleanup")
    subparsers.add_parser("recover-stale")
    upload_parser = subparsers.add_parser("upload-backup")
    upload_parser.add_argument("path")
    args = parser.parse_args()
    if args.command == "cleanup":
        result = cleanup()
    elif args.command == "recover-stale":
        result = recover_stale()
    else:
        result = upload_backup(args.path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
