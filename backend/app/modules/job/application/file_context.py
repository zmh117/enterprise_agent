from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Literal

FileCapability = Literal["METADATA", "ORIGINAL", "READABLE_CONTENT"]
BindReason = Literal[
    "CURRENT_MESSAGE",
    "EXPLICIT_REFERENCE",
    "QUOTE",
    "FILENAME",
    "DEIXIS",
]
GateAction = Literal["enqueue_job", "wait_source", "system_notice"]

DEIXIS_PATTERNS: tuple[str, ...] = (
    "这个文件",
    "这份文件",
    "该文件",
    "刚才那个文件",
    "刚才那个",
    "刚才的文件",
    "刚才那份",
    "上面的附件",
    "这个附件",
    "这份附件",
    "这张图",
    "这张图片",
    "这个表",
    "这张表",
    "该文档",
    "这份文档",
    "这个文档",
)

PLURAL_DEIXIS_PATTERNS: tuple[str, ...] = (
    "这些文件",
    "这几个文件",
    "那几个文件",
    "几个文件",
    "多份文件",
    "这些附件",
    "刚才那些",
)

METADATA_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"叫什么",
        r"文件名",
        r"什么格式",
        r"什么类型",
        r"多大",
        r"多少\s*(mb|mi?b|kb)",
        r"上传时间",
        r"何时上传",
        r"什么时候(传|上传)",
        r"file\s*name",
        r"how\s+big",
        r"what\s+format",
    )
)

ORIGINAL_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"原文件",
        r"原件",
        r"转发原",
        r"下载原",
        r"把.{0,12}(原文件|原件|原pdf|原docx).{0,12}(发|给)",
        r"send\s+(me\s+)?the\s+original",
        r"forward\s+the\s+original",
        r"download\s+the\s+original",
    )
)

SOURCE_TERMINAL = frozenset({"READY", "REJECTED", "FAILED", "stored_not_interpreted"})
READABLE_READY = frozenset({"AVAILABLE", "PARTIAL", "NOT_REQUIRED"})
READABLE_FAILED = frozenset({"NO_TEXT", "UNAVAILABLE"})


@dataclass(frozen=True, slots=True)
class WorkspaceFileCandidate:
    file_id: str
    version_id: str
    display_name: str
    attachment_id: str = ""
    message_external_id: str = ""
    source_status: str = ""
    readability_status: str = "NOT_REQUIRED"
    source_ready_at: str | None = None


@dataclass(frozen=True, slots=True)
class CurrentMessageAttachment:
    file_name: str
    ordinal: int


@dataclass(frozen=True, slots=True)
class FileDependency:
    required_capability: FileCapability
    reason: BindReason
    file_id: str = ""
    version_id: str = ""
    attachment_id: str = ""
    display_name: str = ""
    source_status: str = ""
    readability_status: str = "NOT_REQUIRED"


@dataclass(frozen=True, slots=True)
class ResolverDecision:
    dependencies: tuple[FileDependency, ...]
    ambiguous: bool = False
    clarification_names: tuple[str, ...] = ()
    quote_unresolved: bool = False


@dataclass(frozen=True, slots=True)
class GateDecision:
    action: GateAction
    reason_code: str
    notice_kind: str = ""
    dependencies: tuple[FileDependency, ...] = ()


def normalize_display_name(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold().strip()


def infer_capability(text: str) -> FileCapability:
    if any(pattern.search(text) for pattern in ORIGINAL_PATTERNS):
        return "ORIGINAL"
    if any(pattern.search(text) for pattern in METADATA_PATTERNS):
        return "METADATA"
    return "READABLE_CONTENT"


def has_deixis(text: str) -> bool:
    return any(token in text for token in DEIXIS_PATTERNS)


def has_plural_deixis(text: str) -> bool:
    return any(token in text for token in PLURAL_DEIXIS_PATTERNS)


def resolve_file_context(
    *,
    text: str,
    current_attachments: tuple[CurrentMessageAttachment, ...] = (),
    explicit_references: tuple[tuple[str, str], ...] = (),
    quoted_external_message_id: str = "",
    candidates: tuple[WorkspaceFileCandidate, ...] = (),
) -> ResolverDecision:
    capability = infer_capability(text)
    if current_attachments:
        return ResolverDecision(
            dependencies=tuple(
                FileDependency(
                    required_capability=capability,
                    reason="CURRENT_MESSAGE",
                    display_name=item.file_name,
                    attachment_id=f"current:{item.ordinal}",
                    source_status="PENDING",
                    readability_status="PENDING",
                )
                for item in current_attachments
            )
        )

    if explicit_references:
        bound: list[FileDependency] = []
        by_identity = {
            (item.file_id, item.version_id): item for item in candidates if item.file_id
        }
        for file_id, version_id in explicit_references:
            match = by_identity.get((file_id, version_id))
            if match is None:
                bound.append(
                    FileDependency(
                        file_id=file_id,
                        version_id=version_id,
                        required_capability=capability,
                        reason="EXPLICIT_REFERENCE",
                    )
                )
                continue
            bound.append(_dependency_from_candidate(match, capability, "EXPLICIT_REFERENCE"))
        return ResolverDecision(dependencies=tuple(bound))

    skip_deixis = False
    if quoted_external_message_id:
        quoted = tuple(
            item
            for item in candidates
            if item.message_external_id == quoted_external_message_id
        )
        if quoted:
            return ResolverDecision(
                dependencies=tuple(
                    _dependency_from_candidate(item, capability, "QUOTE") for item in quoted
                )
            )
        skip_deixis = True

    filename_hits = _unique_filename_hits(text, candidates)
    if filename_hits == "ambiguous":
        names = tuple(
            sorted({item.display_name for item in candidates if _name_mentioned(text, item)})
        )
        return ResolverDecision(
            dependencies=(),
            ambiguous=True,
            clarification_names=names,
        )
    if filename_hits:
        return ResolverDecision(
            dependencies=tuple(
                _dependency_from_candidate(item, capability, "FILENAME")
                for item in filename_hits
            )
        )

    if skip_deixis:
        return ResolverDecision(dependencies=(), quote_unresolved=True)
    if has_plural_deixis(text):
        pool = [item for item in candidates if item.source_status in SOURCE_TERMINAL]
        if not pool:
            pool = list(candidates)
        if len(pool) > 1:
            return ResolverDecision(
                dependencies=(),
                ambiguous=True,
                clarification_names=tuple(sorted({item.display_name for item in pool})),
            )
    if not has_deixis(text) and not has_plural_deixis(text):
        return ResolverDecision(dependencies=())

    ready = [item for item in candidates if item.source_status in SOURCE_TERMINAL]
    if not ready:
        ready = list(candidates)
    if len(ready) == 1:
        return ResolverDecision(
            dependencies=(_dependency_from_candidate(ready[0], capability, "DEIXIS"),)
        )
    latest = max(
        (item.source_ready_at or "" for item in ready),
        default="",
    )
    winners = [
        item
        for item in ready
        if (item.source_ready_at or "") == latest and latest
    ]
    if len(winners) != 1:
        return ResolverDecision(
            dependencies=(),
            ambiguous=True,
            clarification_names=tuple(sorted({item.display_name for item in ready})),
        )
    return ResolverDecision(
        dependencies=(_dependency_from_candidate(winners[0], capability, "DEIXIS"),)
    )


def evaluate_file_gate(decision: ResolverDecision) -> GateDecision:
    if decision.ambiguous:
        return GateDecision(
            action="system_notice",
            reason_code="file_binding_ambiguous",
            notice_kind="ambiguous",
            dependencies=(),
        )
    if not decision.dependencies:
        return GateDecision(action="enqueue_job", reason_code="no_file_dependency")

    waiting_source: list[FileDependency] = []
    not_ready: list[FileDependency] = []
    failed: list[FileDependency] = []
    for item in decision.dependencies:
        if _source_pending(item):
            waiting_source.append(item)
            continue
        if item.source_status in {"REJECTED", "FAILED"}:
            failed.append(item)
            continue
        if item.required_capability in {"METADATA", "ORIGINAL"}:
            continue
        if item.readability_status in READABLE_FAILED:
            failed.append(item)
        elif item.readability_status not in READABLE_READY:
            not_ready.append(item)

    if waiting_source:
        return GateDecision(
            action="wait_source",
            reason_code="file_source_pending",
            dependencies=decision.dependencies,
        )
    if failed:
        return GateDecision(
            action="system_notice",
            reason_code="file_processing_failed",
            notice_kind="failed",
            dependencies=tuple(failed),
        )
    if not_ready:
        return GateDecision(
            action="system_notice",
            reason_code="file_readable_content_not_ready",
            notice_kind="pending",
            dependencies=tuple(not_ready),
        )
    return GateDecision(
        action="enqueue_job",
        reason_code="file_capability_ready",
        dependencies=decision.dependencies,
    )


def system_notice_markdown(
    *,
    notice_kind: str,
    display_names: tuple[str, ...],
) -> tuple[str, str]:
    names = "、".join(_safe_file_name(name) for name in display_names if name) or "该文件"
    if notice_kind == "pending":
        return (
            "文件尚未可阅读",
            f"《{names}》原件已保存，正在生成可读内容，当前还不能基于该文件回答。其他问题可以继续发送。",
        )
    if notice_kind == "failed":
        return (
            "文件尚未可阅读",
            f"《{names}》原件已保存，但可读内容生成失败。请更换文件或稍后再试。其他问题可以继续发送。",
        )
    if notice_kind == "ambiguous":
        listed = "、".join(_safe_file_name(name) for name in display_names) or "多份文件"
        return (
            "请指明要使用的文件",
            f"工作区里有多份可能相关的文件（{listed}）。请回复具体文件、引用那条文件消息，或写出完整文件名。",
        )
    if notice_kind == "ready":
        return (
            "文件已可继续提问",
            f"《{names}》可读内容已经生成，现在可以继续提问。",
        )
    return ("文件尚未可阅读", "当前还不能基于该文件回答。其他问题可以继续发送。")


def _dependency_from_candidate(
    item: WorkspaceFileCandidate,
    capability: FileCapability,
    reason: BindReason,
) -> FileDependency:
    return FileDependency(
        file_id=item.file_id,
        version_id=item.version_id,
        attachment_id=item.attachment_id,
        display_name=item.display_name,
        required_capability=capability,
        reason=reason,
        source_status=item.source_status,
        readability_status=item.readability_status,
    )


def _unique_filename_hits(
    text: str,
    candidates: tuple[WorkspaceFileCandidate, ...],
) -> tuple[WorkspaceFileCandidate, ...] | Literal["ambiguous"] | tuple[()]:
    mentioned = [item for item in candidates if _name_mentioned(text, item)]
    if not mentioned:
        return ()
    unique: dict[tuple[str, str], WorkspaceFileCandidate] = {}
    for item in mentioned:
        key = (item.file_id, item.version_id or item.attachment_id)
        previous = unique.get(key)
        if previous is None or (not previous.attachment_id and item.attachment_id):
            unique[key] = item
    collapsed = tuple(unique.values())
    identities = {(item.file_id, item.version_id) for item in collapsed}
    names = {normalize_display_name(item.display_name) for item in collapsed}
    if len(identities) > 1 and len(names) == 1:
        return "ambiguous"
    return collapsed


def _name_mentioned(text: str, item: WorkspaceFileCandidate) -> bool:
    needle = normalize_display_name(item.display_name)
    if not needle or "." not in needle:
        return False
    return needle in normalize_display_name(text)


def _safe_file_name(value: str) -> str:
    cleaned = re.sub(r"[\r\n`]+", " ", value).strip()
    return cleaned[:80] or "文件"


def _source_pending(item: FileDependency) -> bool:
    if item.source_status in {"PENDING", "DOWNLOADING", "EXTRACTING"}:
        return True
    return item.reason == "CURRENT_MESSAGE" and item.source_status not in SOURCE_TERMINAL


def file_dependency_payload(item: FileDependency) -> dict[str, str]:
    return {
        "file_id": item.file_id,
        "version_id": item.version_id,
        "attachment_id": item.attachment_id,
        "display_name": item.display_name,
        "required_capability": item.required_capability,
        "reason": item.reason,
        "source_status": item.source_status,
        "readability_status": item.readability_status,
    }


def file_dependency_from_payload(value: dict[str, object]) -> FileDependency:
    capability = str(value.get("required_capability") or "READABLE_CONTENT")
    reason = str(value.get("reason") or "FILENAME")
    if capability not in {"METADATA", "ORIGINAL", "READABLE_CONTENT"}:
        capability = "READABLE_CONTENT"
    if reason not in {"CURRENT_MESSAGE", "EXPLICIT_REFERENCE", "QUOTE", "FILENAME", "DEIXIS"}:
        reason = "FILENAME"
    return FileDependency(
        required_capability=capability,  # type: ignore[arg-type]
        reason=reason,  # type: ignore[arg-type]
        file_id=str(value.get("file_id") or ""),
        version_id=str(value.get("version_id") or ""),
        attachment_id=str(value.get("attachment_id") or ""),
        display_name=str(value.get("display_name") or ""),
        source_status=str(value.get("source_status") or ""),
        readability_status=str(value.get("readability_status") or "NOT_REQUIRED"),
    )
