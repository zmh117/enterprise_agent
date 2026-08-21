from __future__ import annotations

import io

import pytest
from PIL import Image

from app.modules.document_processing.image_normalization import normalize_picture_asset
from app.modules.document_processing.profile import DOCLING_LAYOUT_OCR_V1
from app.modules.document_processing.provider import DocumentProcessorFailure


def _image_bytes(
    *,
    image_format: str = "PNG",
    size: tuple[int, int] = (12, 8),
    orientation: int | None = None,
) -> bytes:
    output = io.BytesIO()
    image = Image.new("RGB", size, color="white")
    metadata: dict[str, object] = {}
    if orientation is not None:
        exif = image.getexif()
        exif[274] = orientation
        metadata["exif"] = exif.tobytes()
    image.save(output, format=image_format, **metadata)
    return output.getvalue()


def test_picture_normalization_is_deterministic_and_strips_metadata() -> None:
    source = _image_bytes()
    first = normalize_picture_asset(
        source,
        declared_media_type="image/png",
        profile=DOCLING_LAYOUT_OCR_V1,
    )
    second = normalize_picture_asset(
        source,
        declared_media_type="image/png",
        profile=DOCLING_LAYOUT_OCR_V1,
    )
    assert first.content == second.content
    assert first.content_sha256 == second.content_sha256
    assert first.media_type == "image/png"
    assert (first.width_pixels, first.height_pixels) == (12, 8)
    with Image.open(io.BytesIO(first.content)) as normalized:
        assert normalized.info == {}
        assert normalized.getexif().get(274) is None


def test_picture_normalization_applies_exif_orientation_before_hashing() -> None:
    normalized = normalize_picture_asset(
        _image_bytes(image_format="JPEG", size=(12, 8), orientation=6),
        declared_media_type="image/jpeg",
        profile=DOCLING_LAYOUT_OCR_V1,
    )
    assert (normalized.original_width_pixels, normalized.original_height_pixels) == (12, 8)
    assert (normalized.width_pixels, normalized.height_pixels) == (8, 12)
    assert normalized.exif_orientation == 6
    assert normalized.transform["normalized_size"] == [8, 12]
    assert set(normalized.transform) == {
        "version",
        "pixel_basis",
        "office_display_transform_applied",
        "source_origin",
        "target_origin",
        "exif_orientation",
        "original_size",
        "normalized_size",
    }
    assert normalized.transform["pixel_basis"] == "RAW_EMBEDDED_MEDIA_AFTER_EXIF"
    assert normalized.transform["office_display_transform_applied"] is False


def test_picture_normalization_rejects_media_mismatch_and_hard_limits() -> None:
    source = _image_bytes()
    with pytest.raises(DocumentProcessorFailure) as mismatch:
        normalize_picture_asset(
            source,
            declared_media_type="image/jpeg",
            profile=DOCLING_LAYOUT_OCR_V1,
        )
    assert mismatch.value.error_code == "docling_picture_media_type_invalid"

    maximum = int(
        DOCLING_LAYOUT_OCR_V1.layout_ocr_options["limits"]["max_picture_compressed_bytes"]
    )
    with pytest.raises(DocumentProcessorFailure) as compressed:
        normalize_picture_asset(
            b"x" * (maximum + 1),
            declared_media_type="image/png",
            profile=DOCLING_LAYOUT_OCR_V1,
        )
    assert compressed.value.error_code == "docling_picture_size_exceeded"

    total_limit = int(
        DOCLING_LAYOUT_OCR_V1.layout_ocr_options["limits"]["max_total_picture_pixels"]
    )
    with pytest.raises(DocumentProcessorFailure) as pixels:
        normalize_picture_asset(
            source,
            declared_media_type="image/png",
            profile=DOCLING_LAYOUT_OCR_V1,
            used_total_pixels=total_limit - 1,
        )
    assert pixels.value.error_code == "docling_picture_pixel_limit_exceeded"
