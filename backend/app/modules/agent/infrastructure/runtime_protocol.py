from __future__ import annotations

import hashlib
import json
from typing import Any, cast

from app.modules.agent.infrastructure.generated_runtime_contracts_v1_3 import (
    AgentExecutionRequestV13,
    CONTRACT_SCHEMA_PATH as CONTRACT_SCHEMA_PATH_V13,
    validate_contract as validate_v13_contract,
)

CURRENT_RUNTIME_PROTOCOL_VERSION = "1.3"
SUPPORTED_RUNTIME_PROTOCOL_VERSIONS = (CURRENT_RUNTIME_PROTOCOL_VERSION,)


class RuntimeProtocolError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def canonical_request_digest(payload: dict[str, Any]) -> str:
    digest_input = dict(payload)
    digest_input.pop("request_digest", None)
    serialized = json.dumps(
        digest_input,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def validate_execution_request(
    payload: object,
    *,
    encoded_bytes: int | None = None,
) -> AgentExecutionRequestV13:
    protocol_version = _protocol_version(payload)
    contract_path = CONTRACT_SCHEMA_PATH_V13
    limits_path = contract_path.with_name("limits.json")
    limits = json.loads(limits_path.read_text(encoding="utf-8"))
    size = encoded_bytes
    if size is None:
        size = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    if size > int(limits["max_request_bytes"]):
        raise RuntimeProtocolError(
            "runtime_request_too_large",
            f"request is {size} bytes; maximum is {limits['max_request_bytes']}",
        )
    try:
        validate_runtime_contract(
            "AgentExecutionRequestV13",
            payload,
            protocol_version=protocol_version,
        )
    except ValueError as exc:
        raise RuntimeProtocolError("runtime_request_invalid", str(exc)) from exc
    assert isinstance(payload, dict)
    _validate_file_context(payload)
    actual = canonical_request_digest(payload)
    if actual != payload["request_digest"]:
        raise RuntimeProtocolError(
            "runtime_request_digest_mismatch",
            "request digest does not match the canonical request body",
        )
    return cast(
        AgentExecutionRequestV13,
        payload,
    )


def validate_runtime_contract(
    definition_name: str,
    payload: object,
    *,
    protocol_version: str | None = None,
) -> None:
    version = protocol_version or _protocol_version(payload)
    if version != CURRENT_RUNTIME_PROTOCOL_VERSION:
        raise ValueError(f"unsupported runtime protocol version: {version}")
    validate_v13_contract(definition_name, payload)


def _protocol_version(payload: object) -> str:
    if isinstance(payload, dict):
        value = payload.get("protocol_version")
        if value in SUPPORTED_RUNTIME_PROTOCOL_VERSIONS:
            return str(value)
    raise RuntimeProtocolError(
        "runtime_protocol_unsupported",
        "only runtime protocol 1.3 is supported",
    )


def _validate_file_context(payload: dict[str, Any]) -> None:
    context = payload.get("file_context")
    if not isinstance(context, dict):
        raise RuntimeProtocolError(
            "runtime_file_context_invalid",
            "runtime v1.3 requires a frozen file context",
        )
    manifest = context.get("file_manifest")
    if manifest is None:
        return
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != 5
        or not manifest.get("workspace_catalog_revision_id")
    ):
        raise RuntimeProtocolError(
            "runtime_file_manifest_invalid",
            "runtime protocol 1.3 requires manifest schema v5",
        )
    document_actions = {"READ_METADATA", "RETAIN", "DELIVER"}
    matrix = {
        "TXT": {"READ_METADATA", "MATERIALIZE", "EDIT", "COMMIT", "RETAIN", "DELIVER"},
        "LOG": {"READ_METADATA", "MATERIALIZE", "RETAIN", "DELIVER"},
        "MARKDOWN": {
            "READ_METADATA",
            "MATERIALIZE",
            "EDIT",
            "COMMIT",
            "RETAIN",
            "DELIVER",
        },
        "PDF": document_actions,
        "DOCX": document_actions,
        "PPTX": document_actions,
        "XLSX": document_actions,
        "PNG": document_actions,
        "JPEG": document_actions,
        "WEBP": document_actions,
    }
    suffixes = {
        "TXT": (".txt",),
        "LOG": (".log",),
        "MARKDOWN": (".md",),
        "PDF": (".pdf",),
        "DOCX": (".docx",),
        "PPTX": (".pptx",),
        "XLSX": (".xlsx",),
        "PNG": (".png",),
        "JPEG": (".jpg", ".jpeg"),
        "WEBP": (".webp",),
    }
    # Document source items are only readable through a completed Markdown
    # representation, so the representation fields travel as one indivisible set.
    representation_fields = (
        "representation_id",
        "representation_kind",
        "representation_size_bytes",
        "representation_sha256",
        "representation_format_code",
        "representation_created_at",
    )
    identities: set[tuple[str, str]] = set()
    items = manifest.get("items") or []
    if len(items) > 40:
        raise RuntimeProtocolError(
            "runtime_file_manifest_limit_exceeded",
            "file manifest exceeds the 40 input working-set limit",
        )
    for item in items:
        assert isinstance(item, dict)
        format_code = str(item["format_code"])
        if format_code not in suffixes:
            raise RuntimeProtocolError(
                "runtime_file_format_mismatch",
                "file manifest declares an unsupported format",
            )
        identity = (str(item["file_id"]), str(item["version_id"]))
        if identity in identities:
            raise RuntimeProtocolError(
                "runtime_file_manifest_duplicate",
                "file manifest contains a duplicate exact version",
            )
        identities.add(identity)
        if not str(item["display_name"]).lower().endswith(suffixes[format_code]):
            raise RuntimeProtocolError(
                "runtime_file_format_mismatch",
                "file manifest name does not match its format",
            )
        if not set(item["allowed_actions"]).issubset(matrix[format_code]):
            raise RuntimeProtocolError(
                "runtime_file_actions_invalid",
                "file manifest actions exceed the frozen format policy",
            )
        is_document = format_code not in {"TXT", "LOG", "MARKDOWN"}
        present = {field for field in representation_fields if item.get(field) is not None}
        if is_document and present and len(present) != len(representation_fields):
            raise RuntimeProtocolError(
                "runtime_file_representation_invalid",
                "document manifest item requires a complete Markdown representation",
            )
        if (
            is_document
            and item.get("auto_materialize")
            and len(present) != len(representation_fields)
        ):
            raise RuntimeProtocolError(
                "runtime_file_representation_invalid",
                "auto-materialized document items require a complete Markdown representation",
            )
        if not is_document and present:
            raise RuntimeProtocolError(
                "runtime_file_representation_invalid",
                "text manifest item must not carry a document representation",
            )
