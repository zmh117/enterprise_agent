from __future__ import annotations

import hashlib

from app.modules.attachments.domain import StoredObject
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
                "Object checksum mismatch", safe_message="附件校验和不匹配"
            )
        existing = self.objects.get(key)
        if existing is not None and hashlib.sha256(existing).hexdigest() != sha256:
            raise NonRetryableExecutionError("Object key collision", safe_message="附件对象冲突")
        self.objects[key] = data
        return StoredObject(self.bucket, key, len(data), sha256)

    def get(self, *, key: str) -> bytes:
        if key not in self.objects:
            raise NonRetryableExecutionError("Object not found", safe_message="未找到附件对象")
        return self.objects[key]

    def delete(self, *, key: str) -> None:
        self.objects.pop(key, None)

    def list_keys(self) -> list[str]:
        return sorted(self.objects)
