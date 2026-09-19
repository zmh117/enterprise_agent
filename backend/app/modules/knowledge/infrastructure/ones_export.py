"""ONES 导出文件读取适配器。"""

import hashlib
import json
from app.modules.knowledge.domain.normalization import canonical_json
from pathlib import Path
from typing import Any
from app.modules.knowledge.domain.normalization import (
    MAX_FILE_BYTES,
    MAX_ROW_BYTES,
    MAX_RECORDS,
    NORMALIZER_VERSION,
    ExportValidationError,
    PreparedExport,
    Sanitizer,
    _normalize,
    _unique_object,
    identifier,
)


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
        "detail_sha256": detail_hash,
        "list_sha256": list_hash,
        "record_count": expected_count,
        "normalizer_version": NORMALIZER_VERSION,
        "document_kind": "defect",
        "timestamp_contract": "ones-export-epoch-microseconds",
    }
    return PreparedExport(
        tuple(prepared),
        manifest,
        {
            "records": len(prepared),
            "projects": len({r.values["source_project_id"] for r in prepared}),
            "relation_observations": sum(len(r.relations) for r in prepared),
            "image_references": sum(
                r.values["completeness"]["inline_image_count"] for r in prepared
            ),
            "redactions": dict(clean.counts),
        },
    )
