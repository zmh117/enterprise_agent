from __future__ import annotations

import pytest

from app.modules.document_processing import (
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
