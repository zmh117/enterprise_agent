from __future__ import annotations

import codecs
import hashlib
from collections.abc import AsyncIterable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import BinaryIO, Never

from app.modules.file_workspace.domain import FileAction
from app.shared.exceptions import NonRetryableExecutionError


MAX_TEXT_BYTES = 15 * 1024 * 1024
UTF8_BOM = codecs.BOM_UTF8
UTF16_BOMS = (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)


class FileFormatPolicyVersion(StrEnum):
    TEXT_V1 = "text-v1"
    TEXT_V2 = "text-v2"


class TextFormatCode(StrEnum):
    TXT = "TXT"
    LOG = "LOG"
    MARKDOWN = "MARKDOWN"


@dataclass(frozen=True, slots=True)
class TextFormatDefinition:
    code: TextFormatCode
    extension: str
    accepted_media_types: frozenset[str]
    canonical_media_type: str
    actions: frozenset[FileAction]

    @property
    def writable(self) -> bool:
        return FileAction.COMMIT in self.actions


@dataclass(frozen=True, slots=True)
class TextFormatPolicy:
    version: FileFormatPolicyVersion
    formats: tuple[TextFormatDefinition, ...]

    def by_code(self, code: str | TextFormatCode) -> TextFormatDefinition:
        try:
            normalized = TextFormatCode(str(code))
        except ValueError as exc:
            _deny("file_format_unknown", "文件格式不受支持", cause=exc)
        for definition in self.formats:
            if definition.code is normalized:
                return definition
        _deny("file_format_policy_denied", "当前发布版本不支持此文件格式")

    def for_name(self, display_name: str) -> TextFormatDefinition:
        if (
            not display_name
            or "/" in display_name
            or "\\" in display_name
            or "\x00" in display_name
        ):
            _deny("file_name_invalid", "文件名无效")
        suffix = Path(display_name).suffix.lower()
        for definition in self.formats:
            if definition.extension == suffix:
                return definition
        _deny("file_type_unsupported", "当前文件格式策略不支持此文件")


_FULL_ACTIONS = frozenset(
    {
        FileAction.READ_METADATA,
        FileAction.MATERIALIZE,
        FileAction.EDIT,
        FileAction.COMMIT,
        FileAction.RETAIN,
        FileAction.DELIVER,
    }
)
_READ_ONLY_ACTIONS = frozenset(
    {
        FileAction.READ_METADATA,
        FileAction.MATERIALIZE,
        FileAction.RETAIN,
        FileAction.DELIVER,
    }
)
_TXT = TextFormatDefinition(
    code=TextFormatCode.TXT,
    extension=".txt",
    accepted_media_types=frozenset({"text/plain"}),
    canonical_media_type="text/plain",
    actions=_FULL_ACTIONS,
)
_LOG = TextFormatDefinition(
    code=TextFormatCode.LOG,
    extension=".log",
    accepted_media_types=frozenset({"text/plain", "application/octet-stream"}),
    canonical_media_type="text/plain",
    actions=_READ_ONLY_ACTIONS,
)
_MARKDOWN = TextFormatDefinition(
    code=TextFormatCode.MARKDOWN,
    extension=".md",
    accepted_media_types=frozenset({"text/markdown", "text/plain"}),
    canonical_media_type="text/markdown",
    actions=_FULL_ACTIONS,
)

FORMAT_POLICIES: dict[FileFormatPolicyVersion, TextFormatPolicy] = {
    FileFormatPolicyVersion.TEXT_V1: TextFormatPolicy(
        version=FileFormatPolicyVersion.TEXT_V1,
        formats=(_TXT,),
    ),
    FileFormatPolicyVersion.TEXT_V2: TextFormatPolicy(
        version=FileFormatPolicyVersion.TEXT_V2,
        formats=(_TXT, _LOG, _MARKDOWN),
    ),
}


def normalize_file_format_policy_version(
    value: object,
    *,
    default: FileFormatPolicyVersion = FileFormatPolicyVersion.TEXT_V1,
) -> FileFormatPolicyVersion:
    normalized = str(value or default.value).strip().lower()
    try:
        return FileFormatPolicyVersion(normalized)
    except ValueError as exc:
        _deny("file_format_policy_unknown", "文件格式策略版本不受支持", cause=exc)


def get_text_format_policy(value: object) -> TextFormatPolicy:
    return FORMAT_POLICIES[normalize_file_format_policy_version(value)]


def text_format_for_name(
    display_name: str,
    *,
    policy_version: object,
) -> TextFormatDefinition:
    return get_text_format_policy(policy_version).for_name(display_name)


def validate_format_action(
    *,
    policy_version: object,
    format_code: str | TextFormatCode,
    action: FileAction,
) -> TextFormatDefinition:
    definition = get_text_format_policy(policy_version).by_code(format_code)
    if action not in definition.actions:
        _deny("file_format_read_only", "此文件格式只允许读取和发送")
    return definition


def policy_runtime_protocol_version(policy_version: object) -> str:
    version = normalize_file_format_policy_version(policy_version)
    return "1.3" if version is FileFormatPolicyVersion.TEXT_V2 else "1.2"


@dataclass(frozen=True, slots=True)
class TextValidationResult:
    size_bytes: int
    content_sha256: str
    had_utf8_bom: bool
    format_code: TextFormatCode
    media_type: str
    encoding: str = "utf-8"


class TextStreamValidator:
    def __init__(self, *, max_bytes: int = MAX_TEXT_BYTES) -> None:
        if not 1 <= max_bytes <= MAX_TEXT_BYTES:
            raise ValueError("Text stream limit is invalid")
        self.max_bytes = max_bytes

    def validate_and_copy(
        self,
        chunks: Iterable[bytes],
        destination: BinaryIO,
        *,
        display_name: str,
        media_type: str,
        agent_output: bool,
        policy_version: object = FileFormatPolicyVersion.TEXT_V1,
        expected_format: str | TextFormatCode | None = None,
    ) -> TextValidationResult:
        definition = self._require_metadata(
            display_name=display_name,
            media_type=media_type,
            policy_version=policy_version,
            expected_format=expected_format,
            agent_output=agent_output,
        )
        return self._copy(
            chunks,
            destination,
            definition=definition,
            agent_output=agent_output,
        )

    async def validate_and_copy_async(
        self,
        chunks: AsyncIterable[bytes],
        destination: BinaryIO,
        *,
        display_name: str,
        media_type: str,
        agent_output: bool,
        policy_version: object = FileFormatPolicyVersion.TEXT_V1,
        expected_format: str | TextFormatCode | None = None,
    ) -> TextValidationResult:
        definition = self._require_metadata(
            display_name=display_name,
            media_type=media_type,
            policy_version=policy_version,
            expected_format=expected_format,
            agent_output=agent_output,
        )
        decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
        digest = hashlib.sha256()
        size = 0
        prefix = bytearray()
        try:
            async for chunk in chunks:
                size = self._consume_chunk(
                    chunk,
                    destination=destination,
                    decoder=decoder,
                    digest=digest,
                    prefix=prefix,
                    size=size,
                    agent_output=agent_output,
                )
            self._finish(decoder, prefix=prefix, agent_output=agent_output)
        except UnicodeDecodeError as exc:
            _deny("file_encoding_invalid", "文件必须使用 UTF-8 编码", cause=exc)
        return TextValidationResult(
            size,
            digest.hexdigest(),
            bytes(prefix[:3]) == UTF8_BOM,
            definition.code,
            definition.canonical_media_type,
        )

    def _copy(
        self,
        chunks: Iterable[bytes],
        destination: BinaryIO,
        *,
        definition: TextFormatDefinition,
        agent_output: bool,
    ) -> TextValidationResult:
        decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
        digest = hashlib.sha256()
        size = 0
        prefix = bytearray()
        try:
            for chunk in chunks:
                size = self._consume_chunk(
                    chunk,
                    destination=destination,
                    decoder=decoder,
                    digest=digest,
                    prefix=prefix,
                    size=size,
                    agent_output=agent_output,
                )
            self._finish(decoder, prefix=prefix, agent_output=agent_output)
        except UnicodeDecodeError as exc:
            _deny("file_encoding_invalid", "文件必须使用 UTF-8 编码", cause=exc)
        return TextValidationResult(
            size,
            digest.hexdigest(),
            bytes(prefix[:3]) == UTF8_BOM,
            definition.code,
            definition.canonical_media_type,
        )

    def _consume_chunk(
        self,
        chunk: bytes,
        *,
        destination: BinaryIO,
        decoder: codecs.IncrementalDecoder,
        digest: hashlib._Hash,
        prefix: bytearray,
        size: int,
        agent_output: bool,
    ) -> int:
        if not isinstance(chunk, bytes):
            _deny("file_stream_invalid", "文件流无效")
        if not chunk:
            return size
        next_size = size + len(chunk)
        if next_size > self.max_bytes:
            _deny("file_too_large", "文本文件不能超过 15 MiB")
        if len(prefix) < 3:
            prefix.extend(chunk[: 3 - len(prefix)])
            if len(prefix) >= 2 and bytes(prefix[:2]) in UTF16_BOMS:
                _deny("file_encoding_invalid", "文件必须使用 UTF-8 编码")
            if agent_output and len(prefix) >= 3 and bytes(prefix[:3]) == UTF8_BOM:
                _deny("file_output_bom_forbidden", "Agent 输出必须使用无 BOM UTF-8")
        decoded = decoder.decode(chunk, final=False)
        if "\x00" in decoded:
            _deny("file_type_invalid", "文件包含二进制内容")
        digest.update(chunk)
        destination.write(chunk)
        return next_size

    @staticmethod
    def _finish(
        decoder: codecs.IncrementalDecoder,
        *,
        prefix: bytearray,
        agent_output: bool,
    ) -> None:
        tail = decoder.decode(b"", final=True)
        if "\x00" in tail:
            _deny("file_type_invalid", "文件包含二进制内容")
        if agent_output and bytes(prefix[:3]) == UTF8_BOM:
            _deny("file_output_bom_forbidden", "Agent 输出必须使用无 BOM UTF-8")

    @staticmethod
    def _require_metadata(
        *,
        display_name: str,
        media_type: str,
        policy_version: object,
        expected_format: str | TextFormatCode | None,
        agent_output: bool,
    ) -> TextFormatDefinition:
        definition = text_format_for_name(display_name, policy_version=policy_version)
        normalized_media_type = media_type.split(";", 1)[0].strip().lower()
        if normalized_media_type not in definition.accepted_media_types:
            _deny("file_mime_invalid", "文件扩展名与 MIME 类型不一致")
        if expected_format is not None and definition.code is not TextFormatCode(
            str(expected_format)
        ):
            _deny("file_format_mismatch", "文件格式与冻结元数据不一致")
        if agent_output and not definition.writable:
            _deny("file_format_read_only", "此文件格式只允许读取和发送")
        return definition


def _deny(code: str, message: str, *, cause: Exception | None = None) -> Never:
    error = NonRetryableExecutionError(
        "Text file policy validation failed",
        safe_message=message,
        error_code=code,
    )
    if cause is None:
        raise error
    raise error from cause
