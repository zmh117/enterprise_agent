from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Never

import jsonschema

from app.modules.file_workspace.authorization import (
    FileAuthorizationContext,
    FileAuthorizationService,
)
from app.modules.file_workspace.contracts import FILE_TOOL_MANIFEST
from app.modules.file_workspace.domain import FileAction
from app.modules.file_workspace.repository import FileWorkspaceRepository
from app.modules.file_workspace.streaming_service import GovernedFileStreamingService
from app.shared.exceptions import NonRetryableExecutionError


class FileWorkspaceApplicationService:
    def __init__(
        self,
        repository: FileWorkspaceRepository,
        authorization: FileAuthorizationService,
        streaming: GovernedFileStreamingService | None = None,
    ) -> None:
        self.repository = repository
        self.authorization = authorization
        self.streaming = streaming

    def invoke(
        self,
        *,
        context: FileAuthorizationContext,
        tool_identifier: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        definition = FILE_TOOL_MANIFEST.get(tool_identifier)
        if definition is None:
            self._deny("file_tool_denied", "当前任务没有此文件工具")
        assert definition is not None
        try:
            jsonschema.validate(arguments, dict(definition.input_schema))
        except jsonschema.ValidationError as exc:
            raise NonRetryableExecutionError(
                "File Tool input schema rejected the request",
                safe_message="文件工具参数无效",
                error_code="file_tool_input_invalid",
            ) from exc
        if tool_identifier == "task_workspace_get":
            return self._workspace(context)
        if tool_identifier == "task_workspace_list_files":
            return self._list_files(context, arguments)
        if tool_identifier == "file_get_metadata":
            item = self.authorization.require_manifest_action(
                context,
                file_id=str(arguments["file_id"]),
                version_id=str(arguments["version_id"]),
                action=FileAction.READ_METADATA,
            )
            return {**self._metadata(item), "observed_at": _observed_at()}
        if tool_identifier == "file_prepare_materialization":
            if self.streaming is None:
                self._deny("file_streaming_not_ready", "文件流式操作尚未就绪")
            assert self.streaming is not None
            return self.streaming.prepare_materialization(
                context=context, arguments=arguments
            )
        if tool_identifier == "file_create_commit_intent":
            if self.streaming is None:
                self._deny("file_streaming_not_ready", "文件流式操作尚未就绪")
            assert self.streaming is not None
            return self.streaming.prepare_commit(context=context, arguments=arguments)
        if tool_identifier == "file_deliver_version":
            if self.streaming is None:
                self._deny("file_streaming_not_ready", "文件流式操作尚未就绪")
            assert self.streaming is not None
            return self.streaming.deliver_version(
                context=context,
                arguments=arguments,
            )
        self._deny("file_tool_not_ready", "文件操作尚未就绪")

    def _workspace(self, context: FileAuthorizationContext) -> dict[str, Any]:
        workspace = context.workspace
        counts = self.repository.database.execute_one(
            """
            select count(*) as file_count,
                   coalesce(sum(v.size_bytes), 0) as logical_bytes
              from task_workspace_file wf
              join managed_file_version v on v.id = wf.selected_version_id
             where wf.workspace_id = ? and wf.status = 'ACTIVE'
            """,
            (workspace["id"],),
        ) or {"file_count": 0, "logical_bytes": 0}
        persisted = self.repository.get_workspace(str(workspace["id"]))
        return {
            "workspace_id": str(workspace["id"]),
            "status": str(workspace["status"]),
            "retention_period": str(persisted["retention_period"]),
            "expires_at": str(persisted["expires_at"]),
            "file_count": int(counts["file_count"]),
            "logical_bytes": int(counts["logical_bytes"]),
            "limits": {"file_count": 20, "temporary_bytes": 100 * 1024 * 1024},
        }

    def _list_files(
        self,
        context: FileAuthorizationContext,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        limit = int(arguments.get("limit") or 20)
        cursor = str(arguments.get("cursor") or "")
        rows = self.repository.database.execute(
            """
            select wf.id as cursor, wf.logical_name, wf.role,
                   f.id as file_id, f.status as file_status,
                   v.id as version_id, v.version_number, v.status as version_status,
                   v.media_type, v.size_bytes, v.content_sha256,
                   f.source_received_at,
                   v.created_at as version_created_at
              from task_workspace_file wf
              join managed_file f on f.id = wf.file_id
              join managed_file_version v on v.id = wf.selected_version_id
             where wf.workspace_id = ? and wf.status = 'ACTIVE' and wf.id > ?
             order by wf.id limit ?
            """,
            (context.workspace["id"], cursor, limit + 1),
        )
        has_more = len(rows) > limit
        visible = rows[:limit]
        return {
            "items": [self._metadata(row) for row in visible],
            "next_cursor": str(visible[-1]["cursor"]) if has_more and visible else "",
            "observed_at": _observed_at(),
        }

    @staticmethod
    def _metadata(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "file_id": str(row["file_id"]),
            "version_id": str(row["version_id"]),
            "display_name": str(row.get("logical_name") or row.get("display_name") or ""),
            "role": str(row.get("role") or ""),
            "file_status": str(row.get("file_status") or "ACTIVE"),
            "version_status": str(row.get("version_status") or ""),
            "version_number": int(row.get("version_number") or 0),
            "media_type": str(row.get("media_type") or ""),
            "size_bytes": int(row.get("size_bytes") or 0),
            "content_sha256": str(row.get("content_sha256") or ""),
            "source_received_at": (
                str(row.get("source_received_at"))
                if row.get("source_received_at")
                else None
            ),
            "version_created_at": str(row.get("version_created_at") or ""),
        }

    @staticmethod
    def _deny(code: str, safe_message: str) -> Never:
        raise NonRetryableExecutionError(
            "File Tool request denied",
            safe_message=safe_message,
            error_code=code,
        )


def _observed_at() -> str:
    return datetime.now(UTC).isoformat()
