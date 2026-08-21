from __future__ import annotations

from typing import Any


_ALLOWED_FILE_AUDIT_FIELDS = frozenset(
    {
        "operation",
        "status",
        "error_code",
        "job_id",
        "session_id",
        "workspace_id",
        "file_id",
        "version_id",
        "commit_id",
        "delivery_id",
        "principal_jti",
        "tool_identifier",
        "schema_hash",
        "duration_ms",
        "size_bytes",
        "content_sha256",
        "item_count",
        "returned_count",
        "workspace_catalog_revision_id",
        "filter_summary",
    }
)


def safe_file_audit_summary(value: dict[str, Any]) -> dict[str, Any]:
    """Project a file operation to an allowlisted, body-free audit fact."""
    return {
        key: _bounded_scalar(item)
        for key, item in value.items()
        if key in _ALLOWED_FILE_AUDIT_FIELDS and item is not None and item != ""
    }


def _bounded_scalar(value: Any) -> str | int | bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return max(min(value, 2**63 - 1), -(2**63))
    if isinstance(value, str):
        return value[:256]
    return "[OMITTED]"
