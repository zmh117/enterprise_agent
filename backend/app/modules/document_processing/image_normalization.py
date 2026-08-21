from __future__ import annotations

import hashlib
import io
import warnings
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

from app.modules.document_processing.profile import (
    DOCLING_LAYOUT_OCR_V1,
    DocumentProcessingProfile,
)
from app.modules.document_processing.provider import DocumentProcessorFailure


@dataclass(frozen=True, slots=True)
class NormalizedPicture:
    content: bytes
    media_type: str
    content_sha256: str
    original_width_pixels: int
    original_height_pixels: int
    width_pixels: int
    height_pixels: int
    exif_orientation: int
    transform: dict[str, Any]


def normalize_picture_asset(
    content: bytes,
    *,
    declared_media_type: str,
    profile: DocumentProcessingProfile,
    used_total_pixels: int = 0,
    used_derived_bytes: int = 0,
) -> NormalizedPicture:
    if profile.profile_hash != DOCLING_LAYOUT_OCR_V1.profile_hash:
        raise DocumentProcessorFailure("document_profile_mismatch", retryable=False)
    if profile.layout_ocr_options is None:
        raise DocumentProcessorFailure("document_profile_mismatch", retryable=False)
    limits = profile.layout_ocr_options["limits"]
    if declared_media_type not in {"image/png", "image/jpeg", "image/webp"}:
        raise DocumentProcessorFailure("docling_picture_media_type_invalid", retryable=False)
    if not 1 <= len(content) <= int(limits["max_picture_compressed_bytes"]):
        raise DocumentProcessorFailure("docling_picture_size_exceeded", retryable=False)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                expected_format = {
                    "image/png": "PNG",
                    "image/jpeg": "JPEG",
                    "image/webp": "WEBP",
                }[declared_media_type]
                if image.format != expected_format or int(getattr(image, "n_frames", 1)) != 1:
                    raise DocumentProcessorFailure(
                        "docling_picture_media_type_invalid", retryable=False
                    )
                original_width, original_height = image.size
                pixels = original_width * original_height
                if (
                    original_width < 1
                    or original_height < 1
                    or pixels > int(limits["max_picture_pixels"])
                    or used_total_pixels + pixels > int(limits["max_total_picture_pixels"])
                ):
                    raise DocumentProcessorFailure("docling_picture_pixel_limit_exceeded", retryable=False)
                orientation = int(image.getexif().get(274, 1) or 1)
                if orientation not in range(1, 9):
                    raise DocumentProcessorFailure(
                        "docling_picture_transform_invalid", retryable=False
                    )
                image.load()
                normalized = ImageOps.exif_transpose(image)
                normalized = normalized.convert(
                    "RGBA" if "A" in normalized.getbands() else "RGB"
                )
                width, height = normalized.size
                output = io.BytesIO()
                normalized.save(output, format="PNG", optimize=False, compress_level=6)
    except DocumentProcessorFailure:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise DocumentProcessorFailure("docling_picture_pixel_limit_exceeded", retryable=False) from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise DocumentProcessorFailure("docling_picture_decode_failed", retryable=False) from exc
    normalized_content = output.getvalue()
    if used_derived_bytes + len(normalized_content) > int(limits["max_derived_bytes"]):
        raise DocumentProcessorFailure("docling_derived_size_exceeded", retryable=False)
    return NormalizedPicture(
        content=normalized_content,
        media_type="image/png",
        content_sha256=hashlib.sha256(normalized_content).hexdigest(),
        original_width_pixels=original_width,
        original_height_pixels=original_height,
        width_pixels=width,
        height_pixels=height,
        exif_orientation=orientation,
        transform={
            "version": "exif-orientation/v1",
            "source_origin": "TOPLEFT",
            "target_origin": "TOPLEFT",
            "exif_orientation": orientation,
            "original_size": [original_width, original_height],
            "normalized_size": [width, height],
        },
    )
