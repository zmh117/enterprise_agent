from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any, BinaryIO, Protocol, cast
from urllib.parse import urlsplit

from app.shared.database import assert_external_io_allowed
from app.shared.exceptions import NonRetryableExecutionError


class SecretResolver(Protocol):
    def __call__(self, ref: str) -> str: ...


@dataclass(frozen=True, slots=True)
class FileObjectStorageSettings:
    endpoint_url: str
    bucket: str
    access_key_ref: str
    secret_key_ref: str
    region: str = "us-east-1"
    secure: bool = False

    def __post_init__(self) -> None:
        parsed = urlsplit(self.endpoint_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("File object storage endpoint is invalid")
        if not self.bucket or len(self.bucket) > 63:
            raise ValueError("File object storage bucket is invalid")
        for ref in (self.access_key_ref, self.secret_key_ref):
            if not ref.startswith("secret://platform/") or ref.count("/") != 3:
                raise ValueError("File object storage requires platform Secret References")

    def safe_projection(self) -> dict[str, object]:
        parsed = urlsplit(self.endpoint_url)
        return {
            "configured": True,
            "endpoint": f"{parsed.scheme}://{parsed.hostname}",
            "bucket": "configured",
            "credentials": "configured",
            "secure": self.secure,
        }


@dataclass(frozen=True, slots=True)
class InternalStoredObject:
    object_key: str
    size_bytes: int
    content_sha256: str

    def __repr__(self) -> str:
        return (
            "InternalStoredObject(object_key=<hidden>, "
            f"size_bytes={self.size_bytes}, content_sha256={self.content_sha256!r})"
        )


class MinioFileObjectStorage:
    """The only adapter allowed to turn platform Secret References into MinIO I/O."""

    def __init__(
        self,
        settings: FileObjectStorageSettings,
        resolve_secret: SecretResolver,
        *,
        client: Any | None = None,
    ) -> None:
        self.settings = settings
        access_key = resolve_secret(settings.access_key_ref)
        secret_key = resolve_secret(settings.secret_key_ref)
        if not access_key or not secret_key:
            raise NonRetryableExecutionError(
                "File object storage credential is unavailable",
                safe_message="文件存储凭据不可用",
                error_code="file_storage_credential_unavailable",
            )
        if client is None:
            try:
                import boto3
            except ModuleNotFoundError as exc:
                raise RuntimeError("boto3 is required for File Service storage") from exc
            client = boto3.client(
                "s3",
                endpoint_url=settings.endpoint_url,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=settings.region,
                use_ssl=settings.secure,
            )
        self._client = client
        self._bucket = settings.bucket

    @staticmethod
    def new_object_key(*, kind: str) -> str:
        if kind not in {"version", "staging", "attachment"}:
            raise ValueError("Unsupported managed object kind")
        return f"managed/{kind}/{secrets.token_hex(24)}"

    def put_stream(
        self,
        stream: BinaryIO,
        *,
        kind: str,
        content_type: str,
        content_sha256: str,
        size_bytes: int,
        internal_object_key: str | None = None,
    ) -> InternalStoredObject:
        if len(content_sha256) != 64 or size_bytes < 0:
            raise ValueError("Managed object metadata is invalid")
        key = internal_object_key or self.new_object_key(kind=kind)
        if not key.startswith(f"managed/{kind}/") or len(key) > 1024:
            raise ValueError("Managed object key is outside its fixed namespace")
        assert_external_io_allowed("file_storage.put_stream")
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=stream,
            ContentLength=size_bytes,
            ContentType=content_type,
            Metadata={"sha256": content_sha256},
        )
        return InternalStoredObject(key, size_bytes, content_sha256)

    def open_stream(self, *, internal_object_key: str) -> BinaryIO:
        assert_external_io_allowed("file_storage.open_stream")
        return cast(
            BinaryIO,
            self._client.get_object(
                Bucket=self._bucket,
                Key=internal_object_key,
            )["Body"],
        )

    def delete(self, *, internal_object_key: str) -> None:
        assert_external_io_allowed("file_storage.delete")
        self._client.delete_object(Bucket=self._bucket, Key=internal_object_key)

    def exists(self, *, internal_object_key: str) -> bool:
        assert_external_io_allowed("file_storage.exists")
        try:
            self._client.head_object(Bucket=self._bucket, Key=internal_object_key)
            return True
        except Exception:
            return False

    def list_keys(self) -> list[str]:
        assert_external_io_allowed("file_storage.list_keys")
        keys: list[str] = []
        continuation: str | None = None
        while True:
            arguments: dict[str, Any] = {"Bucket": self._bucket, "Prefix": "managed/"}
            if continuation:
                arguments["ContinuationToken"] = continuation
            response = self._client.list_objects_v2(**arguments)
            keys.extend(str(item["Key"]) for item in response.get("Contents") or [])
            if not response.get("IsTruncated"):
                return sorted(keys)
            continuation = str(response.get("NextContinuationToken") or "")
            if not continuation:
                return sorted(keys)

    def assert_ready(self) -> None:
        assert_external_io_allowed("file_storage.assert_ready")
        self._client.head_bucket(Bucket=self._bucket)
