from __future__ import annotations

import hashlib
from typing import Any

from app.modules.attachments.domain import StoredObject
from app.shared.config import ObjectStorageSettings
from app.shared.exceptions import NonRetryableExecutionError


class InMemoryObjectStorage:
    def __init__(self, bucket: str = "agent-attachments") -> None:
        self.bucket = bucket
        self.objects: dict[str, bytes] = {}

    def put(self, *, key: str, data: bytes, content_type: str, sha256: str) -> StoredObject:
        del content_type
        actual = hashlib.sha256(data).hexdigest()
        if actual != sha256:
            raise NonRetryableExecutionError(
                "Object checksum mismatch", safe_message="Attachment checksum mismatch"
            )
        existing = self.objects.get(key)
        if existing is not None and hashlib.sha256(existing).hexdigest() != sha256:
            raise NonRetryableExecutionError(
                "Object key collision", safe_message="Attachment object conflict"
            )
        self.objects[key] = data
        return StoredObject(self.bucket, key, len(data), sha256)

    def get(self, *, key: str) -> bytes:
        if key not in self.objects:
            raise NonRetryableExecutionError(
                "Object not found", safe_message="Attachment object not found"
            )
        return self.objects[key]

    def delete(self, *, key: str) -> None:
        self.objects.pop(key, None)

    def list_keys(self) -> list[str]:
        return sorted(self.objects)


class S3ObjectStorage:
    def __init__(self, settings: ObjectStorageSettings, client: Any | None = None) -> None:
        if client is None:
            try:
                import boto3
            except ModuleNotFoundError as exc:
                raise RuntimeError("boto3 is required for S3 object storage") from exc
            client = boto3.client(
                "s3",
                endpoint_url=settings.endpoint_url,
                aws_access_key_id=settings.access_key,
                aws_secret_access_key=settings.secret_key,
                region_name=settings.region,
                use_ssl=settings.secure,
            )
        self.client = client
        self.bucket = settings.bucket

    def ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except Exception:
            self.client.create_bucket(Bucket=self.bucket)

    def put(self, *, key: str, data: bytes, content_type: str, sha256: str) -> StoredObject:
        try:
            head = self.client.head_object(Bucket=self.bucket, Key=key)
        except Exception:
            head = None
        if head:
            metadata = head.get("Metadata") or {}
            if metadata.get("sha256") != sha256:
                raise NonRetryableExecutionError(
                    "Object key collision", safe_message="Attachment object conflict"
                )
            return StoredObject(self.bucket, key, int(head.get("ContentLength") or 0), sha256)
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            Metadata={"sha256": sha256},
        )
        return StoredObject(self.bucket, key, len(data), sha256)

    def get(self, *, key: str) -> bytes:
        body = self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
        return bytes(body.read())

    def delete(self, *, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def list_keys(self) -> list[str]:
        response = self.client.list_objects_v2(Bucket=self.bucket)
        return sorted(str(item["Key"]) for item in response.get("Contents") or [])
