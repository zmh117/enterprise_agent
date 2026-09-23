"""明确四份文件组成三类批次；只返回规范化内容及安全统计，不执行导出脚本。"""

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any

from app.modules.knowledge.domain.keep_ids import KEEP_IDS_NORMALIZER, normalize_keep_ids
from app.modules.knowledge.domain.normalization import (
    ExportValidationError,
    MAX_FILE_BYTES,
    PreparedExport,
    Sanitizer,
    _unique_object,
    canonical_json,
    digest,
    identifier,
)
from app.modules.knowledge.infrastructure.ones_export import _read_jsonl


LABELS = {"缺陷": "defect", "工单": "ticket", "Story": "requirement", "子任务": "requirement"}


def read_object(path: Path) -> tuple[dict[str, Any], str]:
    if (
        path.is_symlink()
        or not path.is_file()
        or path.stat().st_size > min(MAX_FILE_BYTES, 16 * 1024 * 1024)
    ):
        raise ExportValidationError("knowledge_input_file_invalid")
    raw = path.read_bytes()
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
        if not isinstance(value, dict):
            raise ValueError
        canonical_json(value).encode("utf-8")
    except (ValueError, UnicodeError, RecursionError):
        raise ExportValidationError("knowledge_json_invalid") from None
    return value, hashlib.sha256(raw).hexdigest()


def prepare_keep_ids(root: Path, *, expected: dict[str, int]) -> tuple[PreparedExport, ...]:
    if (
        set(expected) != set(LABELS)
        or any(type(n) is not int or not 1 <= n <= 200_000 for n in expected.values())
        or sum(expected.values()) > 200_000
    ):
        raise ExportValidationError("knowledge_expected_count_invalid")
    dictionary, dictionary_hash = read_object(root / "字段字典.json")
    if not isinstance(dictionary.get("fields"), list):
        raise ExportValidationError("knowledge_field_dictionary_invalid")
    fields = {}
    for field in dictionary["fields"]:
        if not isinstance(field, dict) or not isinstance(field.get("name"), str):
            raise ExportValidationError("knowledge_field_dictionary_invalid")
        fid = identifier(field.get("uuid"))
        if fid in fields or not isinstance(field.get("options", []), list):
            raise ExportValidationError("knowledge_field_dictionary_invalid")
        seen_options = set()
        for option in field.get("options", []):
            if not isinstance(option, dict) or "value" not in option:
                raise ExportValidationError("knowledge_field_dictionary_invalid")
            oid = identifier(option.get("uuid"))
            if oid in seen_options:
                raise ExportValidationError("knowledge_field_dictionary_invalid")
            seen_options.add(oid)
        fields[fid] = field
    host, team = dictionary.get("source_host"), dictionary.get("team_id")
    if not isinstance(host, str) or not host.strip():
        raise ExportValidationError("knowledge_source_identity_invalid")
    identifier(team)
    source_hash = digest([host, team])
    rows, listings, files = {}, {}, {}
    seen: set[str] = set()
    for label in LABELS:
        meta, meta_hash = read_object(root / (label + "_采集说明.json"))
        details, file_hash = _read_jsonl(root / (label + ".jsonl"))
        if (
            meta.get("export_format") != "keep_ids_v1"
            or meta.get("source_host") != host
            or meta.get("team_id") != team
        ):
            raise ExportValidationError("knowledge_source_identity_invalid")
        if (
            len(details) != expected[label]
            or meta.get("success") != len(details)
            or meta.get("failed") != 0
            or meta.get("failed_uuids")
        ):
            raise ExportValidationError("knowledge_record_count_mismatch")
        ids = {r["uuid"] for r in details}
        if seen & ids:
            raise ExportValidationError("knowledge_duplicate_document")
        seen.update(ids)
        rows[label] = details
        files[label] = {"detail_sha256": file_hash, "metadata_sha256": meta_hash}
        if label != "子任务":
            listing, list_hash = _read_jsonl(root / (label + "_list.jsonl"))
            if (
                meta.get("list_pagination_complete") is not True
                or {r["uuid"] for r in listing} != ids
            ):
                raise ExportValidationError("knowledge_record_set_mismatch")
            listings[label] = {r["uuid"]: r for r in listing}
            files[label]["list_sha256"] = list_hash
    children = {r["uuid"]: r for r in rows["子任务"]}
    story_ids = {r["uuid"] for r in rows["Story"]}
    ancestors: dict[str, str] = {}
    for story in rows["Story"]:
        subtasks = story.get("subtasks") or []
        if not isinstance(subtasks, list):
            raise ExportValidationError("knowledge_parent_set_invalid")
        for child in subtasks:
            if not isinstance(child, dict):
                raise ExportValidationError("knowledge_parent_set_invalid")
            uid = identifier(child.get("uuid"))
            if uid in ancestors and ancestors[uid] != story["uuid"]:
                raise ExportValidationError("knowledge_parent_set_invalid")
            ancestors[uid] = story["uuid"]
    if children.keys() != ancestors.keys():
        raise ExportValidationError("knowledge_parent_set_invalid")
    for uid, child in children.items():
        visited = {uid}
        parent = child.get("parent_uuid")
        while parent in children:
            if parent in visited:
                raise ExportValidationError("knowledge_parent_cycle")
            visited.add(parent)
            parent = children[parent].get("parent_uuid")
        if parent not in story_ids or parent != ancestors[uid]:
            raise ExportValidationError("knowledge_parent_set_invalid")
    clean = Sanitizer()
    prepared: dict[str, list[Any]] = {kind: [] for kind in LABELS.values()}
    for label, kind in LABELS.items():
        for line, row in enumerate(rows[label], 1):
            try:
                prepared[kind].append(
                    normalize_keep_ids(
                        row,
                        listings.get(label, {}).get(row["uuid"]),
                        kind=kind,
                        fields=fields,
                        clean=clean,
                    )
                )
            except ExportValidationError as exc:
                raise ExportValidationError(exc.code, line) from None
    result = []
    for kind, records in prepared.items():
        manifest = {
            "export_format": "keep_ids_v1",
            "normalizer_version": KEEP_IDS_NORMALIZER,
            "document_kind": kind,
            "record_count": len(records),
            "source_identity_hash": source_hash,
            "dictionary_sha256": dictionary_hash,
            "files": {label: files[label] for label in LABELS if LABELS[label] == kind},
            "timestamp_contract": "ones-export-epoch-microseconds",
        }
        result.append(
            PreparedExport(
                tuple(records),
                manifest,
                {
                    "records": len(records),
                    "description_missing": sum(
                        r.values["completeness"]["description"] == "missing" for r in records
                    ),
                    "relation_observations": sum(len(r.relations) for r in records),
                    "source_types": dict(
                        Counter(
                            r.values["attributes"]["source_issue_type_display"] for r in records
                        )
                    ),
                    "redactions": dict(clean.counts),
                },
            )
        )
    return tuple(result)
