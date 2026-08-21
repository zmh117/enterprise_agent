from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Never

import jsonschema

from app.modules.file_workspace.authorization import (
    FileAuthorizationContext,
    FileAuthorizationService,
)
from app.modules.file_workspace.clock import (
    canonicalize_file_time_fields,
    to_utc_rfc3339,
)
from app.modules.file_workspace.contracts import FILE_TOOL_MANIFEST
from app.modules.file_workspace.domain import FileAction
from app.modules.file_workspace.repository import FileWorkspaceRepository
from app.modules.file_workspace.quota import WorkspaceQuotaService
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
        if tool_identifier == "task_workspace_search_files":
            return self._search_files(context, arguments)
        if tool_identifier == "file_get_metadata":
            item = self.authorization.require_manifest_action(
                context,
                file_id=str(arguments["file_id"]),
                version_id=str(arguments["version_id"]),
                action=FileAction.READ_METADATA,
            )
            return {
                **self._metadata(item),
                "readability_status": self._readability_status(str(arguments["version_id"])),
                "observed_at": _observed_at(),
            }
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
        quota = WorkspaceQuotaService(self.repository.database).snapshot(
            str(workspace["id"]), now=_observed_at()
        )
        return {
            "workspace_id": str(workspace["id"]),
            "status": str(workspace["status"]),
            "retention_period": str(persisted["retention_period"]),
            "expires_at": to_utc_rfc3339(persisted.get("expires_at"))
            or str(persisted["expires_at"]),
            "file_count": int(counts["file_count"]),
            "logical_bytes": int(counts["logical_bytes"]),
            "limits": {
                "active_file_count": quota.limits.active_file_limit,
                "billable_bytes": quota.limits.billable_bytes_limit,
                "config_revision": quota.limits.config_revision,
                "active_file_limit_source": quota.limits.active_file_limit_source,
                "billable_bytes_limit_source": quota.limits.billable_bytes_limit_source,
            },
            "usage": {
                "active_file_count": quota.usage.active_file_count,
                "billable_bytes": quota.usage.billable_bytes,
                "reserved_file_slots": quota.usage.reserved_file_slots,
                "reserved_billable_bytes": quota.usage.reserved_billable_bytes,
            },
        }

    def _search_files(
        self,
        context: FileAuthorizationContext,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        if int(context.manifest.get("schema_version") or 0) < 5:
            self._deny(
                "file_workspace_search_manifest_incompatible",
                "当前任务不支持冻结目录搜索",
            )
        catalog_revision_id = str(
            context.manifest.get("workspace_catalog_revision_id") or ""
        )
        if not catalog_revision_id:
            self._deny("file_manifest_invalid", "任务文件清单无效")
        if arguments.get("exact_name") and arguments.get("name_prefix"):
            self._deny("file_tool_input_invalid", "完整名称和名称前缀不能同时使用")
        received_from = self._utc_filter(arguments.get("source_received_from"))
        received_to = self._utc_filter(arguments.get("source_received_to"))
        if received_from and received_to and received_from > received_to:
            self._deny("file_tool_input_invalid", "来源时间范围无效")
        filters = {
            "exact_name": str(arguments.get("exact_name") or ""),
            "name_prefix": str(arguments.get("name_prefix") or ""),
            "format_codes": sorted(str(value) for value in arguments.get("format_codes") or []),
            "source_received_from": received_from,
            "source_received_to": received_to,
            "readability_statuses": sorted(
                str(value) for value in arguments.get("readability_statuses") or []
            ),
        }
        filter_hash = hashlib.sha256(
            json.dumps(filters, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        after = {"sort_name": "", "logical_name": "", "file_id": ""}
        cursor = str(arguments.get("cursor") or "")
        if cursor:
            after = self._decode_search_cursor(
                cursor,
                context=context,
                catalog_revision_id=catalog_revision_id,
                filter_hash=filter_hash,
            )
        limit = int(arguments.get("limit") or 20)
        rows = self.repository.search_catalog_revision(
            workspace_id=str(context.workspace["id"]),
            catalog_revision_id=catalog_revision_id,
            limit=limit + 1,
            exact_name=filters["exact_name"],
            name_prefix=filters["name_prefix"],
            format_codes=tuple(filters["format_codes"]),
            source_received_from=received_from,
            source_received_to=received_to,
            readability_statuses=tuple(filters["readability_statuses"]),
            after_sort_name=after["sort_name"],
            after_logical_name=after["logical_name"],
            after_file_id=after["file_id"],
        )
        has_more = len(rows) > limit
        visible = rows[:limit]
        next_cursor = ""
        if has_more and visible:
            last = visible[-1]
            next_cursor = self._encode_search_cursor(
                context=context,
                catalog_revision_id=catalog_revision_id,
                filter_hash=filter_hash,
                sort_name=str(last["sort_name"]),
                logical_name=str(last["logical_name"]),
                file_id=str(last["file_id"]),
            )
        observed_at = _observed_at()
        return {
            "items": [
                canonicalize_file_time_fields(
                    {
                        "file_id": str(row["file_id"]),
                        "version_id": str(row["version_id"]),
                        "display_name": str(row["logical_name"]),
                        "format_code": str(row["format_code"]),
                        "size_bytes": int(row["size_bytes"]),
                        "source_received_at": row.get("source_received_at"),
                        "version_created_at": str(row["version_created_at"]),
                        "readability_status": str(row["readability_status"]),
                    }
                )
                for row in visible
            ],
            "next_cursor": next_cursor,
            "workspace_catalog_revision_id": catalog_revision_id,
            "observed_at": observed_at,
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
            select i.id as cursor, i.display_name as logical_name, coalesce(wf.role, '') as role,
                   f.id as file_id, f.status as file_status,
                   v.id as version_id, v.version_number, v.status as version_status,
                   v.media_type, v.size_bytes, v.content_sha256,
                   f.source_received_at,
                   v.created_at as version_created_at,
                   coalesce((
                     select a.readability_status
                       from message_attachment_file_binding b
                       join message_attachment a on a.id = b.attachment_id
                      where b.version_id = v.id
                      order by a.readability_updated_at desc, a.id desc
                      limit 1
                   ), 'NOT_REQUIRED') as readability_status
              from agent_job_file_snapshot_item i
              join managed_file f on f.id = i.file_id
              join managed_file_version v on v.id = i.version_id
              left join task_workspace_file wf
                on wf.workspace_id = ? and wf.file_id = i.file_id and wf.status = 'ACTIVE'
             where i.snapshot_id = ? and i.id > ?
             order by i.ordinal, i.id limit ?
            """,
            (context.workspace["id"], str(context.manifest["id"]), cursor, limit + 1),
        )
        has_more = len(rows) > limit
        visible = rows[:limit]
        return {
            "items": [self._metadata(row) for row in visible],
            "next_cursor": str(visible[-1]["cursor"]) if has_more and visible else "",
            "observed_at": _observed_at(),
        }

    def _encode_search_cursor(
        self,
        *,
        context: FileAuthorizationContext,
        catalog_revision_id: str,
        filter_hash: str,
        sort_name: str,
        logical_name: str,
        file_id: str,
    ) -> str:
        payload = {
            "v": 1,
            "snapshot_id": str(context.manifest["id"]),
            "workspace_id": str(context.workspace["id"]),
            "catalog_revision_id": catalog_revision_id,
            "filter_hash": filter_hash,
            "sort_name": sort_name,
            "logical_name": logical_name,
            "file_id": file_id,
        }
        body = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        envelope = {
            "payload": payload,
            "checksum": hashlib.sha256(
                (body + "|" + str(context.manifest["manifest_hash"])).encode()
            ).hexdigest(),
        }
        encoded = json.dumps(
            envelope, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode()
        return base64.urlsafe_b64encode(encoded).rstrip(b"=").decode()

    def _decode_search_cursor(
        self,
        cursor: str,
        *,
        context: FileAuthorizationContext,
        catalog_revision_id: str,
        filter_hash: str,
    ) -> dict[str, str]:
        try:
            raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
            envelope = json.loads(raw)
            payload = envelope["payload"]
            body = json.dumps(
                payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
            )
            checksum = hashlib.sha256(
                (body + "|" + str(context.manifest["manifest_hash"])).encode()
            ).hexdigest()
            if (
                set(envelope) != {"payload", "checksum"}
                or not isinstance(payload, dict)
                or str(envelope["checksum"]) != checksum
                or payload.get("v") != 1
                or str(payload.get("snapshot_id") or "")
                != str(context.manifest["id"])
                or str(payload.get("workspace_id") or "")
                != str(context.workspace["id"])
                or str(payload.get("catalog_revision_id") or "")
                != catalog_revision_id
                or str(payload.get("filter_hash") or "") != filter_hash
            ):
                raise ValueError("cursor binding mismatch")
            values = {
                "sort_name": str(payload["sort_name"]),
                "logical_name": str(payload["logical_name"]),
                "file_id": str(payload["file_id"]),
            }
            if not all(values.values()):
                raise ValueError("cursor ordering key missing")
            return values
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise NonRetryableExecutionError(
                "Workspace search cursor is invalid",
                safe_message="工作区文件搜索游标无效",
                error_code="file_workspace_search_cursor_invalid",
            ) from exc

    @staticmethod
    def _utc_filter(value: object) -> str:
        if not value:
            return ""
        try:
            return to_utc_rfc3339(str(value)) or ""
        except ValueError as exc:
            raise NonRetryableExecutionError(
                "Workspace search time filter is invalid",
                safe_message="工作区文件搜索时间无效",
                error_code="file_tool_input_invalid",
            ) from exc

    @staticmethod
    def _metadata(row: dict[str, Any]) -> dict[str, Any]:
        payload = {
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
            "readability_status": str(row.get("readability_status") or "NOT_REQUIRED"),
        }
        return canonicalize_file_time_fields(payload)

    def _readability_status(self, version_id: str) -> str:
        row = self.repository.database.execute_one(
            """
            select coalesce((
                     select a.readability_status
                       from message_attachment_file_binding b
                       join message_attachment a on a.id = b.attachment_id
                      where b.version_id = ?
                      order by a.readability_updated_at desc, a.id desc
                      limit 1
                   ), 'NOT_REQUIRED') as readability_status
            """,
            (version_id,),
        )
        return str((row or {}).get("readability_status") or "NOT_REQUIRED")

    @staticmethod
    def _deny(code: str, safe_message: str) -> Never:
        raise NonRetryableExecutionError(
            "File Tool request denied",
            safe_message=safe_message,
            error_code=code,
        )


def _observed_at() -> str:
    return to_utc_rfc3339(datetime.now(UTC)) or ""
