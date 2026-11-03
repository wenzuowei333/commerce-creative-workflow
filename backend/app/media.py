from pathlib import Path
from typing import Protocol

from qcloud_cos import CosConfig, CosS3Client

from app.config import Settings


class MediaStore(Protocol):
    def upload_url(
        self, *, asset_id: str, object_key: str, upload_token: str
    ) -> tuple[str, dict[str, str]]: ...

    def put_bytes(self, object_key: str, content: bytes, content_type: str) -> None: ...

    def read_bytes(self, object_key: str) -> bytes: ...

    def exists(self, object_key: str) -> bool: ...

    def download_url(self, object_key: str, expires_seconds: int = 600) -> str: ...

    def delete(self, object_key: str) -> None: ...


class LocalMediaStore:
    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, object_key: str) -> Path:
        path = (self.root / object_key).resolve()
        if self.root not in path.parents:
            raise ValueError("invalid object key")
        return path

    def upload_url(
        self, *, asset_id: str, object_key: str, upload_token: str
    ) -> tuple[str, dict[str, str]]:
        return f"/api/v1/assets/{asset_id}/content", {"X-Upload-Token": upload_token}

    def put_bytes(self, object_key: str, content: bytes, content_type: str) -> None:
        path = self._path(object_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def read_bytes(self, object_key: str) -> bytes:
        return self._path(object_key).read_bytes()

    def exists(self, object_key: str) -> bool:
        return self._path(object_key).is_file()

    def download_url(self, object_key: str, expires_seconds: int = 600) -> str:
        return f"/api/v1/media/{object_key}"

    def delete(self, object_key: str) -> None:
        path = self._path(object_key)
        if path.exists():
            path.unlink()


class CosMediaStore:
    def __init__(self, settings: Settings) -> None:
        config = CosConfig(
            Region=settings.cos_region,
            SecretId=settings.cos_secret_id,
            SecretKey=settings.cos_secret_key,
            Scheme=settings.cos_scheme,
        )
        self.client = CosS3Client(config)
        self.bucket = settings.cos_bucket

    def upload_url(
        self, *, asset_id: str, object_key: str, upload_token: str
    ) -> tuple[str, dict[str, str]]:
        url = self.client.get_presigned_url(
            Method="PUT",
            Bucket=self.bucket,
            Key=object_key,
            Expired=900,
        )
        return url, {}

    def put_bytes(self, object_key: str, content: bytes, content_type: str) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Body=content,
            Key=object_key,
            ContentType=content_type,
        )

    def read_bytes(self, object_key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=object_key)
        return response["Body"].get_raw_stream().read()

    def exists(self, object_key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=object_key)
            return True
        except Exception:
            return False

    def download_url(self, object_key: str, expires_seconds: int = 600) -> str:
        return self.client.get_presigned_url(
            Method="GET",
            Bucket=self.bucket,
            Key=object_key,
            Expired=expires_seconds,
        )

    def delete(self, object_key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=object_key)


def build_media_store(settings: Settings) -> MediaStore:
    if settings.media_backend == "cos":
        return CosMediaStore(settings)
    return LocalMediaStore(settings.media_root)
