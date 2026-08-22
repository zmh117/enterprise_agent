from __future__ import annotations

import json
import math
import stat
import zipfile
from dataclasses import dataclass
from enum import StrEnum
from io import BytesIO
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, BinaryIO, Protocol
from urllib.parse import quote, urlsplit

import httpx

from app.modules.document_processing.profile import (
    DocumentProcessingProfile,
    DocumentProcessingProfileCode,
    require_document_processing_profile,
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


@dataclass(frozen=True, slots=True)
class EmbeddedPictureArtifact:
    occurrence_index: int
    picture_ref: str
    parent_ref: str
    parent_label: str
    parent_ordinal: int
    slide_no: int | None
    parent_bbox: list[int] | None
    media_type: str
    content: bytes


@dataclass(frozen=True, slots=True)
class DocumentProcessorBundleResult:
    markdown: bytes
    docling_json: bytes
    pictures: tuple[EmbeddedPictureArtifact, ...]
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

    def fetch_bundle(
        self,
        task_id: str,
        *,
        profile: DocumentProcessingProfile,
        source_format: str,
    ) -> DocumentProcessorBundleResult: ...

    def submit_picture(
        self,
        *,
        stream: BinaryIO,
        media_type: str,
        profile: DocumentProcessingProfile,
    ) -> ProcessorTask: ...

    def fetch_picture(
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
        registered = require_document_processing_profile(
            profile.code.value, profile_hash=profile.profile_hash
        )
        if registered is not profile:
            raise DocumentProcessorFailure("document_profile_mismatch", retryable=False)
        definition = profile.source_by_code(format_code)
        if media_type.split(";", 1)[0].strip().lower() not in definition.accepted_media_types:
            raise DocumentProcessorFailure("document_source_media_type_mismatch", retryable=False)
        options = profile.request_options
        target_type = "inbody"
        if profile.layout_ocr_options is not None and format_code in {"DOCX", "PPTX"}:
            if profile.layout_ocr_options is None:
                raise DocumentProcessorFailure("document_profile_mismatch", retryable=False)
            options = profile.layout_ocr_options["bundle_request_options"]
            target_type = "zip"
        fields: dict[str, str | list[str]] = {}
        for key, value in options.items():
            if key == "target_type":
                continue
            values = value if isinstance(value, (tuple, list)) else [value]
            encoded_values: list[str] = []
            for item in values:
                if isinstance(item, bool):
                    encoded = "true" if item else "false"
                else:
                    encoded = str(item)
                encoded_values.append(encoded)
            fields[key] = encoded_values if isinstance(value, (tuple, list)) else encoded_values[0]
        fields["from_formats"] = definition.docling_format
        fields["target_type"] = target_type
        response = self._request(
            "POST",
            "/v1/convert/file/async",
            data=fields,
            files={
                "files": (
                    f"document-input{definition.extensions[0]}",
                    stream,
                    definition.canonical_media_type,
                )
            },
        )
        return self._task(response, expected_task_id=None)

    def poll(self, task_id: str) -> ProcessorTask:
        _require_task_id(task_id)
        response = self._request("GET", f"/v1/status/poll/{quote(task_id, safe='')}")
        return self._task(response, expected_task_id=task_id)

    def fetch(self, task_id: str, *, profile: DocumentProcessingProfile) -> DocumentProcessorResult:
        if profile.code is not DocumentProcessingProfileCode.DOCLING_LAYOUT_OCR_V2:
            raise DocumentProcessorFailure("document_profile_mismatch", retryable=False)
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

    def fetch_bundle(
        self,
        task_id: str,
        *,
        profile: DocumentProcessingProfile,
        source_format: str,
    ) -> DocumentProcessorBundleResult:
        _require_task_id(task_id)
        registered = require_document_processing_profile(
            profile.code.value,
            profile_hash=profile.profile_hash,
        )
        if (
            registered is not profile
            or source_format not in {"DOCX", "PPTX"}
            or profile.layout_ocr_options is None
        ):
            raise DocumentProcessorFailure("document_profile_mismatch", retryable=False)
        limits = profile.layout_ocr_options["limits"]
        maximum_bundle = int(limits["max_bundle_bytes"])
        body = self._request_bytes(
            "GET",
            f"/v1/result/{quote(task_id, safe='')}",
            expected_media_type="application/zip",
            maximum_bytes=maximum_bundle,
        )
        return _parse_office_picture_bundle(
            body,
            profile=profile,
            source_format=source_format,
        )

    def submit_picture(
        self,
        *,
        stream: BinaryIO,
        media_type: str,
        profile: DocumentProcessingProfile,
    ) -> ProcessorTask:
        registered = require_document_processing_profile(
            profile.code.value,
            profile_hash=profile.profile_hash,
        )
        if registered is not profile or profile.layout_ocr_options is None:
            raise DocumentProcessorFailure("document_profile_mismatch", retryable=False)
        if media_type not in {"image/png", "image/jpeg", "image/webp"}:
            raise DocumentProcessorFailure("document_source_media_type_mismatch", retryable=False)
        if profile.layout_ocr_options is None:
            raise DocumentProcessorFailure("document_profile_mismatch", retryable=False)
        fields: dict[str, str | list[str]] = {}
        for key, value in profile.layout_ocr_options["picture_ocr_request_options"].items():
            values = value if isinstance(value, (tuple, list)) else [value]
            encoded_values = [
                ("true" if item else "false") if isinstance(item, bool) else str(item)
                for item in values
            ]
            fields[key] = encoded_values if isinstance(value, (tuple, list)) else encoded_values[0]
        response = self._request(
            "POST",
            "/v1/convert/file/async",
            data=fields,
            files={"files": ("picture-input", stream, media_type)},
        )
        return self._task(response, expected_task_id=None)

    def fetch_picture(
        self,
        task_id: str,
        *,
        profile: DocumentProcessingProfile,
    ) -> DocumentProcessorResult:
        _require_task_id(task_id)
        registered = require_document_processing_profile(
            profile.code.value,
            profile_hash=profile.profile_hash,
        )
        if registered is not profile or profile.layout_ocr_options is None:
            raise DocumentProcessorFailure("document_profile_mismatch", retryable=False)
        value = self._request("GET", f"/v1/result/{quote(task_id, safe='')}")
        if not isinstance(value, dict) or not set(value).issubset(self._result_keys):
            raise DocumentProcessorFailure("docling_response_schema_invalid", retryable=True)
        if not {"document", "status", "processing_time", "timings", "errors"}.issubset(value):
            raise DocumentProcessorFailure("docling_response_schema_invalid", retryable=True)
        status = str(value["status"])
        if status == "failure":
            raise DocumentProcessorFailure("docling_conversion_failed", retryable=False)
        if status not in {"success", "partial_success"}:
            raise DocumentProcessorFailure("docling_response_schema_invalid", retryable=True)
        document = value["document"]
        if not isinstance(document, dict) or not set(document).issubset(self._document_keys):
            raise DocumentProcessorFailure("docling_response_schema_invalid", retryable=True)
        markdown_value = document.get("md_content")
        if markdown_value is not None and not isinstance(markdown_value, str):
            raise DocumentProcessorFailure("docling_picture_result_invalid", retryable=False)
        errors = value["errors"]
        if not isinstance(errors, list) or len(errors) > 100:
            raise DocumentProcessorFailure("docling_response_schema_invalid", retryable=True)
        processing_time = value["processing_time"]
        if not isinstance(processing_time, (int, float)) or isinstance(processing_time, bool):
            raise DocumentProcessorFailure("docling_response_schema_invalid", retryable=True)
        markdown = str(markdown_value or "").encode()
        json_value = document.get("json_content")
        json_has_text = False
        if isinstance(json_value, dict):
            texts = json_value.get("texts")
            json_has_text = isinstance(texts, list) and any(
                isinstance(item, dict)
                and isinstance(item.get("text"), str)
                and bool(str(item["text"]).strip())
                for item in texts
            )
        confirmed_no_text = (
            profile.code is DocumentProcessingProfileCode.DOCLING_LAYOUT_OCR_V2
            and status == "success"
            and not errors
            and not markdown.strip()
            and not json_has_text
        )
        if confirmed_no_text:
            encoded_json = b"{}"
        else:
            if (
                not isinstance(json_value, dict)
                or json_value.get("schema_name") != "DoclingDocument"
            ):
                raise DocumentProcessorFailure("docling_picture_result_invalid", retryable=False)
            encoded_json = json.dumps(
                json_value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        return DocumentProcessorResult(
            markdown=markdown,
            docling_json=encoded_json,
            partial=status == "partial_success" or bool(errors),
            no_text=confirmed_no_text,
            page_count=1,
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

    def _request_bytes(
        self,
        method: str,
        path: str,
        *,
        expected_media_type: str,
        maximum_bytes: int,
    ) -> bytes:
        try:
            with self.client.stream(method, f"{self.base_url}{path}") as response:
                self._validate_status(response, path=path)
                media_type = response.headers.get("content-type", "").split(";", 1)[0]
                if media_type != expected_media_type:
                    raise DocumentProcessorFailure(
                        "docling_response_media_type_invalid", retryable=True
                    )
                content_length = response.headers.get("content-length")
                if content_length is not None:
                    try:
                        if int(content_length) > maximum_bytes:
                            raise DocumentProcessorFailure(
                                "docling_response_size_exceeded", retryable=False
                            )
                    except ValueError as exc:
                        raise DocumentProcessorFailure(
                            "docling_response_schema_invalid", retryable=True
                        ) from exc
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > maximum_bytes:
                        raise DocumentProcessorFailure(
                            "docling_response_size_exceeded", retryable=False
                        )
                    chunks.append(chunk)
                return b"".join(chunks)
        except DocumentProcessorFailure:
            raise
        except httpx.TimeoutException as exc:
            raise DocumentProcessorFailure("docling_request_timeout", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise DocumentProcessorFailure("docling_service_unavailable", retryable=True) from exc

    @staticmethod
    def _validate_status(response: httpx.Response, *, path: str) -> None:
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


def _safe_bundle_path(value: str) -> PurePosixPath:
    if not value or "\\" in value or "\x00" in value:
        raise DocumentProcessorFailure("docling_bundle_path_invalid", retryable=False)
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise DocumentProcessorFailure("docling_bundle_path_invalid", retryable=False)
    return path


def _strict_json_bytes(value: bytes) -> dict[str, Any]:
    def reject_constant(_: str) -> None:
        raise ValueError("non-finite JSON number")

    try:
        decoded = json.loads(value.decode("utf-8", errors="strict"), parse_constant=reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise DocumentProcessorFailure("docling_json_schema_invalid", retryable=False) from exc
    if not isinstance(decoded, dict) or decoded.get("schema_name") != "DoclingDocument":
        raise DocumentProcessorFailure("docling_json_schema_invalid", retryable=False)
    return decoded


def _resolve_json_ref(document: dict[str, Any], value: object) -> object | None:
    if not isinstance(value, str) or not value.startswith("#/") or len(value) > 512:
        return None
    current: object = document
    for raw_part in value[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None
    return current


def _parent_ordinal(parent: object, picture_ref: str) -> int:
    if not isinstance(parent, dict) or not isinstance(parent.get("children"), list):
        raise DocumentProcessorFailure("docling_picture_parent_invalid", retryable=False)
    refs = [
        str(child.get("$ref"))
        for child in parent["children"]
        if isinstance(child, dict) and isinstance(child.get("$ref"), str)
    ]
    if picture_ref not in refs:
        raise DocumentProcessorFailure("docling_picture_parent_invalid", retryable=False)
    return refs.index(picture_ref)


def _document_page_size(document: dict[str, Any], page_no: int) -> tuple[float, float]:
    pages = document.get("pages")
    page: object | None = None
    if isinstance(pages, dict):
        page = pages.get(str(page_no), pages.get(page_no))
    elif isinstance(pages, list) and 0 < page_no <= len(pages):
        page = pages[page_no - 1]
    if not isinstance(page, dict) or not isinstance(page.get("size"), dict):
        raise DocumentProcessorFailure("docling_picture_anchor_invalid", retryable=False)
    width = page["size"].get("width")
    height = page["size"].get("height")
    if (
        not isinstance(width, (int, float))
        or isinstance(width, bool)
        or not isinstance(height, (int, float))
        or isinstance(height, bool)
        or not math.isfinite(float(width))
        or not math.isfinite(float(height))
        or float(width) <= 0
        or float(height) <= 0
    ):
        raise DocumentProcessorFailure("docling_picture_anchor_invalid", retryable=False)
    return float(width), float(height)


def _validated_parent_bbox(
    value: object, *, page_width: float, page_height: float
) -> list[int]:
    if not isinstance(value, dict):
        raise DocumentProcessorFailure("docling_picture_bbox_invalid", retryable=False)
    allowed = {"l", "t", "r", "b", "coord_origin"}
    if set(value) != allowed or value.get("coord_origin") not in {"BOTTOMLEFT", "TOPLEFT"}:
        raise DocumentProcessorFailure("docling_picture_bbox_invalid", retryable=False)
    coordinates: dict[str, float] = {}
    for key in ("l", "t", "r", "b"):
        coordinate = value[key]
        if (
            not isinstance(coordinate, (int, float))
            or isinstance(coordinate, bool)
            or not math.isfinite(float(coordinate))
        ):
            raise DocumentProcessorFailure("docling_picture_bbox_invalid", retryable=False)
        coordinates[key] = float(coordinate)
    if value["coord_origin"] == "BOTTOMLEFT":
        left, top, right, bottom = (
            coordinates["l"],
            page_height - coordinates["t"],
            coordinates["r"],
            page_height - coordinates["b"],
        )
    else:
        left, top, right, bottom = (
            coordinates["l"],
            coordinates["t"],
            coordinates["r"],
            coordinates["b"],
        )
    if (
        left < 0
        or top < 0
        or right > page_width
        or bottom > page_height
        or right <= left
        or bottom <= top
    ):
        raise DocumentProcessorFailure("docling_picture_bbox_invalid", retryable=False)
    normalized = [
        int(round(left * 10_000 / page_width)),
        int(round(top * 10_000 / page_height)),
        int(round(right * 10_000 / page_width)),
        int(round(bottom * 10_000 / page_height)),
    ]
    if (
        any(item < 0 or item > 10_000 for item in normalized)
        or normalized[2] <= normalized[0]
        or normalized[3] <= normalized[1]
    ):
        raise DocumentProcessorFailure("docling_picture_bbox_invalid", retryable=False)
    return normalized


def _parse_office_picture_bundle(
    body: bytes,
    *,
    profile: DocumentProcessingProfile,
    source_format: str,
) -> DocumentProcessorBundleResult:
    if profile.layout_ocr_options is None:
        raise DocumentProcessorFailure("document_profile_mismatch", retryable=False)
    limits = profile.layout_ocr_options["limits"]
    maximum_entries = int(limits["max_bundle_entries"])
    maximum_uncompressed = int(limits["max_bundle_uncompressed_bytes"])
    maximum_pictures = int(limits["hard_picture_occurrences"])
    try:
        archive = zipfile.ZipFile(BytesIO(body))
    except (zipfile.BadZipFile, OSError) as exc:
        raise DocumentProcessorFailure("docling_bundle_invalid", retryable=False) from exc
    with archive:
        members = archive.infolist()
        if not 1 <= len(members) <= maximum_entries:
            raise DocumentProcessorFailure("docling_bundle_entry_limit_exceeded", retryable=False)
        files: dict[str, zipfile.ZipInfo] = {}
        total_uncompressed = 0
        for member in members:
            normalized = str(_safe_bundle_path(member.filename.rstrip("/")))
            if normalized in files:
                raise DocumentProcessorFailure("docling_bundle_entry_duplicate", retryable=False)
            if stat.S_ISLNK(member.external_attr >> 16) or member.flag_bits & 0x1:
                raise DocumentProcessorFailure("docling_bundle_entry_unsafe", retryable=False)
            if member.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                raise DocumentProcessorFailure("docling_bundle_compression_invalid", retryable=False)
            if member.is_dir():
                continue
            total_uncompressed += member.file_size
            if total_uncompressed > maximum_uncompressed:
                raise DocumentProcessorFailure(
                    "docling_bundle_uncompressed_limit_exceeded", retryable=False
                )
            files[normalized] = member
        json_names = [name for name in files if PurePosixPath(name).suffix.lower() == ".json"]
        markdown_names = [name for name in files if PurePosixPath(name).suffix.lower() == ".md"]
        if len(json_names) != 1 or len(markdown_names) != 1:
            raise DocumentProcessorFailure("docling_bundle_schema_invalid", retryable=False)
        json_member = files[json_names[0]]
        markdown_member = files[markdown_names[0]]
        if (
            json_member.file_size > profile.max_docling_json_bytes
            or markdown_member.file_size > profile.max_markdown_bytes
        ):
            raise DocumentProcessorFailure("docling_response_size_exceeded", retryable=False)
        document = _strict_json_bytes(archive.read(json_member))
        markdown = archive.read(markdown_member)
        try:
            markdown.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise DocumentProcessorFailure("docling_markdown_encoding_invalid", retryable=False) from exc
        pictures = document.get("pictures")
        if not isinstance(pictures, list) or len(pictures) > maximum_pictures:
            raise DocumentProcessorFailure("docling_picture_limit_exceeded", retryable=False)
        artifacts: list[EmbeddedPictureArtifact] = []
        referenced_image_names: set[str] = set()
        seen_picture_refs: set[str] = set()
        for occurrence_index, picture in enumerate(pictures, start=1):
            if not isinstance(picture, dict):
                raise DocumentProcessorFailure("docling_picture_schema_invalid", retryable=False)
            picture_ref = picture.get("self_ref")
            parent_pointer = picture.get("parent")
            image = picture.get("image")
            if (
                not isinstance(picture_ref, str)
                or not picture_ref.startswith("#/")
                or picture_ref in seen_picture_refs
                or not isinstance(parent_pointer, dict)
                or not isinstance(parent_pointer.get("$ref"), str)
                or not isinstance(image, dict)
            ):
                raise DocumentProcessorFailure("docling_picture_schema_invalid", retryable=False)
            seen_picture_refs.add(picture_ref)
            parent_ref = str(parent_pointer["$ref"])
            parent = _resolve_json_ref(document, parent_ref)
            if not isinstance(parent, dict):
                raise DocumentProcessorFailure("docling_picture_parent_invalid", retryable=False)
            parent_label = str(parent.get("label") or "")
            if len(parent_label) > 128:
                raise DocumentProcessorFailure("docling_picture_parent_invalid", retryable=False)
            parent_ordinal = _parent_ordinal(parent, picture_ref)
            uri = image.get("uri")
            media_type = str(image.get("mimetype") or "")
            if not isinstance(uri, str) or uri.startswith(("data:", "http:", "https:")):
                raise DocumentProcessorFailure("docling_picture_reference_invalid", retryable=False)
            image_name = str(_safe_bundle_path(uri))
            image_member = files.get(image_name)
            if image_member is None or media_type not in {"image/png", "image/jpeg", "image/webp"}:
                raise DocumentProcessorFailure("docling_picture_reference_invalid", retryable=False)
            expected_suffixes = {
                "image/png": {".png"},
                "image/jpeg": {".jpg", ".jpeg"},
                "image/webp": {".webp"},
            }
            if PurePosixPath(image_name).suffix.lower() not in expected_suffixes[media_type]:
                raise DocumentProcessorFailure("docling_picture_media_type_invalid", retryable=False)
            if image_member.file_size > int(limits["max_picture_compressed_bytes"]):
                raise DocumentProcessorFailure("docling_picture_size_exceeded", retryable=False)
            slide_no: int | None = None
            parent_bbox: list[int] | None = None
            provenance = picture.get("prov")
            if source_format == "PPTX":
                if not isinstance(provenance, list) or not provenance:
                    raise DocumentProcessorFailure("docling_picture_anchor_invalid", retryable=False)
                first = provenance[0]
                if (
                    not isinstance(first, dict)
                    or not isinstance(first.get("page_no"), int)
                    or int(first["page_no"]) < 1
                ):
                    raise DocumentProcessorFailure("docling_picture_anchor_invalid", retryable=False)
                slide_no = int(first["page_no"])
                page_width, page_height = _document_page_size(document, slide_no)
                parent_bbox = _validated_parent_bbox(
                    first.get("bbox"), page_width=page_width, page_height=page_height
                )
            elif source_format != "DOCX":
                raise DocumentProcessorFailure("document_profile_mismatch", retryable=False)
            referenced_image_names.add(image_name)
            artifacts.append(
                EmbeddedPictureArtifact(
                    occurrence_index=occurrence_index,
                    picture_ref=picture_ref,
                    parent_ref=parent_ref,
                    parent_label=parent_label,
                    parent_ordinal=parent_ordinal,
                    slide_no=slide_no,
                    parent_bbox=parent_bbox,
                    media_type=media_type,
                    content=archive.read(image_member),
                )
            )
        allowed_files = {json_names[0], markdown_names[0], *referenced_image_names}
        if set(files) != allowed_files:
            raise DocumentProcessorFailure("docling_bundle_entry_unknown", retryable=False)
        pages = document.get("pages")
        page_count = len(pages) if isinstance(pages, (dict, list)) else None
        canonical_json = json.dumps(
            document, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        return DocumentProcessorBundleResult(
            markdown=markdown,
            docling_json=canonical_json,
            pictures=tuple(artifacts),
            partial=False,
            no_text=not markdown.strip(),
            page_count=page_count,
            processing_time_ms=None,
        )
