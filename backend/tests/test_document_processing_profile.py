from __future__ import annotations

import pytest

from app.modules.document_processing import (
    DOCLING_LAYOUT_OCR_V1,
    DOCLING_LAYOUT_OCR_V1_PROFILE_HASH,
    DOCLING_LAYOUT_OCR_V2,
    DOCLING_LAYOUT_OCR_V2_PROFILE_HASH,
    DOCLING_TEXT_V1,
    DOCLING_TEXT_V1_PROFILE_HASH,
    DocumentProcessingProfileCode,
    DocumentSourceFormatCode,
    document_processing_profile_snapshot,
    document_processing_state,
    normalize_document_processing_profile_code,
    resolve_document_processing_profile,
)
from app.modules.file_workspace.domain import FileAction
from app.shared.exceptions import NonRetryableExecutionError


def test_docling_text_v1_profile_is_closed_and_hash_stable() -> None:
    profile = DOCLING_TEXT_V1

    assert profile.code is DocumentProcessingProfileCode.DOCLING_TEXT_V1
    assert profile.version == "1"
    assert {item.code for item in profile.source_formats} == set(DocumentSourceFormatCode)
    assert profile.output_kinds == ("MARKDOWN", "DOCLING_JSON")
    assert profile.max_source_bytes == 25 * 1024 * 1024
    assert profile.max_pdf_pages == 300
    assert profile.processing_timeout_seconds == 600
    assert profile.max_markdown_bytes == 15 * 1024 * 1024
    assert profile.max_docling_json_bytes == 64 * 1024 * 1024
    assert profile.max_attempts == 3
    assert profile.profile_hash == DOCLING_TEXT_V1_PROFILE_HASH
    assert profile.profile_hash == (
        "337dc23bd405e7225e8ffca06b72852ed19121723bc8b1abeafdc05cf5ceac42"
    )

    for source in profile.source_formats:
        assert source.actions == {
            FileAction.READ_METADATA,
            FileAction.RETAIN,
            FileAction.DELIVER,
        }
        assert FileAction.MATERIALIZE not in source.actions
        assert FileAction.EDIT not in source.actions
        assert FileAction.COMMIT not in source.actions


def test_docling_text_v1_provider_options_disable_visual_and_remote_expansion() -> None:
    options = dict(DOCLING_TEXT_V1.request_options)

    assert options["to_formats"] == ["md", "json"]
    assert options["image_export_mode"] == "placeholder"
    assert options["do_ocr"] is True
    assert options["do_table_structure"] is True
    assert options["do_picture_description"] is False
    assert options["do_code_enrichment"] is False
    assert options["do_formula_enrichment"] is False
    assert options["include_images"] is False
    assert not DOCLING_TEXT_V1.remote_services_enabled
    assert not DOCLING_TEXT_V1.external_plugins_enabled
    assert not DOCLING_TEXT_V1.custom_vlm_config_enabled
    assert not DOCLING_TEXT_V1.custom_picture_description_config_enabled
    assert not DOCLING_TEXT_V1.custom_code_formula_config_enabled
    assert not DOCLING_TEXT_V1.callbacks_enabled
    assert not DOCLING_TEXT_V1.http_sources_enabled
    assert not DOCLING_TEXT_V1.runtime_model_download_enabled
    assert {
        "url",
        "callback",
        "headers",
        "vlm_pipeline_custom_config",
        "picture_description_api",
    }.isdisjoint(options)


def test_docling_layout_ocr_v1_is_a_complete_fixed_superset() -> None:
    profile = DOCLING_LAYOUT_OCR_V1

    assert profile.code is DocumentProcessingProfileCode.DOCLING_LAYOUT_OCR_V1
    assert profile.version == "1"
    assert profile.source_formats == DOCLING_TEXT_V1.source_formats
    assert profile.request_options == DOCLING_TEXT_V1.request_options
    assert profile.output_kinds == ("MARKDOWN", "DOCLING_JSON", "OCR_LAYOUT_JSON")
    assert profile.profile_hash == DOCLING_LAYOUT_OCR_V1_PROFILE_HASH
    assert profile.profile_hash == (
        "3d7fc7efe62fbd1cc42bd1d00f944a97fa722699eb4b59041398a87a2ebb57ad"
    )

    layout = profile.canonical_payload["layout_ocr"]
    assert layout["embedded_source_formats"] == ["DOCX", "PPTX"]
    assert layout["bundle_request_options"]["target_type"] == "zip"
    assert layout["bundle_request_options"]["image_export_mode"] == "referenced"
    assert layout["picture_ocr_request_options"]["ocr_preset"] == "rapidocr"
    assert layout["picture_pixel_basis"] == {
        "source": "docling-referenced-embedded-media",
        "image_exif_orientation_applied": True,
        "office_display_crop_rotation_flip_applied": False,
    }
    assert layout["model_artifact"]["digest"] == (
        "sha256:9e53a21c25853b53fa0b46df02bb8ebad1d5087dee342d7ef412efecaad0912c"
    )
    assert layout["layout_schema"] == {
        "name": "enterprise-agent.office-image-ocr-layout",
        "version": "v1",
    }
    assert layout["limits"]["soft_picture_occurrences"] == 32
    assert layout["limits"]["hard_picture_occurrences"] == 128
    assert layout["limits"]["max_global_docling_concurrency"] == 1
    assert layout["security"]["vlm_enabled"] is False
    assert layout["security"]["runtime_options_override_enabled"] is False


def test_docling_layout_ocr_v2_freezes_nullable_upstream_confidence_contract() -> None:
    profile = DOCLING_LAYOUT_OCR_V2

    assert profile.code is DocumentProcessingProfileCode.DOCLING_LAYOUT_OCR_V2
    assert profile.version == "2"
    assert profile.source_formats == DOCLING_LAYOUT_OCR_V1.source_formats
    assert profile.request_options == DOCLING_LAYOUT_OCR_V1.request_options
    assert profile.output_kinds == DOCLING_LAYOUT_OCR_V1.output_kinds
    assert profile.profile_hash == DOCLING_LAYOUT_OCR_V2_PROFILE_HASH
    assert profile.profile_hash == (
        "c3f6d45b3d23f70727e047158f20b1e798fa9a6d188aa11b8985385a1bc79cb8"
    )

    layout = profile.canonical_payload["layout_ocr"]
    assert layout["layout_schema"] == {
        "name": "enterprise-agent.office-image-ocr-layout",
        "version": "v2",
    }
    assert layout["picture_result_schema"] == {
        "name": "enterprise-agent.office-picture-ocr-result",
        "version": "v2",
    }
    assert layout["confidence_contract"] == {
        "source": "docling-text-item-or-provenance",
        "unit": "basis-points",
        "missing_value": None,
        "aggregate_fallback_enabled": False,
    }
    assert layout["assembler_version"] == "office-image-layout-assembler/v2"


def test_docling_text_v1_payload_does_not_inherit_layout_fields() -> None:
    assert "layout_ocr" not in DOCLING_TEXT_V1.canonical_payload
    assert DOCLING_TEXT_V1.profile_hash == DOCLING_TEXT_V1_PROFILE_HASH


def test_profile_snapshot_preserves_disabled_legacy_default() -> None:
    assert normalize_document_processing_profile_code(None) is DocumentProcessingProfileCode.NONE
    assert resolve_document_processing_profile("NONE") is None
    assert document_processing_profile_snapshot(None) == {
        "code": "NONE",
        "version": "",
        "hash": "",
    }
    assert document_processing_profile_snapshot("docling-text-v1") == {
        "code": "docling-text-v1",
        "version": "1",
        "hash": DOCLING_TEXT_V1.profile_hash,
    }
    assert document_processing_profile_snapshot("docling-layout-ocr-v1") == {
        "code": "docling-layout-ocr-v1",
        "version": "1",
        "hash": DOCLING_LAYOUT_OCR_V1.profile_hash,
    }
    assert document_processing_profile_snapshot("docling-layout-ocr-v2") == {
        "code": "docling-layout-ocr-v2",
        "version": "2",
        "hash": DOCLING_LAYOUT_OCR_V2.profile_hash,
    }


def test_unknown_or_arbitrary_profile_is_rejected() -> None:
    with pytest.raises(NonRetryableExecutionError) as error:
        resolve_document_processing_profile("https://example.invalid/docling")

    assert error.value.error_code == "validation_failed"
    assert error.value.field_errors == [
        {
            "field": "document_processing_profile_code",
            "message": "文档处理Profile不受支持",
        }
    ]


def test_document_processing_state_never_reports_ready_without_all_dependencies() -> None:
    assert document_processing_state("NONE") == {
        "document_processing_status": "DISABLED",
        "document_processing_reason_code": "profile_disabled",
    }
    assert document_processing_state("docling-text-v1") == {
        "document_processing_status": "CONFIGURED_UNAVAILABLE",
        "document_processing_reason_code": "processing_dependencies_unavailable",
    }
    assert document_processing_state(
        "docling-text-v1", dependencies_ready=True
    )["document_processing_status"] == "READY"
