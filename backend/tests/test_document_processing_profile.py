from __future__ import annotations

import pytest

from app.modules.document_processing import (
    DOCLING_LAYOUT_OCR_V2,
    DOCLING_LAYOUT_OCR_V2_PROFILE_HASH,
    DocumentProcessingProfileCode,
    DocumentSourceFormatCode,
    document_processing_profile_snapshot,
    document_processing_state,
    normalize_document_processing_profile_code,
    resolve_document_processing_profile,
)
from app.modules.file_workspace.domain import FileAction
from app.shared.exceptions import NonRetryableExecutionError


def test_only_current_layout_ocr_profile_is_registered_and_hash_stable() -> None:
    profile = DOCLING_LAYOUT_OCR_V2
    assert profile.code is DocumentProcessingProfileCode.DOCLING_LAYOUT_OCR_V2
    assert profile.version == "2"
    assert {item.code for item in profile.source_formats} == set(DocumentSourceFormatCode)
    assert profile.output_kinds == ("MARKDOWN", "DOCLING_JSON", "OCR_LAYOUT_JSON")
    assert profile.profile_hash == DOCLING_LAYOUT_OCR_V2_PROFILE_HASH
    assert profile.profile_hash == (
        "7265262613d8cd022f7703d3f0ada08785a87bfe7bc4cfe550605ef3fbd605e1"
    )
    for source in profile.source_formats:
        assert source.actions == {
            FileAction.READ_METADATA,
            FileAction.RETAIN,
            FileAction.DELIVER,
        }


def test_current_profile_is_a_complete_independent_fixed_definition() -> None:
    profile = DOCLING_LAYOUT_OCR_V2
    options = dict(profile.request_options)
    assert options["to_formats"] == ["md", "json"]
    assert options["do_ocr"] is True
    assert options["do_table_structure"] is True
    assert options["do_picture_description"] is False
    assert options["include_images"] is False
    assert not profile.remote_services_enabled
    assert not profile.external_plugins_enabled
    assert not profile.callbacks_enabled
    assert not profile.http_sources_enabled
    assert not profile.runtime_model_download_enabled

    layout = profile.canonical_payload["layout_ocr"]
    assert layout["embedded_source_formats"] == ["DOCX", "PPTX"]
    assert layout["layout_schema"]["version"] == "v2"
    assert layout["picture_result_schema"]["version"] == "v2"
    assert layout["picture_result_adapter"] == {
        "version": "docling-picture-result-adapter/v2",
    }
    assert layout["assembler_version"] == "office-image-layout-assembler/v2"
    assert layout["confidence_contract"]["missing_value"] is None
    assert layout["confidence_contract"]["aggregate_fallback_enabled"] is False
    assert layout["picture_pixel_basis"] == {
        "source": "docling-referenced-embedded-media",
        "image_exif_orientation_applied": True,
        "office_display_crop_rotation_flip_applied": False,
    }
    assert layout["security"]["vlm_enabled"] is False
    assert layout["security"]["runtime_options_override_enabled"] is False
    assert layout["model_artifact"] == {
        "code": "docling-v1.30.0-cpu-model-bundle",
        "revision": "v1.30.0",
        "image_index_digest": (
            "sha256:0244089785d5ccb7570dfaa593cdc81ec64a1aadc63ffa9dce065064b0a6a807"
        ),
        "manifest_algorithm": "relative-path-size-content-sha256/v1",
        "platforms": {
            "linux/amd64": {
                "image_manifest_digest": (
                    "sha256:0ccbc00b5f8b443334a7c4f36a5c6ff89c684c6fbe18ff7c1bc41e00b8e01657"
                ),
                "digest": (
                    "sha256:bd9b6624ee97cd02b2506737e6f1646e25c68bf64a1cf4825a2ff69a5992c090"
                ),
            },
            "linux/arm64": {
                "image_manifest_digest": (
                    "sha256:b09477515c6234bb86c8a90c9db3af2b5d6991aeb6b64c3348283be264dba63c"
                ),
                "digest": (
                    "sha256:9e53a21c25853b53fa0b46df02bb8ebad1d5087dee342d7ef412efecaad0912c"
                ),
            },
        },
    }


def test_profile_selection_is_only_none_or_current_v2() -> None:
    assert normalize_document_processing_profile_code(None) is DocumentProcessingProfileCode.NONE
    assert resolve_document_processing_profile("NONE") is None
    assert document_processing_profile_snapshot(None) == {
        "code": "NONE",
        "version": "",
        "hash": "",
    }
    assert document_processing_profile_snapshot("docling-layout-ocr-v2") == {
        "code": "docling-layout-ocr-v2",
        "version": "2",
        "hash": DOCLING_LAYOUT_OCR_V2.profile_hash,
    }

    for removed in ("docling-text-v1", "docling-layout-ocr-v1"):
        with pytest.raises(NonRetryableExecutionError) as rejected:
            resolve_document_processing_profile(removed)
        assert rejected.value.error_code == "validation_failed"


def test_document_processing_state_requires_current_dependencies() -> None:
    assert document_processing_state("NONE") == {
        "document_processing_status": "DISABLED",
        "document_processing_reason_code": "profile_disabled",
    }
    assert document_processing_state("docling-layout-ocr-v2") == {
        "document_processing_status": "CONFIGURED_UNAVAILABLE",
        "document_processing_reason_code": "processing_dependencies_unavailable",
    }
    assert (
        document_processing_state("docling-layout-ocr-v2", dependencies_ready=True)[
            "document_processing_status"
        ]
        == "READY"
    )
