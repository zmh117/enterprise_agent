from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from services.mcp_common.contracts import AuthorizedToolContext
from services.mcp_common.platform_store import PlatformQuery
from services.mcp_common.sensitive_data import sanitize_sensitive_data


class McpProvenanceRecorder:
    def __init__(self, query: PlatformQuery, *, server_code: str, server_version: str) -> None:
        self.query = query
        self.server_code = server_code
        self.server_version = server_version

    def record(
        self,
        *,
        context: AuthorizedToolContext,
        request_summary: dict[str, Any],
        result_payload: Any,
        status: str,
        duration_ms: int,
        credential_revision: int = 0,
        error_code: str = "",
        attempt: int = 1,
    ) -> str:
        if status not in {"SUCCEEDED", "FAILED", "DENIED"}:
            raise ValueError("Unsupported MCP provenance status")
        if not 1 <= attempt <= 3:
            raise ValueError("MCP attempt must be between one and three")
        encoded = (
            json.dumps(
                result_payload,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode()
            if result_payload is not None
            else b""
        )
        provenance_id = f"mcp_provenance_{uuid.uuid4().hex}"
        occurred_at = datetime.now(UTC).isoformat()
        self.query.execute(
            """
            insert into mcp_tool_call_provenance
              (id, job_id, app_user_id, application_publication_id,
               mcp_server_code, server_version, tool_name, tool_schema_hash,
               subject_snapshot_id, resource_deployment_id, resource_revision_id,
               credential_revision, request_summary_json, result_hash, result_size,
               status, duration_ms, correlation_id, occurred_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                provenance_id,
                context.job.job_id,
                context.job.app_user_id,
                context.job.application_publication_id,
                self.server_code,
                self.server_version,
                context.binding.tool_name,
                context.binding.tool_schema_hash,
                context.binding.subject_snapshot_id,
                context.binding.resource_deployment_id,
                context.binding.resource_revision_id,
                credential_revision,
                json.dumps(
                    sanitize_sensitive_data(request_summary),
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                hashlib.sha256(encoded).hexdigest() if encoded else "",
                len(encoded),
                status,
                max(0, duration_ms),
                context.principal.correlation_id,
                occurred_at,
            ),
        )
        self.query.execute(
            """
            insert into mcp_tool_call_attempt
              (id, provenance_id, attempt, status, error_code, duration_ms, created_at)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"mcp_attempt_{uuid.uuid4().hex}",
                provenance_id,
                attempt,
                status,
                error_code[:128],
                max(0, duration_ms),
                occurred_at,
            ),
        )
        return provenance_id
