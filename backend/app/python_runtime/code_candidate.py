"""Seal data-only model authoring into the canonical envelope from verified source bytes."""

from typing import Any

from app.modules.knowledge.domain.code_contracts import (
    AUTHORING,
    CodeKnowledgeError,
    MAX_PACKAGE_BYTES,
    validate,
)
from app.modules.knowledge.domain.code_package import (
    EvidenceSource,
    parse_json,
    sha256,
    encode_package,
    verify_candidate,
)
from app.modules.knowledge.infrastructure.code_source import _read_beneath
from app.python_runtime.code_source_mount import CodeSourceMount


def seal_candidate(
    raw: bytes,
    mount: CodeSourceMount,
    expected: dict[str, Any],
    *,
    expected_entries: set[str] | None = None,
) -> bytes:
    if len(raw) > MAX_PACKAGE_BYTES:
        raise CodeKnowledgeError("code_package_invalid_size_or_text")
    value = parse_json(raw.decode("utf-8"))
    validate(value, AUTHORING)
    package = value["entries"]
    if package["manifest.json"] != expected:
        raise CodeKnowledgeError("code_candidate_binding_mismatch")
    sources: dict[str, EvidenceSource] = {}
    for evidence in package["evidence.jsonl"]:
        mount.recheck()
        path = evidence["path"]
        source = mount.files.get(path)
        if (
            not source
            or evidence["source_snapshot_id"] != mount.snapshot_id
            or any(
                evidence[field] != source[field]
                for field in ("file_id", "raw_hash", "representation_hash")
            )
        ):
            raise CodeKnowledgeError("code_evidence_source_unavailable")
        data = _read_beneath(mount.root, path, MAX_PACKAGE_BYTES)
        if sha256(data) != source["representation_hash"]:
            raise CodeKnowledgeError("code_source_changed")
        lines = data.decode("utf-8").splitlines(keepends=True)
        start, end = evidence["start_line"], evidence["end_line"]
        if not 1 <= start <= end <= len(lines):
            raise CodeKnowledgeError("code_evidence_lines_invalid")
        evidence["excerpt_hash"] = sha256("".join(lines[start - 1 : end]).encode())
        sources[source["file_id"]] = EvidenceSource(
            path, source["raw_hash"], source["representation_hash"], data.decode("utf-8")
        )
    if expected_entries is not None:
        verify_candidate(
            package,
            expected_manifest=expected,
            sources=sources,
            expected_entries=expected_entries,
        )
    return encode_package(package)
