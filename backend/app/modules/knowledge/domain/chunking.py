"""确定性知识文本派生；不访问数据库、网络或模型。"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import asdict, dataclass
import re
from typing import Any

from app.modules.knowledge.domain.normalization import (
    NORMALIZER_VERSION,
    WORK_ITEM_NORMALIZER_VERSION,
    ExportValidationError,
    digest,
)
from app.modules.knowledge.domain.work_items import check_offline_type, document_kind
from app.modules.knowledge.domain.keep_ids import KEEP_IDS_NORMALIZER


@dataclass(frozen=True)
class ChunkProfile:
    version: str = "ones-text-chunks/v1"
    cleaner_version: str = "conservative-text/v1"
    template_version: str = "ones-context/v1"
    soft_chars: int = 900
    max_chars: int = 1200
    overlap_chars: int = 120
    context_chars: int = 550
    embedding_chars: int = 1800

    def validate(self) -> None:
        if not (
            0 <= self.overlap_chars < self.soft_chars <= self.max_chars <= 1200
            and 100 <= self.context_chars <= 550
            and self.max_chars + self.context_chars + 32 <= self.embedding_chars <= 1800
        ):
            raise ExportValidationError("knowledge_chunk_profile_invalid")

    @property
    def fingerprint(self) -> str:
        return digest(asdict(self))


DEFAULT_PROFILE = ChunkProfile()
WORK_ITEM_PROFILE = ChunkProfile(
    version="ones-work-item-chunks/v1", template_version="ones-work-item-context/v1"
)
KEEP_IDS_PROFILE = ChunkProfile(
    version="ones-keep-ids-hybrid-chunks/v1", template_version="ones-keep-ids-context/v1"
)


def profile_for_kind(kind: str) -> ChunkProfile:
    return DEFAULT_PROFILE if document_kind(kind) == "defect" else WORK_ITEM_PROFILE


CHUNK_VALUE_COLUMNS = (
    "ordinal",
    "chunk_kind",
    "source_field",
    "source_start",
    "source_end",
    "evidence_text",
    "embedding_text",
    "char_count",
    "embedding_char_count",
    "evidence_hash",
    "embedding_hash",
    "quality_flags",
)
_CONTROLS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufeff]")
_FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})[^\n]*$", re.MULTILINE)
_HEADING = re.compile(
    r"(?m)^(?:[ \t]*#{1,6}[ \t]+|[ \t]*(?:\d+[.、）)]|步骤|操作步骤|预期结果|实际结果|复现步骤))"
)
_PLACEHOLDERS = frozenset(
    {
        "已处理",
        "已修复",
        "已解决",
        "已关闭",
        "修复",
        "完成",
        "关闭",
        "无",
        "暂无",
        "待处理",
        "n/a",
        "null",
        "none",
        "-",
        "/",
    }
)


def clean_text(value: str) -> str:
    """只整理行结束符、控制字符和边缘空白行；不解析 HTML 或改写代码。"""
    result = _CONTROLS.sub("", value.replace("\r\n", "\n").replace("\r", "\n"))
    result = re.sub(r"\A(?:[ \t]*\n)+", "", result)
    return re.sub(r"(?:\n[ \t]*)+\Z", "", result)


def _fences(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    opened: tuple[int, str] | None = None
    for match in _FENCE.finditer(text):
        marker = match.group(1)
        if opened is None:
            opened = (match.start(), marker)
        elif marker[0] == opened[1][0] and len(marker) >= len(opened[1]):
            spans.append((opened[0], match.end()))
            opened = None
    if opened:
        spans.append((opened[0], len(text)))
    return spans


def _ranges(text: str, profile: ChunkProfile) -> list[tuple[int, int, list[str]]]:
    fences = _fences(text)
    protected = [(a, b) for a, b in fences if b - a <= profile.max_chars]
    paragraphs = sorted(
        {m.end() for m in re.finditer(r"\n[ \t]*\n", text)}
        | {m.start() for m in _HEADING.finditer(text)}
    )
    lines = [m.end() for m in re.finditer("\n", text)]
    sentences = [m.end() for m in re.finditer(r"[。！？；.!?;](?:[ \t]+|\n|$)", text)]

    def allowed(position: int) -> bool:
        return not any(a < position < b for a, b in protected)

    result: list[tuple[int, int, list[str]]] = []
    start = 0
    while start < len(text):
        limit = min(start + profile.max_chars, len(text))
        end = limit
        flags: list[str] = []
        if limit < len(text):
            selected = False
            for boundaries in (paragraphs, lines, sentences):
                left = bisect_left(boundaries, start + min(400, profile.soft_chars))
                right = bisect_left(boundaries, limit + 1)
                candidates = [p for p in boundaries[left:right] if allowed(p)]
                if candidates:
                    end = min(candidates, key=lambda p: (abs(p - start - profile.soft_chars), -p))
                    selected = True
                    break
            if not selected:
                # 小围栏即使靠近块开头也保持完整，不为了软目标从中间切开。
                enclosing = next(((a, b) for a, b in protected if a < limit < b), None)
                if enclosing and enclosing[0] > start:
                    end = enclosing[0]
                else:
                    flags.append("hard_split")
        if any(a < end < b or a < start < b for a, b in fences):
            flags.append("code_continuation")
        if text[start:end].strip():
            result.append((start, end, flags))
        if end == len(text):
            break
        next_start = max(start + 1, end - profile.overlap_chars)
        line_index = bisect_left(lines, next_start)
        if line_index < len(lines) and lines[line_index] <= end:
            next_start = lines[line_index]
        for a, b in protected:
            if a < next_start < b:
                next_start = min(b, end)
        start = next_start
    return result


def _context(
    record: dict[str, Any], body: str, kind: str, profile: ChunkProfile
) -> tuple[str, bool]:
    pieces: list[str] = []
    cropped = False

    def add(label: str, value: Any, budget: int) -> None:
        nonlocal cropped
        if isinstance(value, list):
            value = " / ".join(v for v in value if isinstance(v, str))
        if not isinstance(value, str):
            return
        text = " ".join(clean_text(value).split())
        if not text:
            return
        if len(text) > budget:
            text = text[: budget - 1] + "…"
            cropped = True
        pieces.append(f"{label}：{text}")

    if record.get("normalizer_version") in {WORK_ITEM_NORMALIZER_VERSION, KEEP_IDS_NORMALIZER}:
        add("类型", record["attributes"].get("source_issue_type_display"), 40)
    add("标题", record["title"], 200)
    if kind == "solution":
        add("问题片段", body, 180)
    add("项目", record.get("source_project_name"), 60)
    attrs = record["attributes"]
    for key, label in (
        ("product_names", "产品"),
        ("module_names", "模块"),
        ("environment_text", "环境"),
        ("affected_versions", "影响版本"),
        ("fixed_versions", "修复版本"),
    ):
        add(label, attrs.get(key), 80)
    result = "\n".join(pieces)
    if len(result) > profile.context_chars:
        result = result[: profile.context_chars - 1] + "…"
        cropped = True
    return result, cropped


@dataclass(frozen=True)
class PreparedChunks:
    normalized_fields: dict[str, str]
    quality: dict[str, Any]
    chunks: tuple[dict[str, Any], ...]

    @property
    def output_hash(self) -> str:
        return digest(asdict(self))


def prepare_chunks(record: dict[str, Any], profile: ChunkProfile | None = None) -> PreparedChunks:  # noqa: C901, PLR0915
    keep_ids = record.get("normalizer_version") == KEEP_IDS_NORMALIZER
    typed = keep_ids or record.get("normalizer_version") == WORK_ITEM_NORMALIZER_VERSION
    profile = profile or (
        KEEP_IDS_PROFILE if keep_ids else WORK_ITEM_PROFILE if typed else DEFAULT_PROFILE
    )
    profile.validate()
    if record.get("normalizer_version") not in {
        NORMALIZER_VERSION,
        WORK_ITEM_NORMALIZER_VERSION,
        KEEP_IDS_NORMALIZER,
    }:
        raise ExportValidationError("knowledge_chunk_source_profile_unsupported")
    if (
        not isinstance(record.get("body_text"), str)
        or not isinstance(record.get("title"), str)
        or not isinstance(record.get("attributes"), dict)
        or not isinstance(record.get("completeness"), dict)
    ):
        raise ExportValidationError("knowledge_chunk_source_invalid")
    if typed:
        kind = record["attributes"].get("document_kind")
        kinds = {"defect", "ticket", "requirement"} if keep_ids else {"ticket", "requirement"}
        if kind not in kinds or record.get("document_kind", kind) != kind:
            raise ExportValidationError("knowledge_chunk_kind_unsupported")
        check_offline_type(kind, record["attributes"].get("source_issue_type_display"))
        expected_profile = KEEP_IDS_PROFILE if keep_ids else WORK_ITEM_PROFILE
        if profile.template_version != expected_profile.template_version:
            raise ExportValidationError("knowledge_chunk_source_profile_unsupported")
    elif profile.template_version in {
        WORK_ITEM_PROFILE.template_version,
        KEEP_IDS_PROFILE.template_version,
    }:
        raise ExportValidationError("knowledge_chunk_source_profile_unsupported")
    if len(record["body_text"]) > 2 * 1024 * 1024:
        raise ExportValidationError("knowledge_chunk_source_limit")
    body = clean_text(record["body_text"])
    if not body.strip() and not typed:
        raise ExportValidationError("knowledge_chunk_body_empty")
    raw_solution = record["attributes"].get("solution_text")
    solution = clean_text(raw_solution) if isinstance(raw_solution, str) else ""
    if len(solution) > 2 * 1024 * 1024:
        raise ExportValidationError("knowledge_chunk_source_limit")
    solution_state = "included"
    if raw_solution is not None and not isinstance(raw_solution, str):
        solution_state = "unsupported_type"
    elif not solution.strip():
        solution_state = "absent"
    elif solution.strip().strip("。.!！ ").casefold() in _PLACEHOLDERS:
        solution_state = "status_only"
    elif solution == body:
        solution_state = "duplicates_body"
    fields = {"body_text": body, "attributes.solution_text": solution}
    base_flags: list[str] = []
    primary = "body_text"
    if typed and not body.strip():
        primary = "title"
        fields["title"] = clean_text(record["title"])
        if not fields["title"].strip():
            raise ExportValidationError("knowledge_chunk_source_invalid")
        base_flags.append("description_missing")
        if solution_state != "included":
            base_flags.append("title_only")
    completeness = record["completeness"]
    if completeness.get("inline_image_count", 0) > 0:
        base_flags.append("images_not_collected")
    if completeness.get("discussion_count", 0) > 0:
        base_flags.append("discussion_not_collected")
    if completeness.get("attachment_count", 0) > 0:
        base_flags.append("attachments_not_collected")
    chunks: list[dict[str, Any]] = []
    for field, kind in ((primary, "problem"), ("attributes.solution_text", "solution")):
        if kind == "solution" and solution_state != "included":
            continue
        context, cropped = _context(record, body, kind, profile)
        for start, end, flags in _ranges(fields[field], profile):
            evidence = fields[field][start:end]
            label = "问题证据" if kind == "problem" else "解决方案证据"
            if typed and kind == "problem":
                label = "标题证据" if field == "title" else "工作项描述证据"
            embedding = f"{context}\n{label}：\n{evidence}"
            chunks.append(
                {
                    "ordinal": len(chunks),
                    "chunk_kind": kind,
                    "source_field": field,
                    "source_start": start,
                    "source_end": end,
                    "evidence_text": evidence,
                    "embedding_text": embedding,
                    "char_count": len(evidence),
                    "embedding_char_count": len(embedding),
                    "evidence_hash": digest(evidence),
                    "embedding_hash": digest(embedding),
                    "quality_flags": sorted(
                        set(base_flags + flags + (["context_truncated"] if cropped else []))
                    ),
                }
            )
    prepared = PreparedChunks(
        fields,
        {
            "solution_state": solution_state,
            "body_normalized": body != record["body_text"],
            "solution_normalized": isinstance(raw_solution, str) and solution != raw_solution,
            "source_flags": base_flags,
        },
        tuple(chunks),
    )
    validate_chunks(prepared, profile)
    return prepared


def validate_chunks(prepared: PreparedChunks, profile: ChunkProfile = DEFAULT_PROFILE) -> None:
    def require(condition: bool) -> None:
        if not condition:
            raise ExportValidationError("knowledge_chunk_integrity_failed")

    fields = prepared.normalized_fields
    cursors = {key: 0 for key in fields}
    for ordinal, chunk in enumerate(prepared.chunks):
        field = chunk["source_field"]
        require(field in fields)
        start, end = chunk["source_start"], chunk["source_end"]
        require(chunk["ordinal"] == ordinal and 0 <= start < end <= len(fields[field]))
        require(start >= max(0, cursors[field] - profile.overlap_chars) and end > cursors[field])
        require(not fields[field][cursors[field] : start].strip())
        text = chunk["evidence_text"]
        require(bool(text.strip()) and text == fields[field][start:end])
        require(chunk["char_count"] == len(text) <= profile.max_chars)
        require(
            chunk["embedding_char_count"] == len(chunk["embedding_text"]) <= profile.embedding_chars
        )
        require(
            chunk["evidence_hash"] == digest(text)
            and chunk["embedding_hash"] == digest(chunk["embedding_text"])
        )
        require(chunk["embedding_text"].endswith(text))
        require(
            chunk["chunk_kind"] == ("problem" if field in {"body_text", "title"} else "solution")
        )
        cursors[field] = end
    require(bool(prepared.chunks))
    require(not fields["body_text"][cursors["body_text"] :].strip())
    if "title" in fields:
        require(not fields["title"][cursors["title"] :].strip())
    if prepared.quality["solution_state"] == "included":
        require(
            not fields["attributes.solution_text"][cursors["attributes.solution_text"] :].strip()
        )
