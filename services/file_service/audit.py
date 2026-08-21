from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from app.modules.file_workspace.authorization import FileAuthorizationContext
from app.modules.file_workspace.contracts import FILE_MCP_SERVER_CODE, FILE_TOOL_MANIFEST
from app.modules.file_workspace.safe_summary import safe_file_audit_summary
from app.modules.mcp_audit import McpAuditContext, McpAuditCoordinator, McpAuditHandle
from app.shared.exceptions import PermissionDenied


class FileMcpAudit:
    def __init__(self, coordinator: McpAuditCoordinator) -> None:
        self.coordinator = coordinator

    def begin(
        self,
        *,
        claims: dict[str, Any],
        authorization: FileAuthorizationContext,
        tool_identifier: str,
        arguments: dict[str, Any],
        invocation_id: str,
        correlation_id: str,
    ) -> McpAuditHandle:
        expected_invocation = (
            f"{authorization.job['id']}.attempt-{int(authorization.job['retry_count'])}"
        )
        effective_invocation = invocation_id or expected_invocation
        if effective_invocation != expected_invocation:
            raise PermissionDenied(
                "File MCP invocation does not match the current Job attempt",
                safe_message="文件工具调用与当前任务执行不一致",
                error_code="file_mcp_invocation_mismatch",
            )
        definition = FILE_TOOL_MANIFEST[tool_identifier]
        filter_summary = ""
        if tool_identifier == "task_workspace_search_files":
            filter_shape = {
                "keys": sorted(
                    key
                    for key in arguments
                    if key not in {"cursor", "file_id", "version_id"}
                ),
                "has_cursor": bool(arguments.get("cursor")),
            }
            filter_summary = hashlib.sha256(
                json.dumps(filter_shape, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        return self.coordinator.begin(
            McpAuditContext(
                correlation_id=(correlation_id.strip() or f"job:{claims['job_id']}")[:128],
                job_id=str(claims["job_id"]),
                session_id=str(claims["session_id"]),
                invocation_id=effective_invocation,
                actor_user_id=str(claims["sub"]),
                server_code=FILE_MCP_SERVER_CODE,
                tool_identifier=tool_identifier,
                tool_schema_hash=definition.schema_hash,
                agent_publication_id=str(claims["agent_publication_id"]),
                application_publication_id=str(
                    claims["application_publication_id"]
                ),
                operation=definition.operation,
                risk_level="medium" if definition.mutating else "low",
                principal_jti=str(claims["jti"]),
                provider="internal_file_service",
            ),
            business_request=safe_file_audit_summary(
                {
                    "operation": definition.operation,
                    "tool_identifier": tool_identifier,
                    "job_id": claims["job_id"],
                    "workspace_id": authorization.workspace["id"],
                    "file_id": arguments.get("file_id"),
                    "version_id": arguments.get("version_id"),
                    "commit_id": arguments.get("commit_id"),
                    "workspace_catalog_revision_id": authorization.manifest.get(
                        "workspace_catalog_revision_id"
                    ),
                    "filter_summary": filter_summary,
                }
            ),
        )

    def authorized(self, handle: McpAuditHandle) -> None:
        self.coordinator.append_event(
            handle,
            event_kind="AUTHORIZATION",
            status="SUCCEEDED",
            authorization_decision="ALLOW",
            authorization_reason="job_workspace_manifest_allowed",
            business_request={"stage": "file_tool_call"},
        )

    def complete(
        self,
        handle: McpAuditHandle,
        *,
        status: Literal["SUCCEEDED", "FAILED", "DENIED"],
        result: dict[str, Any],
        duration_ms: int,
        error_code: str = "",
    ) -> None:
        response = dict(result)
        if handle.context.tool_identifier == "task_workspace_search_files":
            response = {
                "workspace_catalog_revision_id": result.get(
                    "workspace_catalog_revision_id"
                ),
                "returned_count": len(result.get("items") or []),
                "error_code": error_code,
            }
        self.coordinator.complete(
            handle,
            status=status,
            error_code=error_code,
            business_response=safe_file_audit_summary(response),
            duration_ms=max(duration_ms, 0),
        )
