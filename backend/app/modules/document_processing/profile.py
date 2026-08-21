from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping

from app.modules.file_workspace.domain import FileAction
from app.shared.exceptions import NonRetryableExecutionError


MIB = 1024 * 1024


def _plain_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain_value(item) for item in value]
    return value


class DocumentProcessingProfileCode(StrEnum):
    NONE = "NONE"
    DOCLING_TEXT_V1 = "docling-text-v1"
    DOCLING_LAYOUT_OCR_V1 = "docling-layout-ocr-v1"


class DocumentProcessingStatus(StrEnum):
    DISABLED = "DISABLED"
    CONFIGURED_UNAVAILABLE = "CONFIGURED_UNAVAILABLE"
    READY = "READY"


class DocumentSourceFormatCode(StrEnum):
    PDF = "PDF"
    DOCX = "DOCX"
    PPTX = "PPTX"
    XLSX = "XLSX"
    PNG = "PNG"
    JPEG = "JPEG"
    WEBP = "WEBP"


DOCUMENT_SOURCE_ACTIONS = frozenset(
    {
        FileAction.READ_METADATA,
        FileAction.RETAIN,
        FileAction.DELIVER,
    }
)


@dataclass(frozen=True, slots=True)
class DocumentSourceDefinition:
    code: DocumentSourceFormatCode
    extensions: tuple[str, ...]
    accepted_media_types: frozenset[str]
    canonical_media_type: str
    docling_format: str
    actions: frozenset[FileAction] = DOCUMENT_SOURCE_ACTIONS


@dataclass(frozen=True, slots=True)
class DocumentProcessingProfile:
    code: DocumentProcessingProfileCode
    version: str
    processor_code: str
    source_formats: tuple[DocumentSourceDefinition, ...]
    output_kinds: tuple[str, ...]
    request_options: Mapping[str, Any]
    max_source_bytes: int
    max_pdf_pages: int
    processing_timeout_seconds: int
    max_markdown_bytes: int
    max_docling_json_bytes: int
    max_attempts: int
    layout_ocr_options: Mapping[str, Any] | None = None
    remote_services_enabled: bool = False
    external_plugins_enabled: bool = False
    custom_vlm_config_enabled: bool = False
    custom_picture_description_config_enabled: bool = False
    custom_code_formula_config_enabled: bool = False
    callbacks_enabled: bool = False
    http_sources_enabled: bool = False
    runtime_model_download_enabled: bool = False

    @property
    def canonical_payload(self) -> dict[str, Any]:
        payload = {
            "code": self.code.value,
            "version": self.version,
            "processor_code": self.processor_code,
            "source_formats": [
                {
                    "code": item.code.value,
                    "extensions": list(item.extensions),
                    "accepted_media_types": sorted(item.accepted_media_types),
                    "canonical_media_type": item.canonical_media_type,
                    "docling_format": item.docling_format,
                    "actions": sorted(action.value for action in item.actions),
                }
                for item in self.source_formats
            ],
            "output_kinds": list(self.output_kinds),
            "request_options": dict(self.request_options),
            "limits": {
                "max_source_bytes": self.max_source_bytes,
                "max_pdf_pages": self.max_pdf_pages,
                "processing_timeout_seconds": self.processing_timeout_seconds,
                "max_markdown_bytes": self.max_markdown_bytes,
                "max_docling_json_bytes": self.max_docling_json_bytes,
                "max_attempts": self.max_attempts,
            },
            "security": {
                "remote_services_enabled": self.remote_services_enabled,
                "external_plugins_enabled": self.external_plugins_enabled,
                "custom_vlm_config_enabled": self.custom_vlm_config_enabled,
                "custom_picture_description_config_enabled": (
                    self.custom_picture_description_config_enabled
                ),
                "custom_code_formula_config_enabled": (self.custom_code_formula_config_enabled),
                "callbacks_enabled": self.callbacks_enabled,
                "http_sources_enabled": self.http_sources_enabled,
                "runtime_model_download_enabled": self.runtime_model_download_enabled,
            },
        }
        if self.layout_ocr_options is not None:
            payload["layout_ocr"] = _plain_value(self.layout_ocr_options)
        return payload

    @property
    def profile_hash(self) -> str:
        encoded = json.dumps(
            self.canonical_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def source_by_code(self, value: str | DocumentSourceFormatCode) -> DocumentSourceDefinition:
        try:
            code = DocumentSourceFormatCode(str(value))
        except ValueError as exc:
            raise _profile_error("文档源格式不受支持") from exc
        for definition in self.source_formats:
            if definition.code is code:
                return definition
        raise _profile_error("当前文档处理Profile不支持此源格式")


_PDF = DocumentSourceDefinition(
    code=DocumentSourceFormatCode.PDF,
    extensions=(".pdf",),
    accepted_media_types=frozenset({"application/pdf"}),
    canonical_media_type="application/pdf",
    docling_format="pdf",
)
_DOCX = DocumentSourceDefinition(
    code=DocumentSourceFormatCode.DOCX,
    extensions=(".docx",),
    accepted_media_types=frozenset(
        {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
    ),
    canonical_media_type=(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    docling_format="docx",
)
_PPTX = DocumentSourceDefinition(
    code=DocumentSourceFormatCode.PPTX,
    extensions=(".pptx",),
    accepted_media_types=frozenset(
        {"application/vnd.openxmlformats-officedocument.presentationml.presentation"}
    ),
    canonical_media_type=(
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    ),
    docling_format="pptx",
)
_XLSX = DocumentSourceDefinition(
    code=DocumentSourceFormatCode.XLSX,
    extensions=(".xlsx",),
    accepted_media_types=frozenset(
        {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
    ),
    canonical_media_type=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    docling_format="xlsx",
)
_PNG = DocumentSourceDefinition(
    code=DocumentSourceFormatCode.PNG,
    extensions=(".png",),
    accepted_media_types=frozenset({"image/png"}),
    canonical_media_type="image/png",
    docling_format="image",
)
_JPEG = DocumentSourceDefinition(
    code=DocumentSourceFormatCode.JPEG,
    extensions=(".jpg", ".jpeg"),
    accepted_media_types=frozenset({"image/jpeg"}),
    canonical_media_type="image/jpeg",
    docling_format="image",
)
_WEBP = DocumentSourceDefinition(
    code=DocumentSourceFormatCode.WEBP,
    extensions=(".webp",),
    accepted_media_types=frozenset({"image/webp"}),
    canonical_media_type="image/webp",
    docling_format="image",
)


DOCLING_TEXT_V1 = DocumentProcessingProfile(
    code=DocumentProcessingProfileCode.DOCLING_TEXT_V1,
    version="1",
    processor_code="docling-serve",
    source_formats=(_PDF, _DOCX, _PPTX, _XLSX, _PNG, _JPEG, _WEBP),
    output_kinds=("MARKDOWN", "DOCLING_JSON"),
    request_options=MappingProxyType(
        {
            "from_formats": ["pdf", "docx", "pptx", "xlsx", "image"],
            "to_formats": ["md", "json"],
            "image_export_mode": "placeholder",
            "do_ocr": True,
            "force_ocr": False,
            "do_table_structure": True,
            "table_mode": "accurate",
            "abort_on_error": False,
            "include_images": False,
            "do_picture_description": False,
            "do_code_enrichment": False,
            "do_formula_enrichment": False,
        }
    ),
    max_source_bytes=25 * MIB,
    max_pdf_pages=300,
    processing_timeout_seconds=600,
    max_markdown_bytes=15 * MIB,
    max_docling_json_bytes=64 * MIB,
    max_attempts=3,
)
DOCLING_TEXT_V1_PROFILE_HASH = "337dc23bd405e7225e8ffca06b72852ed19121723bc8b1abeafdc05cf5ceac42"

if DOCLING_TEXT_V1.profile_hash != DOCLING_TEXT_V1_PROFILE_HASH:
    raise RuntimeError("docling-text-v1 canonical profile hash changed")


DOCLING_LAYOUT_OCR_V1 = DocumentProcessingProfile(
    code=DocumentProcessingProfileCode.DOCLING_LAYOUT_OCR_V1,
    version="1",
    processor_code="docling-serve",
    source_formats=DOCLING_TEXT_V1.source_formats,
    output_kinds=("MARKDOWN", "DOCLING_JSON", "OCR_LAYOUT_JSON"),
    request_options=DOCLING_TEXT_V1.request_options,
    max_source_bytes=DOCLING_TEXT_V1.max_source_bytes,
    max_pdf_pages=DOCLING_TEXT_V1.max_pdf_pages,
    processing_timeout_seconds=DOCLING_TEXT_V1.processing_timeout_seconds,
    max_markdown_bytes=DOCLING_TEXT_V1.max_markdown_bytes,
    max_docling_json_bytes=DOCLING_TEXT_V1.max_docling_json_bytes,
    max_attempts=DOCLING_TEXT_V1.max_attempts,
    layout_ocr_options=MappingProxyType(
        {
            "embedded_source_formats": ("DOCX", "PPTX"),
            "bundle_request_options": {
                "target_type": "zip",
                "to_formats": ("md", "json"),
                "image_export_mode": "referenced",
                "include_images": True,
                "include_page_images": False,
                "do_ocr": True,
                "force_ocr": False,
                "do_table_structure": True,
                "table_mode": "accurate",
                "abort_on_error": False,
                "do_picture_description": False,
                "do_picture_classification": False,
                "do_chart_extraction": False,
                "do_code_enrichment": False,
                "do_formula_enrichment": False,
            },
            "picture_ocr_request_options": {
                "target_type": "inbody",
                "from_formats": ("image",),
                "to_formats": ("md", "json"),
                "image_export_mode": "placeholder",
                "include_images": False,
                "include_page_images": False,
                "do_ocr": True,
                "force_ocr": False,
                "ocr_preset": "rapidocr",
                "do_table_structure": False,
                "abort_on_error": True,
                "do_picture_description": False,
                "do_picture_classification": False,
                "do_chart_extraction": False,
                "do_code_enrichment": False,
                "do_formula_enrichment": False,
            },
            "picture_pixel_basis": {
                "source": "docling-referenced-embedded-media",
                "image_exif_orientation_applied": True,
                "office_display_crop_rotation_flip_applied": False,
            },
            "model_artifact": {
                "code": "docling-v1.30.0-cpu-model-bundle",
                "revision": "v1.30.0",
                "digest": (
                    "sha256:9e53a21c25853b53fa0b46df02bb8ebad1d5087dee342d7ef412efecaad0912c"
                ),
                "manifest_algorithm": "relative-path-size-content-sha256/v1",
            },
            "layout_schema": {
                "name": "enterprise-agent.office-image-ocr-layout",
                "version": "v1",
            },
            "assembler_version": "office-image-layout-assembler/v1",
            "relation_algorithm": {
                "version": "bounded-adjacent-geometry/v1",
                "allowed_relations": (
                    "LEFT_OF",
                    "RIGHT_OF",
                    "ABOVE",
                    "BELOW",
                    "SAME_ROW",
                    "CONTAINS",
                ),
            },
            "limits": {
                "soft_picture_occurrences": 32,
                "hard_picture_occurrences": 128,
                "max_picture_compressed_bytes": 10 * MIB,
                "max_picture_pixels": 16_777_216,
                "max_total_picture_pixels": 67_108_864,
                "max_derived_bytes": 256 * MIB,
                "max_bundle_bytes": 128 * MIB,
                "max_bundle_entries": 512,
                "max_bundle_uncompressed_bytes": 256 * MIB,
                "max_blocks_per_picture": 2_048,
                "max_words_per_picture": 8_192,
                "max_relations_per_picture": 4_096,
                "max_characters_per_picture": 262_144,
                "max_blocks_per_run": 16_384,
                "max_words_per_run": 65_536,
                "max_relations_per_run": 65_536,
                "max_characters_per_run": 4_194_304,
                "max_ocr_layout_json_bytes": 64 * MIB,
                "parent_deadline_seconds": 600,
                "picture_attempt_deadline_seconds": 120,
                "assembly_deadline_seconds": 120,
                "run_deadline_seconds": 1_800,
                "max_parent_attempts": 3,
                "max_picture_attempts": 3,
                "max_assembly_attempts": 3,
                "max_global_docling_concurrency": 1,
                "max_parent_picture_concurrency": 1,
            },
            "security": {
                "upload_name_policy": "fixed-synthetic-name",
                "agent_materializes_picture_assets": False,
                "agent_materializes_ocr_layout_json": False,
                "vlm_enabled": False,
                "runtime_options_override_enabled": False,
            },
        }
    ),
)
DOCLING_LAYOUT_OCR_V1_PROFILE_HASH = (
    "3d7fc7efe62fbd1cc42bd1d00f944a97fa722699eb4b59041398a87a2ebb57ad"
)

if DOCLING_LAYOUT_OCR_V1.profile_hash != DOCLING_LAYOUT_OCR_V1_PROFILE_HASH:
    raise RuntimeError("docling-layout-ocr-v1 canonical profile hash changed")


PROFILE_REGISTRY: Mapping[DocumentProcessingProfileCode, DocumentProcessingProfile] = (
    MappingProxyType(
        {
            DocumentProcessingProfileCode.DOCLING_TEXT_V1: DOCLING_TEXT_V1,
            DocumentProcessingProfileCode.DOCLING_LAYOUT_OCR_V1: DOCLING_LAYOUT_OCR_V1,
        }
    )
)


def normalize_document_processing_profile_code(
    value: object,
    *,
    default: DocumentProcessingProfileCode = DocumentProcessingProfileCode.NONE,
) -> DocumentProcessingProfileCode:
    normalized = str(value or default.value).strip()
    try:
        return DocumentProcessingProfileCode(normalized)
    except ValueError as exc:
        raise _profile_error("文档处理Profile不受支持") from exc


def resolve_document_processing_profile(
    value: object,
) -> DocumentProcessingProfile | None:
    code = normalize_document_processing_profile_code(value)
    if code is DocumentProcessingProfileCode.NONE:
        return None
    return PROFILE_REGISTRY[code]


def require_document_processing_profile(
    value: object,
    *,
    profile_hash: object | None = None,
) -> DocumentProcessingProfile:
    profile = resolve_document_processing_profile(value)
    if profile is None:
        raise _profile_error("文档处理Profile未启用")
    if profile_hash is not None and str(profile_hash) != profile.profile_hash:
        raise _profile_error("文档处理Profile版本不匹配")
    return profile


def required_output_kinds_for_profile(
    value: object,
    *,
    profile_hash: object | None = None,
) -> tuple[str, ...]:
    return require_document_processing_profile(
        value,
        profile_hash=profile_hash,
    ).output_kinds


def document_processing_profile_snapshot(value: object) -> dict[str, str]:
    profile = resolve_document_processing_profile(value)
    if profile is None:
        return {"code": DocumentProcessingProfileCode.NONE.value, "version": "", "hash": ""}
    return {
        "code": profile.code.value,
        "version": profile.version,
        "hash": profile.profile_hash,
    }


def document_processing_state(
    value: object,
    *,
    dependencies_ready: bool = False,
) -> dict[str, str]:
    profile = resolve_document_processing_profile(value)
    if profile is None:
        return {
            "document_processing_status": DocumentProcessingStatus.DISABLED.value,
            "document_processing_reason_code": "profile_disabled",
        }
    if not dependencies_ready:
        return {
            "document_processing_status": (DocumentProcessingStatus.CONFIGURED_UNAVAILABLE.value),
            "document_processing_reason_code": "processing_dependencies_unavailable",
        }
    return {
        "document_processing_status": DocumentProcessingStatus.READY.value,
        "document_processing_reason_code": "processing_dependencies_ready",
    }


def _profile_error(message: str) -> NonRetryableExecutionError:
    return NonRetryableExecutionError(
        "Document processing profile is invalid",
        safe_message=message,
        error_code="validation_failed",
        field_errors=[{"field": "document_processing_profile_code", "message": message}],
    )
