from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class MediaDownloader(Protocol):
    def download(
        self,
        *,
        download_code: str,
        max_bytes: int,
        connector_id: str = "",
        robot_code: str = "",
    ) -> bytes: ...


@dataclass(frozen=True)
class AttachmentImportReceipt:
    attachment_id: str
    size_bytes: int
    sha256: str
    file_id: str = ""
    version_id: str = ""
    readability_status: str = "NOT_REQUIRED"
    processing_run_id: str = ""


class AttachmentImporter(Protocol):
    def import_content(
        self,
        *,
        attachment_id: str,
        data: bytes,
        content_type: str,
    ) -> AttachmentImportReceipt: ...


class ConversationCache(Protocol):
    def get(self, session_id: str) -> None: ...


class NoConversationCache:
    def get(self, session_id: str) -> None:
        del session_id
        return None
