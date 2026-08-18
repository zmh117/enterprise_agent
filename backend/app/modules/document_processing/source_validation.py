from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader

from app.modules.document_processing.profile import (
    DOCLING_TEXT_V1,
    DocumentSourceDefinition,
    DocumentSourceFormatCode,
)
from app.shared.exceptions import NonRetryableExecutionError


@dataclass(frozen=True, slots=True)
class ValidatedDocumentSource:
    format_code: DocumentSourceFormatCode
    media_type: str
    size_bytes: int
    page_count: int | None


def validate_document_source(
    stream: BinaryIO,
    *,
    display_name: str,
    declared_media_type: str,
    declared_size_bytes: int,
) -> ValidatedDocumentSource:
    if declared_size_bytes < 1 or declared_size_bytes > DOCLING_TEXT_V1.max_source_bytes:
        _reject("document_source_size_exceeded", "文档原件大小必须在 1 字节到 25 MiB 之间")
    extension = Path(display_name).suffix.lower()
    definition = next(
        (item for item in DOCLING_TEXT_V1.source_formats if extension in item.extensions),
        None,
    )
    if definition is None:
        _reject("document_source_format_unsupported", "文档原件格式不受支持")
    assert definition is not None
    normalized_media_type = declared_media_type.split(";", 1)[0].strip().lower()
    if normalized_media_type not in definition.accepted_media_types:
        _reject("document_source_media_type_mismatch", "文件扩展名与媒体类型不一致")
    actual_size = _stream_size(stream)
    if actual_size != declared_size_bytes:
        _reject("document_source_size_mismatch", "文件大小声明不一致")
    stream.seek(0)
    page_count: int | None = None
    if definition.code is DocumentSourceFormatCode.PDF:
        page_count = _validate_pdf(stream)
    elif definition.code in {
        DocumentSourceFormatCode.DOCX,
        DocumentSourceFormatCode.PPTX,
        DocumentSourceFormatCode.XLSX,
    }:
        _validate_ooxml(stream, definition)
    else:
        _validate_image(stream, definition)
    stream.seek(0)
    return ValidatedDocumentSource(
        format_code=definition.code,
        media_type=definition.canonical_media_type,
        size_bytes=actual_size,
        page_count=page_count,
    )


def _stream_size(stream: BinaryIO) -> int:
    current = stream.tell()
    stream.seek(0, 2)
    size = stream.tell()
    stream.seek(current)
    return size


def _validate_pdf(stream: BinaryIO) -> int:
    if stream.read(5) != b"%PDF-":
        _reject("document_source_signature_mismatch", "PDF 文件签名无效")
    stream.seek(0)
    try:
        reader = PdfReader(stream, strict=True)
        if reader.is_encrypted:
            _reject("document_source_encrypted", "暂不支持加密 PDF")
        page_count = len(reader.pages)
    except NonRetryableExecutionError:
        raise
    except Exception as exc:
        raise _error("document_source_malformed", "PDF 文件结构无效") from exc
    if page_count < 1:
        _reject("document_source_empty", "PDF 不包含页面")
    if page_count > DOCLING_TEXT_V1.max_pdf_pages:
        _reject("document_source_page_limit_exceeded", "PDF 页数超过 300 页上限")
    return page_count


def _validate_ooxml(stream: BinaryIO, definition: DocumentSourceDefinition) -> None:
    required_part = {
        DocumentSourceFormatCode.DOCX: "word/document.xml",
        DocumentSourceFormatCode.PPTX: "ppt/presentation.xml",
        DocumentSourceFormatCode.XLSX: "xl/workbook.xml",
    }[definition.code]
    try:
        with zipfile.ZipFile(stream) as archive:
            infos = archive.infolist()
            names = {item.filename for item in infos}
            if len(infos) > 20_000 or sum(item.file_size for item in infos) > 200 * 1024 * 1024:
                _reject("document_source_archive_limit_exceeded", "Office 文档展开规模超限")
            if "[Content_Types].xml" not in names or required_part not in names:
                _reject("document_source_signature_mismatch", "Office 文件结构与扩展名不一致")
            if any(name.lower().endswith("vbaproject.bin") for name in names):
                _reject("document_source_macro_unsupported", "暂不支持含宏的 Office 文档")
            if archive.testzip() is not None:
                _reject("document_source_malformed", "Office 文件压缩结构损坏")
    except NonRetryableExecutionError:
        raise
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        raise _error("document_source_malformed", "Office 文件结构无效") from exc


def _validate_image(stream: BinaryIO, definition: DocumentSourceDefinition) -> None:
    expected = {
        DocumentSourceFormatCode.PNG: "PNG",
        DocumentSourceFormatCode.JPEG: "JPEG",
        DocumentSourceFormatCode.WEBP: "WEBP",
    }[definition.code]
    try:
        with Image.open(stream) as image:
            if image.format != expected:
                _reject("document_source_signature_mismatch", "图片内容与扩展名不一致")
            image.verify()
    except NonRetryableExecutionError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise _error("document_source_malformed", "图片文件结构无效") from exc


def _error(code: str, safe_message: str) -> NonRetryableExecutionError:
    return NonRetryableExecutionError(
        "Document source validation failed",
        safe_message=safe_message,
        error_code=code,
    )


def _reject(code: str, safe_message: str) -> None:
    raise _error(code, safe_message)
