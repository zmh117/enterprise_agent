"""显式 ONES 离线导出契约，错误和统计不得携带业务正文。"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from typing import Any


NORMALIZER_VERSION = "ones-offline-text/v1"
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_ROW_BYTES = 2 * 1024 * 1024
MAX_RECORDS = 200_000
_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_SENSITIVE_KEY = re.compile(
    r"password|passwd|secret|token|cookie|authorization|api.?key|access.?key|密码|密钥",
    re.IGNORECASE,
)
_URL = re.compile(r"[a-z][a-z0-9+.-]*://[^\s<>\"']+", re.IGNORECASE)
_DATA_URI = re.compile(r"data:[^\s<>\"']+", re.IGNORECASE)
_CREDENTIAL_LINE = re.compile(
    r"^.*(?:\b[a-z0-9_]*(?:password|passwd|secret|token|api_key|access_key|cookie)"
    r"[a-z0-9_]*\b|authorization|密码|密钥)\s*[\"']?\s*[:=]\s*\S.*$",
    re.IGNORECASE | re.MULTILINE,
)
_BEARER = re.compile(r"\b(?:Bearer|Basic)\s+[A-Za-z0-9_+/=.-]+", re.IGNORECASE)
_PRIVATE_KEY = re.compile(
    r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----", re.DOTALL
)
_XML_SECRET = re.compile(
    r"<(password|passwd|secret|token|api_key|access_key)>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_SECRET_TOKEN = re.compile(
    r"\b(?:eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|"
    r"sk-[A-Za-z0-9_-]{16,}|AKIA[A-Z0-9]{16})\b"
)

FIELD_MAPPING = {
    "所属产品": "product_names", "所属功能模块": "module_names", "环境": "environment_text",
    "影响版本-MES": "affected_versions", "修复版本-MES": "fixed_versions",
    "验证版本-MES": "verified_versions", "解决方案": "solution_text",
    "缺陷产生原因": "cause_category", "影响面分析": "impact_text",
    "处理结果": "resolution_category", "严重程度": "severity",
    "优先级（任务内置）": "priority", "重现概率": "reproducibility",
    "是否线上缺陷": "is_production_label", "是否历史缺陷": "is_historical_label",
    "标签": "labels", "关闭时间": "closed_at_raw", "解决时间": "resolved_at_raw",
    "创建者": "creator_name", "负责人": "assignee_name", "解决者": "resolver_name",
    "所属人": "owner_names", "发现难易程度": "discovery_difficulty",
    "缺陷发现阶段": "discovery_stage", "紧急程度": "urgency", "Svn版本号": "svn_revision",
}
_DUPLICATE_FIELDS = {
    "标题", "描述", "描述富文本", "状态", "所属项目", "工作项类型", "所属迭代",
}


class ExportValidationError(ValueError):
    def __init__(self, code: str, line: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.line = line


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def identifier(value: Any) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ExportValidationError("knowledge_source_identifier_invalid")
    return value


class Sanitizer:
    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()

    def text(self, value: str) -> str:
        value = unescape(value).replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
        for code, pattern in (
            ("private_key", _PRIVATE_KEY), ("credential_xml", _XML_SECRET),
            ("credential_line", _CREDENTIAL_LINE), ("authorization", _BEARER),
            ("credential_token", _SECRET_TOKEN),
            ("url", _URL), ("inline_data", _DATA_URI),
        ):
            value, count = pattern.subn("[敏感内容已移除]", value)
            self.counts[code] += count
        # 验证可以安全进入 UTF-8 PostgreSQL，不输出非法输入片段。
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeError:
            raise ExportValidationError("knowledge_text_encoding_invalid") from None
        return value

    def value(self, value: Any, *, depth: int = 0) -> Any:
        if depth > 40:
            raise ExportValidationError("knowledge_json_too_deep")
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if _SENSITIVE_KEY.search(key):
                    self.counts["sensitive_field"] += 1
                    continue
                result[key] = self.value(item, depth=depth + 1)
            return result
        if isinstance(value, list):
            return [self.value(item, depth=depth + 1) for item in value]
        return self.text(value) if isinstance(value, str) else value


class RichText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.images: list[dict[str, Any]] = []
        self.ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.ignored += 1
        if self.ignored:
            return
        if tag in {"p", "div", "li", "br", "tr", "pre", "h1", "h2", "h3"}:
            self.parts.append("\n")
        if tag == "img":
            attributes = dict(attrs)
            raw_id = attributes.get("data-uuid") or ""
            source = attributes.get("src") or ""
            self.images.append({
                "occurrence_index": len(self.images),
                "source_attachment_id": raw_id if _IDENTIFIER.fullmatch(raw_id) else None,
                "source_kind": "inline_data" if source.startswith("data:") else "reference",
                "state": "not_collected",
                "anchor": {"field": "desc_rich", "text_offset": sum(map(len, self.parts))},
            })

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.ignored = max(0, self.ignored - 1)
        elif not self.ignored and tag in {"p", "div", "li", "tr", "pre"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.ignored:
            self.parts.append(data)


@dataclass(frozen=True)
class PreparedRecord:
    external_id: str
    external_number: str
    values: dict[str, Any]
    relations: tuple[dict[str, str], ...]
    content_hash: str


@dataclass(frozen=True)
class PreparedExport:
    records: tuple[PreparedRecord, ...]
    manifest: dict[str, Any]
    statistics: dict[str, Any]


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ExportValidationError("knowledge_json_duplicate_key")
        result[key] = value
    return result


def _read_jsonl(path: Path) -> tuple[list[dict[str, Any]], str]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        raise ExportValidationError("knowledge_input_file_invalid")
    result = []
    hasher = hashlib.sha256()
    identities: set[str] = set()
    with path.open("rb") as stream:
        line_no = 0
        while line := stream.readline(MAX_ROW_BYTES + 1):
            line_no += 1
            if len(line) > MAX_ROW_BYTES or line_no > MAX_RECORDS:
                raise ExportValidationError("knowledge_input_limit_exceeded", line_no)
            hasher.update(line)
            try:
                row = json.loads(line, object_pairs_hook=_unique_object)
                if not isinstance(row, dict):
                    raise ExportValidationError("knowledge_record_invalid")
                external_id = identifier(row.get("uuid"))
                if external_id in identities:
                    raise ExportValidationError("knowledge_duplicate_document")
                identities.add(external_id)
                # 拒绝 NaN、Infinity 和非法 UTF-8 代理字符。
                canonical_json(row).encode("utf-8")
            except ExportValidationError as exc:
                raise ExportValidationError(exc.code, line_no) from None
            except (ValueError, UnicodeError, RecursionError):
                raise ExportValidationError("knowledge_json_invalid", line_no) from None
            result.append(row)
    return result, hasher.hexdigest()


def _timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if type(value) is not int:
        raise ExportValidationError("knowledge_timestamp_invalid")
    if value == 0:
        return None
    try:
        converted = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=value)
        if not 2000 <= converted.year <= 2200:
            raise ValueError
        return converted.isoformat()
    except (OverflowError, ValueError):
        raise ExportValidationError("knowledge_timestamp_invalid") from None


def _normalize(row: dict[str, Any], listing: dict[str, Any], clean: Sanitizer) -> PreparedRecord:
    external_id = identifier(row["uuid"])
    if row.get("summary") != listing.get("name") or row.get("number") != listing.get("number"):
        raise ExportValidationError("knowledge_list_detail_mismatch")
    if row.get("create_time") != listing.get("createTime"):
        raise ExportValidationError("knowledge_creation_time_mismatch")
    title = row.get("summary")
    body = row.get("desc")
    rich = row.get("desc_rich") or ""
    if not isinstance(title, str) or not title.strip() or not isinstance(body, str) or not isinstance(rich, str):
        raise ExportValidationError("knowledge_body_invalid")
    project = listing.get("project")
    status = listing.get("status")
    sprint = listing.get("sprint")
    if not isinstance(project, dict) or not isinstance(status, dict):
        raise ExportValidationError("knowledge_list_scope_invalid")
    if sprint is not None and not isinstance(sprint, dict):
        raise ExportValidationError("knowledge_list_scope_invalid")
    parser = RichText()
    parser.feed(rich)
    safe_rich = clean.text("".join(parser.parts)).strip()
    fields = row.get("field_values")
    if not isinstance(fields, list):
        raise ExportValidationError("knowledge_fields_invalid")
    attributes: dict[str, Any] = {"unmapped_fields": {}, "image_references": parser.images}
    seen_fields: set[str] = set()
    for field in fields:
        if not isinstance(field, dict) or not isinstance(field.get("field_uuid"), str):
            raise ExportValidationError("knowledge_field_invalid")
        key = field["field_uuid"]
        if key in seen_fields:
            raise ExportValidationError("knowledge_field_duplicate")
        seen_fields.add(key)
        if _SENSITIVE_KEY.search(key):
            clean.counts["sensitive_field"] += 1
            continue
        if key in FIELD_MAPPING:
            attributes[FIELD_MAPPING[key]] = clean.value(field.get("value"))
        elif key not in _DUPLICATE_FIELDS:
            attributes["unmapped_fields"][key] = clean.value(field.get("value"))
    attributes.update({
        "sprint_id": identifier(sprint.get("uuid")) if sprint else None,
        "sprint_name": clean.value(sprint.get("name")) if sprint else None,
        "source_issue_type_display": clean.value(row.get("issue_type_uuid")),
        "export_id_mapping": "detail_display_values_joined_to_list_ids",
    })
    links = row.get("links") or []
    related = row.get("related_tasks") or []
    if not isinstance(links, list) or not isinstance(related, list):
        raise ExportValidationError("knowledge_relations_invalid")
    relations: dict[str, dict[str, str]] = {}
    for link in links:
        if not isinstance(link, dict):
            raise ExportValidationError("knowledge_relation_invalid")
        relation = {
            "target_external_id": identifier(link.get("task_uuid")),
            "source_relation_type": identifier(link.get("task_link_type_uuid")),
            "source_direction": identifier(link.get("link_desc_type")),
        }
        relations[digest(relation)] = relation
    # related_tasks 只有摘要而不是完整正文，仅保存身份；不可生成虚假工单。
    related_refs = []
    for item in related:
        if not isinstance(item, dict):
            raise ExportValidationError("knowledge_relation_invalid")
        related_refs.append({"uuid": identifier(item.get("uuid")), "readable": item.get("readable") is True})
    snapshot_detail = {key: value for key, value in row.items() if key not in {
        "desc_rich", "field_values", "related_tasks", "SkipCheckFieldPermissions",
    }}
    snapshot_detail["desc_rich_text"] = safe_rich
    snapshot_detail["related_task_references"] = related_refs
    # 字段值保留在规范化属性中，避免第二份富文本/Base64 原样进入快照。
    snapshot_detail["field_values_storage"] = "attributes"
    discussion_count = row.get("discussion_count", 0)
    attachment_count = row.get("attachment_count", 0)
    if any(type(v) is not int or v < 0 for v in (discussion_count, attachment_count)):
        raise ExportValidationError("knowledge_content_counts_invalid")
    values = {
        "title": clean.text(title), "body_text": clean.text(body).strip() or safe_rich,
        "source_project_id": identifier(project.get("uuid")),
        "source_project_name": clean.value(row.get("project_uuid")) or "",
        "source_status_id": identifier(status.get("uuid")),
        "source_status_name": clean.value(status.get("name")),
        "source_created_at": _timestamp(row.get("create_time")),
        "source_updated_at": _timestamp(row.get("server_update_stamp")),
        "source_update_stamp_raw": row.get("server_update_stamp") or None,
        "source_snapshot": {"detail": clean.value(snapshot_detail), "list": clean.value(listing)},
        "attributes": attributes,
        "completeness": {
            "detail": "collected", "discussion": "not_collected", "attachments": "not_collected",
            "ocr": "not_requested", "relation_set": "unverified", "discussion_count": discussion_count,
            "attachment_count": attachment_count, "inline_image_count": len(parser.images),
        },
        "normalizer_version": NORMALIZER_VERSION,
    }
    if not values["title"].strip() or not values["body_text"].strip():
        raise ExportValidationError("knowledge_text_empty")
    return PreparedRecord(external_id, str(row["number"]), values, tuple(relations.values()), digest(values))


def prepare_export(detail_path: Path, list_path: Path, *, expected_count: int) -> PreparedExport:
    if not 1 <= expected_count <= MAX_RECORDS:
        raise ExportValidationError("knowledge_expected_count_invalid")
    details, detail_hash = _read_jsonl(detail_path)
    listings, list_hash = _read_jsonl(list_path)
    if len(details) != expected_count or len(listings) != expected_count:
        raise ExportValidationError("knowledge_record_count_mismatch")
    indexed = {row["uuid"]: row for row in listings}
    if {row["uuid"] for row in details} != indexed.keys():
        raise ExportValidationError("knowledge_record_set_mismatch")
    clean = Sanitizer()
    prepared = []
    for line_no, row in enumerate(details, 1):
        try:
            prepared.append(_normalize(row, indexed[row["uuid"]], clean))
        except ExportValidationError as exc:
            raise ExportValidationError(exc.code, line_no) from None
    manifest = {
        "detail_sha256": detail_hash, "list_sha256": list_hash, "record_count": expected_count,
        "normalizer_version": NORMALIZER_VERSION, "document_kind": "defect",
        "timestamp_contract": "ones-export-epoch-microseconds",
    }
    return PreparedExport(tuple(prepared), manifest, {
        "records": len(prepared), "projects": len({r.values["source_project_id"] for r in prepared}),
        "relation_observations": sum(len(r.relations) for r in prepared),
        "image_references": sum(r.values["completeness"]["inline_image_count"] for r in prepared),
        "redactions": dict(clean.counts),
    })
