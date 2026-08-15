from __future__ import annotations

import codecs
import hashlib
from collections.abc import AsyncIterable, Iterable
from dataclasses import dataclass
from typing import BinaryIO

from app.shared.exceptions import NonRetryableExecutionError


MAX_TXT_BYTES = 15 * 1024 * 1024
UTF8_BOM = codecs.BOM_UTF8
UTF16_BOMS = (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)


@dataclass(frozen=True, slots=True)
class TxtValidationResult:
    size_bytes: int
    content_sha256: str
    had_utf8_bom: bool
    media_type: str = "text/plain"
    encoding: str = "utf-8"


class TxtStreamValidator:
    def __init__(self, *, max_bytes: int = MAX_TXT_BYTES) -> None:
        if not 1 <= max_bytes <= MAX_TXT_BYTES:
            raise ValueError("TXT stream limit is invalid")
        self.max_bytes = max_bytes

    def validate_and_copy(
        self,
        chunks: Iterable[bytes],
        destination: BinaryIO,
        *,
        display_name: str,
        media_type: str,
        agent_output: bool,
    ) -> TxtValidationResult:
        if (
            not display_name
            or not display_name.lower().endswith(".txt")
            or "/" in display_name
            or "\\" in display_name
            or media_type.split(";", 1)[0].strip().lower() != "text/plain"
        ):
            self._deny("file_type_unsupported", "第一阶段只支持 UTF-8 TXT 文件")
        decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
        digest = hashlib.sha256()
        size = 0
        prefix = bytearray()
        had_bom = False
        first = True
        try:
            for chunk in chunks:
                if not isinstance(chunk, bytes):
                    self._deny("file_stream_invalid", "文件流无效")
                if not chunk:
                    continue
                size += len(chunk)
                if size > self.max_bytes:
                    self._deny("file_too_large", "TXT 文件不能超过 15 MiB")
                if first:
                    prefix.extend(chunk[:3])
                    if len(prefix) >= 2 and bytes(prefix[:2]) in UTF16_BOMS:
                        self._deny("file_encoding_invalid", "TXT 文件必须使用 UTF-8 编码")
                    if len(prefix) >= 3:
                        had_bom = bytes(prefix[:3]) == UTF8_BOM
                        if agent_output and had_bom:
                            self._deny(
                                "file_output_bom_forbidden",
                                "Agent 输出必须使用无 BOM UTF-8",
                            )
                        first = False
                decoded = decoder.decode(chunk, final=False)
                if "\x00" in decoded:
                    self._deny("file_type_invalid", "TXT 文件包含二进制内容")
                digest.update(chunk)
                destination.write(chunk)
            tail = decoder.decode(b"", final=True)
            if "\x00" in tail:
                self._deny("file_type_invalid", "TXT 文件包含二进制内容")
        except UnicodeDecodeError as exc:
            raise NonRetryableExecutionError(
                "TXT content is not valid UTF-8",
                safe_message="TXT 文件必须使用 UTF-8 编码",
                error_code="file_encoding_invalid",
            ) from exc
        if first:
            had_bom = bytes(prefix[:3]) == UTF8_BOM
            if agent_output and had_bom:
                self._deny("file_output_bom_forbidden", "Agent 输出必须使用无 BOM UTF-8")
        return TxtValidationResult(size, digest.hexdigest(), had_bom)

    async def validate_and_copy_async(
        self,
        chunks: AsyncIterable[bytes],
        destination: BinaryIO,
        *,
        display_name: str,
        media_type: str,
        agent_output: bool,
    ) -> TxtValidationResult:
        self._require_txt_metadata(display_name=display_name, media_type=media_type)
        decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
        digest = hashlib.sha256()
        size = 0
        prefix = bytearray()
        first = True
        try:
            async for chunk in chunks:
                if not isinstance(chunk, bytes):
                    self._deny("file_stream_invalid", "文件流无效")
                if not chunk:
                    continue
                size += len(chunk)
                if size > self.max_bytes:
                    self._deny("file_too_large", "TXT 文件不能超过 15 MiB")
                if first:
                    prefix.extend(chunk[:3])
                    if len(prefix) >= 2 and bytes(prefix[:2]) in UTF16_BOMS:
                        self._deny("file_encoding_invalid", "TXT 文件必须使用 UTF-8 编码")
                    if len(prefix) >= 3:
                        if agent_output and bytes(prefix[:3]) == UTF8_BOM:
                            self._deny(
                                "file_output_bom_forbidden",
                                "Agent 输出必须使用无 BOM UTF-8",
                            )
                        first = False
                decoded = decoder.decode(chunk, final=False)
                if "\x00" in decoded:
                    self._deny("file_type_invalid", "TXT 文件包含二进制内容")
                digest.update(chunk)
                destination.write(chunk)
            tail = decoder.decode(b"", final=True)
            if "\x00" in tail:
                self._deny("file_type_invalid", "TXT 文件包含二进制内容")
        except UnicodeDecodeError as exc:
            raise NonRetryableExecutionError(
                "TXT content is not valid UTF-8",
                safe_message="TXT 文件必须使用 UTF-8 编码",
                error_code="file_encoding_invalid",
            ) from exc
        had_bom = bytes(prefix[:3]) == UTF8_BOM
        if agent_output and had_bom:
            self._deny("file_output_bom_forbidden", "Agent 输出必须使用无 BOM UTF-8")
        return TxtValidationResult(size, digest.hexdigest(), had_bom)

    @staticmethod
    def _require_txt_metadata(*, display_name: str, media_type: str) -> None:
        if (
            not display_name
            or not display_name.lower().endswith(".txt")
            or "/" in display_name
            or "\\" in display_name
            or media_type.split(";", 1)[0].strip().lower() != "text/plain"
        ):
            TxtStreamValidator._deny(
                "file_type_unsupported", "第一阶段只支持 UTF-8 TXT 文件"
            )

    @staticmethod
    def _deny(code: str, message: str) -> None:
        raise NonRetryableExecutionError(
            "TXT validation failed",
            safe_message=message,
            error_code=code,
        )
