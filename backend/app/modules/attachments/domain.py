from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class StoredObject:
    bucket: str
    key: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class ExtractedContent:
    text: str
    segments: list[dict[str, object]]
    parser_version: str
    truncated: bool


class ObjectStorage(Protocol):
    def put(self, *, key: str, data: bytes, content_type: str, sha256: str) -> StoredObject: ...
    def get(self, *, key: str) -> bytes: ...
    def delete(self, *, key: str) -> None: ...
    def list_keys(self) -> list[str]: ...


class MediaDownloader(Protocol):
    def download(self, *, download_code: str, max_bytes: int) -> bytes: ...


class AttachmentExtractor(Protocol):
    def inspect(self, *, file_name: str, data: bytes) -> str: ...
    def extract(self, *, file_name: str, data: bytes) -> ExtractedContent: ...


class ConversationCache(Protocol):
    def get(self, session_id: str) -> None: ...


class NoConversationCache:
    def get(self, session_id: str) -> None:
        del session_id
        return None
