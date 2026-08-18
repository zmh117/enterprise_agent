from __future__ import annotations

import json
import stat
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, BinaryIO, Protocol
from urllib.parse import quote, urlsplit

import httpx

from app.modules.document_processing.profile import (
    DOCLING_TEXT_V1,
    DocumentProcessingProfile,
)


class ProcessorTaskState(StrEnum):
    PENDING = "pending"
    STARTED = "started"
    SUCCESS = "success"
    FAILURE = "failure"


class DocumentProcessorFailure(Exception):
    def __init__(self, error_code: str, *, retryable: bool) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class ProcessorTask:
    task_id: str
    state: ProcessorTaskState


@dataclass(frozen=True, slots=True)
class DocumentProcessorResult:
    markdown: bytes
    docling_json: bytes
    partial: bool
    no_text: bool
    page_count: int | None
    processing_time_ms: int | None


class DocumentProcessor(Protocol):
    def submit(
        self,
        *,
        stream: BinaryIO,
        filename: str,
        media_type: str,
        format_code: str,
        profile: DocumentProcessingProfile,
    ) -> ProcessorTask: ...

    def poll(self, task_id: str) -> ProcessorTask: ...

    def fetch(
        self, task_id: str, *, profile: DocumentProcessingProfile
    ) -> DocumentProcessorResult: ...


class DoclingServeProvider:
    """Bounded client for Docling Serve v1 async multipart conversion only."""

    _task_keys = frozenset(
        {
            "task_id",
            "task_type",
            "task_status",
            "task_position",
            "task_meta",
            "error_message",
            "failure",
        }
    )
    _result_keys = frozenset(
        {"document", "status", "processing_time", "timings", "errors", "confidence"}
    )
    _document_keys = frozenset(
        {
            "filename",
            "md_content",
            "json_content",
            "yaml_content",
            "html_content",
            "html_split_page_content",
            "text_content",
            "doctags_content",
            "vtt_content",
            "doclang_content",
            "dclx_content",
            "chunks_content",
        }
    )

    def __init__(
        self,
        *,
        base_url: str,
        allowed_hosts: tuple[str, ...],
        api_key: str,
        connect_timeout_seconds: int,
        max_response_bytes: int,
        client: httpx.Client | None = None,
    ) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.hostname not in allowed_hosts
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("Docling Serve internal endpoint is invalid")
        if not api_key or len(api_key.encode("ascii")) > 4096:
            raise ValueError("Docling Serve API key is invalid")
        if not 1 <= connect_timeout_seconds <= 60:
            raise ValueError("Docling Serve connect timeout is invalid")
        if not 1024 <= max_response_bytes <= 128 * 1024 * 1024:
            raise ValueError("Docling Serve response size bound is invalid")
        self.base_url = base_url.rstrip("/")
        self.max_response_bytes = max_response_bytes
        self.client = client or httpx.Client(
            headers={"Accept": "application/json", "X-Api-Key": api_key},
            timeout=httpx.Timeout(
                connect=float(connect_timeout_seconds),
                read=float(connect_timeout_seconds),
                write=float(connect_timeout_seconds),
                pool=float(connect_timeout_seconds),
            ),
            follow_redirects=False,
        )

    def submit(
        self,
        *,
        stream: BinaryIO,
        filename: str,
        media_type: str,
        format_code: str,
        profile: DocumentProcessingProfile,
    ) -> ProcessorTask:
        if profile.profile_hash != DOCLING_TEXT_V1.profile_hash:
            raise DocumentProcessorFailure("document_profile_mismatch", retryable=False)
        definition = profile.source_by_code(format_code)
        if media_type.split(";", 1)[0].strip().lower() not in definition.accepted_media_types:
            raise DocumentProcessorFailure("document_source_media_type_mismatch", retryable=False)
        fields: dict[str, str | list[str]] = {}
        for key, value in profile.request_options.items():
            values = value if isinstance(value, list) else [value]
            encoded_values: list[str] = []
            for item in values:
                if isinstance(item, bool):
                    encoded = "true" if item else "false"
                else:
                    encoded = str(item)
                encoded_values.append(encoded)
            fields[key] = encoded_values if isinstance(value, list) else encoded_values[0]
        fields["target_type"] = "inbody"
        response = self._request(
            "POST",
            "/v1/convert/file/async",
            data=fields,
            files={"files": (filename, stream, definition.canonical_media_type)},
        )
        return self._task(response, expected_task_id=None)

    def poll(self, task_id: str) -> ProcessorTask:
        _require_task_id(task_id)
        response = self._request("GET", f"/v1/status/poll/{quote(task_id, safe='')}")
        return self._task(response, expected_task_id=task_id)

    def fetch(self, task_id: str, *, profile: DocumentProcessingProfile) -> DocumentProcessorResult:
        _require_task_id(task_id)
        value = self._request("GET", f"/v1/result/{quote(task_id, safe='')}")
        if not isinstance(value, dict) or not set(value).issubset(self._result_keys):
            raise DocumentProcessorFailure("docling_response_schema_invalid", retryable=True)
        if not {"document", "status", "processing_time", "timings", "errors"}.issubset(value):
            raise DocumentProcessorFailure("docling_response_schema_invalid", retryable=True)
        status = str(value["status"])
        if status not in {"success", "partial_success", "failure"}:
            raise DocumentProcessorFailure("docling_response_schema_invalid", retryable=True)
        if status == "failure":
            raise DocumentProcessorFailure("docling_conversion_failed", retryable=False)
        errors = value["errors"]
        if not isinstance(errors, list) or len(errors) > 100:
            raise DocumentProcessorFailure("docling_response_schema_invalid", retryable=True)
        document = value["document"]
        if not isinstance(document, dict) or not set(document).issubset(self._document_keys):
            raise DocumentProcessorFailure("docling_response_schema_invalid", retryable=True)
        markdown_value = document.get("md_content")
        json_value = document.get("json_content")
        if markdown_value is not None and not isinstance(markdown_value, str):
            raise DocumentProcessorFailure("docling_response_schema_invalid", retryable=True)
        if not isinstance(json_value, dict):
            raise DocumentProcessorFailure("docling_response_schema_invalid", retryable=True)
        if json_value.get("schema_name") != "DoclingDocument":
            raise DocumentProcessorFailure("docling_json_schema_invalid", retryable=True)
        markdown = (markdown_value or "").encode("utf-8")
        docling_json = json.dumps(
            json_value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(markdown) > profile.max_markdown_bytes:
            raise DocumentProcessorFailure("docling_markdown_size_exceeded", retryable=False)
        if len(docling_json) > profile.max_docling_json_bytes:
            raise DocumentProcessorFailure("docling_json_size_exceeded", retryable=False)
        processing_time = value["processing_time"]
        if not isinstance(processing_time, (int, float)) or isinstance(processing_time, bool):
            raise DocumentProcessorFailure("docling_response_schema_invalid", retryable=True)
        pages = json_value.get("pages")
        page_count = len(pages) if isinstance(pages, (dict, list)) else None
        if page_count is not None and page_count > profile.max_pdf_pages:
            raise DocumentProcessorFailure("document_page_limit_exceeded", retryable=False)
        no_text = not markdown.strip()
        return DocumentProcessorResult(
            markdown=markdown,
            docling_json=docling_json,
            partial=status == "partial_success" or bool(errors),
            no_text=no_text,
            page_count=page_count,
            processing_time_ms=max(0, int(float(processing_time) * 1000)),
        )

    def _task(self, value: Any, *, expected_task_id: str | None) -> ProcessorTask:
        if (
            not isinstance(value, dict)
            or not set(value).issubset(self._task_keys)
            or not {"task_id", "task_status"}.issubset(value)
        ):
            raise DocumentProcessorFailure("docling_response_schema_invalid", retryable=True)
        task_id = str(value["task_id"])
        _require_task_id(task_id)
        if expected_task_id is not None and task_id != expected_task_id:
            raise DocumentProcessorFailure("docling_task_identity_mismatch", retryable=True)
        try:
            state = ProcessorTaskState(str(value["task_status"]))
        except ValueError as exc:
            raise DocumentProcessorFailure("docling_task_status_invalid", retryable=True) from exc
        return ProcessorTask(task_id=task_id, state=state)

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self.client.request(method, f"{self.base_url}{path}", **kwargs)
        except httpx.TimeoutException as exc:
            raise DocumentProcessorFailure("docling_request_timeout", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise DocumentProcessorFailure("docling_service_unavailable", retryable=True) from exc
        content_length = response.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > self.max_response_bytes:
                    raise DocumentProcessorFailure(
                        "docling_response_size_exceeded", retryable=False
                    )
            except ValueError as exc:
                raise DocumentProcessorFailure(
                    "docling_response_schema_invalid", retryable=True
                ) from exc
        if response.status_code == 404 and path.startswith(("/v1/status/", "/v1/result/")):
            raise DocumentProcessorFailure("docling_task_not_found", retryable=True)
        if response.status_code == 413:
            raise DocumentProcessorFailure("docling_source_size_exceeded", retryable=False)
        if response.status_code in {400, 415, 422}:
            raise DocumentProcessorFailure("docling_format_rejected", retryable=False)
        if response.status_code in {408, 429} or response.status_code >= 500:
            raise DocumentProcessorFailure("docling_service_unavailable", retryable=True)
        if response.status_code < 200 or response.status_code >= 300:
            raise DocumentProcessorFailure("docling_request_rejected", retryable=False)
        if len(response.content) > self.max_response_bytes:
            raise DocumentProcessorFailure("docling_response_size_exceeded", retryable=False)
        if response.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            raise DocumentProcessorFailure("docling_response_media_type_invalid", retryable=True)
        try:
            return response.json()
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DocumentProcessorFailure("docling_response_json_invalid", retryable=True) from exc


def read_docling_api_key(path: str) -> str:
    configured = path.strip()
    if not configured:
        raise ValueError("Docling API key file is required")
    file_path = Path(configured)
    try:
        metadata = file_path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise ValueError("Docling API key file must be a regular non-symlink file")
        if not 32 <= metadata.st_size <= 4096:
            raise ValueError("Docling API key file size is invalid")
        if stat.S_IMODE(metadata.st_mode) & 0o022:
            raise ValueError("Docling API key file must not be writable by group or others")
        if (
            not str(file_path).startswith("/run/secrets/")
            and stat.S_IMODE(metadata.st_mode) & 0o077
        ):
            raise ValueError("Docling API key file permissions must be owner-only")
        value = file_path.read_text(encoding="ascii")
    except OSError as exc:
        raise ValueError("Docling API key file is unreadable") from exc
    if value != value.strip() or any(character.isspace() for character in value):
        raise ValueError("Docling API key format is invalid")
    return value


def _require_task_id(value: str) -> None:
    if not value or len(value) > 256 or any(character in value for character in "/\\\r\n"):
        raise DocumentProcessorFailure("docling_task_id_invalid", retryable=True)
