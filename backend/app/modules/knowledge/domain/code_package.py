"""Strict JSON envelope and source evidence verification; model text is never a command."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from app.modules.knowledge.domain.code_contracts import (
    CONTRACT_VERSION,
    ENVELOPE,
    LOGICAL_SCHEMAS,
    MAX_PACKAGE_BYTES,
    CodeKnowledgeError,
    validate,
)
from app.modules.knowledge.domain.normalization import canonical_json


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CodeKnowledgeError("code_duplicate_json_key")
        result[key] = value
    return result


def parse_json(text: str) -> Any:
    try:
        return json.loads(
            text,
            object_pairs_hook=_unique_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
    except (ValueError, RecursionError):
        raise CodeKnowledgeError("code_json_invalid") from None


def encode_package(entries: dict[str, Any]) -> bytes:
    if set(entries) != set(LOGICAL_SCHEMAS):
        raise CodeKnowledgeError("code_package_entries_invalid")
    encoded = []
    for name, value in entries.items():
        content = (
            "\n".join(canonical_json(row) for row in value)
            if name.endswith(".jsonl")
            else canonical_json(value)
        )
        encoded.append(
            {"logical_name": name, "content": content, "sha256": sha256(content.encode())}
        )
    result = canonical_json({"contract_version": CONTRACT_VERSION, "entries": encoded}).encode()
    decode_package(result)
    return result


def decode_package(data: bytes) -> dict[str, Any]:
    if len(data) > MAX_PACKAGE_BYTES or b"\0" in data:
        raise CodeKnowledgeError("code_package_invalid_size_or_text")
    try:
        envelope = parse_json(data.decode("utf-8"))
    except UnicodeDecodeError:
        raise CodeKnowledgeError("code_package_requires_utf8") from None
    validate(envelope, ENVELOPE)
    result: dict[str, Any] = {}
    for entry in envelope["entries"]:
        name, content = entry["logical_name"], entry["content"]
        if name in result or sha256(content.encode()) != entry["sha256"]:
            raise CodeKnowledgeError("code_package_entry_integrity")
        if name.endswith(".jsonl"):
            value = [parse_json(line) for line in content.splitlines() if line.strip()]
            if len(value) > 10_000:
                raise CodeKnowledgeError("code_package_row_limit")
            for row in value:
                validate(row, LOGICAL_SCHEMAS[name])
        else:
            value = parse_json(content)
            validate(value, LOGICAL_SCHEMAS[name])
        result[name] = value
    if set(result) != set(LOGICAL_SCHEMAS):
        raise CodeKnowledgeError("code_package_entries_invalid")
    return result


@dataclass(frozen=True)
class EvidenceSource:
    """Admitted frozen representation supplied by the controller, never the candidate."""

    path: str
    raw_hash: str
    representation_hash: str
    text: str


def _identities(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    result = {row[key]: row for row in rows}
    if len(result) != len(rows):
        raise CodeKnowledgeError("code_duplicate_identity", key)
    return result


def _evidence_references(value: Any) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "evidence_ids":
                result.update(item)
            else:
                result.update(_evidence_references(item))
    elif isinstance(value, list):
        for item in value:
            result.update(_evidence_references(item))
    return result


def _unknown_guard(value: Any) -> bool:
    if isinstance(value, dict):
        return value.get("op") == "unknown" or any(_unknown_guard(item) for item in value.values())
    if isinstance(value, list):
        return any(_unknown_guard(item) for item in value)
    return False


def _verify_evidence(evidence: dict[str, Any], source: EvidenceSource | None) -> None:
    if source is None:
        raise CodeKnowledgeError("code_evidence_source_unavailable")
    start, end = evidence["start_line"], evidence["end_line"]
    lines = source.text.splitlines(keepends=True)
    if not 1 <= start <= end <= len(lines):
        raise CodeKnowledgeError("code_evidence_lines_invalid")
    if (
        evidence["path"] != source.path
        or evidence["raw_hash"] != source.raw_hash
        or evidence["representation_hash"] != source.representation_hash
        or sha256(source.text.encode()) != source.representation_hash
        or sha256("".join(lines[start - 1 : end]).encode()) != evidence["excerpt_hash"]
    ):
        raise CodeKnowledgeError("code_evidence_digest_mismatch")


def verify_candidate(
    package: dict[str, Any],
    *,
    expected_manifest: dict[str, Any],
    sources: dict[str, EvidenceSource],
    expected_entries: set[str],
) -> dict[str, Any]:
    """Machine proof of binding, references and bytes; NOT proof of business truth."""
    if package["manifest.json"] != expected_manifest:
        raise CodeKnowledgeError("code_candidate_binding_mismatch")
    knowledge = _identities(package["knowledge.jsonl"], "business_key")
    evidence = _identities(package["evidence.jsonl"], "id")
    relations = _identities(package["relations.jsonl"], "id")
    for row in evidence.values():
        if row["source_snapshot_id"] != expected_manifest["source_snapshot_id"]:
            raise CodeKnowledgeError("code_evidence_snapshot_mismatch")
        _verify_evidence(row, sources.get(row["file_id"]))
    if not _evidence_references(package) <= evidence.keys():
        raise CodeKnowledgeError("code_evidence_reference_missing")
    for relation in relations.values():
        if relation["from_key"] not in knowledge or relation["to_key"] not in knowledge:
            raise CodeKnowledgeError("code_relation_endpoint_missing")
    entries = _identities(package["coverage.json"]["entries"], "entry_id")
    if set(entries) != expected_entries:
        raise CodeKnowledgeError("code_entry_coverage_mismatch")
    for entry in entries.values():
        if not set(entry["knowledge_keys"]) <= knowledge.keys():
            raise CodeKnowledgeError("code_coverage_identity_missing")
        if entry["status"] == "analyzed" and not entry["knowledge_keys"]:
            raise CodeKnowledgeError("code_analyzed_entry_empty")
    removals = _identities(package["changes.json"]["removed_keys"], "business_key")
    if removals.keys() & knowledge.keys():
        raise CodeKnowledgeError("code_removed_identity_still_present")
    unknowns = package["coverage.json"]["unknowns"] + [
        item for row in [*knowledge.values(), *entries.values()] for item in row["unknowns"]
    ]
    blocked = (
        bool(package["coverage.json"].get("dependency_requests"))
        or any(item["critical"] for item in unknowns)
        or any(_unknown_guard(row["guard"]) for row in knowledge.values())
        or any(row["identity_state"] != "confirmed" for row in knowledge.values())
        or any(row["status"] != "analyzed" for row in entries.values())
        or any(row["coverage"] != "analyzed" for row in knowledge.values())
        or bool(package["changes.json"]["identity_unresolved"])
    )
    return {
        "machine_valid": True,
        "activation_blocked": blocked,
        "business_verified": False,
        "dependency_requests": package["coverage.json"].get("dependency_requests", []),
        "knowledge_count": len(knowledge),
        "evidence_count": len(evidence),
        "relation_count": len(relations),
        "removed_keys": list(removals.values()),
        "removal_evidence": [
            evidence[key] for key in sorted(_evidence_references(list(removals.values())))
        ],
    }
