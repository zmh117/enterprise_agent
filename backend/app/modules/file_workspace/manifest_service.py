from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any, cast

from app.modules.channel.domain.channel_event import ChannelFileReference
from app.modules.file_workspace.domain import (
    FileAction,
    FileOwner,
    RetentionPeriod,
    SnapshotSourceKind,
    WorkspaceOwnerType,
)
from app.modules.file_workspace.repository import FileWorkspaceRepository
from app.modules.file_workspace.workspace_service import TaskWorkspaceService
from app.shared.exceptions import NonRetryableExecutionError


MAX_TXT_BYTES = 15 * 1024 * 1024
REGULAR_ACTIONS = (
    FileAction.READ_METADATA,
    FileAction.MATERIALIZE,
    FileAction.EDIT,
    FileAction.COMMIT,
    FileAction.RETAIN,
    FileAction.DELIVER,
)
CONFLICT_ACTIONS = (
    FileAction.READ_METADATA,
    FileAction.MATERIALIZE,
    FileAction.EDIT,
    FileAction.COMMIT,
)


def is_task_txt_name(value: str) -> bool:
    return Path(value).suffix.lower() == ".txt"


def is_explicit_txt_output_request(message: str) -> bool:
    """Conservative first-phase signal; callers can pass an explicit flag."""

    normalized = " ".join(message.lower().split())
    if ".txt" not in normalized and "txt文件" not in normalized and "文本文件" not in normalized:
        return False
    return any(
        token in normalized
        for token in (
            "生成",
            "创建",
            "新建",
            "修改",
            "编辑",
            "保存",
            "写入",
            "generate",
            "create",
            "edit",
            "save",
            "write",
        )
    )


class JobFileManifestService:
    """Resolve a governed workspace and freeze one immutable per-Job manifest."""

    def __init__(
        self,
        repository: FileWorkspaceRepository,
        workspace_service: TaskWorkspaceService,
    ) -> None:
        self.repository = repository
        self.workspace_service = workspace_service

    def resolve_workspace(
        self,
        *,
        tenant_id: str,
        session_id: str,
        requester_id: str,
        conversation_type: str,
        enterprise_id: str,
        connector_id: str,
        conversation_id: str,
        sender_staff_id: str,
        publication_id: str,
        retention_period: str,
        attachments: tuple[object, ...],
        file_references: tuple[ChannelFileReference, ...],
        requests_file_output: bool,
    ) -> dict[str, Any] | None:
        has_txt_input = any(
            is_task_txt_name(str(getattr(item, "file_name", ""))) for item in attachments
        ) or bool(file_references)
        active = self.repository.get_active_workspace(session_id)
        if active is None and not (has_txt_input or requests_file_output):
            return None
        if not all((tenant_id, publication_id, requester_id)):
            raise NonRetryableExecutionError(
                "Task file workspace provenance is incomplete",
                safe_message="任务文件工作区身份或发布信息不完整",
                error_code="file_workspace_provenance_incomplete",
            )
        try:
            period = RetentionPeriod(retention_period or "WEEK")
        except ValueError as exc:
            raise NonRetryableExecutionError(
                "Task file retention period is invalid",
                safe_message="任务文件工作区保留策略无效",
                error_code="file_workspace_retention_invalid",
            ) from exc
        owner = self._owner(
            requester_id=requester_id,
            conversation_type=conversation_type,
            enterprise_id=enterprise_id,
            connector_id=connector_id,
            conversation_id=conversation_id,
            sender_staff_id=sender_staff_id,
        )
        workspace = self.workspace_service.resolve_for_request(
            tenant_id=tenant_id,
            session_id=session_id,
            owner=owner,
            publication_id=publication_id,
            retention_period=period,
            actor_id=requester_id,
            has_file_input=has_txt_input,
            requests_file_output=requests_file_output,
        )
        if workspace is None:
            return None
        owner_type, user_id, owner_enterprise, owner_connector, owner_conversation = (
            owner.database_values()
        )
        expected = {
            "tenant_id": tenant_id,
            "business_application_publication_id": publication_id,
            "owner_type": owner_type,
            "owner_user_id": user_id,
            "owner_enterprise_id": owner_enterprise,
            "owner_connector_id": owner_connector,
            "owner_conversation_id": owner_conversation,
        }
        if any(str(workspace.get(key) or "") != value for key, value in expected.items()):
            raise NonRetryableExecutionError(
                "Active task workspace does not match the current request boundary",
                safe_message="当前任务工作区与会话身份不匹配",
                error_code="file_workspace_boundary_mismatch",
            )
        return cast(dict[str, Any], workspace)

    def register_request(
        self,
        *,
        job_id: str,
        workspace: dict[str, Any],
        requester_id: str,
        publication_id: str,
        file_references: tuple[ChannelFileReference, ...],
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self.repository.register_job_file_request(
                job_id=job_id,
                workspace_id=str(workspace["id"]),
                tenant_id=str(workspace["tenant_id"]),
                principal_user_id=requester_id,
                publication_id=publication_id,
                retention_period=RetentionPeriod(str(workspace["retention_period"])),
                explicit_references=(
                    {"file_id": item.file_id, "version_id": item.version_id}
                    for item in file_references
                ),
            ),
        )

    def finalize(self, job_id: str) -> dict[str, Any] | None:
        existing = self.repository.database.execute_one(
            "select id from agent_job_file_snapshot where job_id = ?", (job_id,)
        )
        if existing is not None:
            return cast(dict[str, Any], self.repository.get_job_snapshot(job_id))
        request = self.repository.database.execute_one(
            "select job_id from agent_job_file_request where job_id = ?", (job_id,)
        )
        if request is None:
            return None
        with self.repository.database.unit_of_work():
            pending = self.repository.get_job_file_request(job_id)
            workspace = self.repository.get_workspace(str(pending["workspace_id"]))
            self._require_request_boundary(pending, workspace)
            items = self._manifest_items(job_id, pending, workspace)
            canonical = [self._canonical_item(item) for item in items]
            manifest_hash = hashlib.sha256(
                json.dumps(
                    canonical,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            snapshot = self.repository.create_job_snapshot(
                snapshot_id=f"file_snapshot_{uuid.uuid4().hex}",
                job_id=job_id,
                workspace_id=str(workspace["id"]),
                tenant_id=str(workspace["tenant_id"]),
                principal_user_id=str(pending["principal_user_id"]),
                publication_id=str(pending["business_application_publication_id"]),
                retention_period=RetentionPeriod(str(pending["retention_period"])),
                manifest_hash=manifest_hash,
                items=canonical,
            )
            self.repository.finalize_job_file_request(job_id)
            return cast(dict[str, Any], snapshot)

    def runtime_manifest(self, job_id: str) -> dict[str, Any]:
        """Project the immutable Job snapshot into the bounded Runtime contract."""

        snapshot = self.repository.get_job_snapshot(job_id)
        projected: list[dict[str, Any]] = []
        for item in snapshot.get("items") or []:
            try:
                actions = json.loads(str(item.get("allowed_actions_json") or "[]"))
            except json.JSONDecodeError as exc:
                raise NonRetryableExecutionError(
                    "Job File Manifest actions are invalid",
                    safe_message="任务文件清单无效",
                    error_code="file_manifest_invalid",
                ) from exc
            if not isinstance(actions, list) or any(
                not isinstance(action, str) for action in actions
            ):
                raise NonRetryableExecutionError(
                    "Job File Manifest actions are invalid",
                    safe_message="任务文件清单无效",
                    error_code="file_manifest_invalid",
                )
            projected.append(
                {
                    "file_id": str(item["file_id"]),
                    "version_id": str(item["version_id"]),
                    "display_name": str(item["display_name"]),
                    "source_kind": str(item["source_kind"]),
                    "allowed_actions": actions,
                    "auto_materialize": bool(item.get("auto_materialize")),
                    "conflict_candidate": bool(item.get("conflict_candidate")),
                }
            )
        return {
            "schema_version": int(snapshot.get("schema_version") or 1),
            "manifest_hash": str(snapshot["manifest_hash"]),
            "items": projected,
        }

    def has_pending_txt_attachments(self, job_id: str) -> bool:
        row = self.repository.database.execute_one(
            """
            select count(*) as value from message_attachment
             where job_id = ? and lower(file_name) like ?
               and status not in ('READY', 'REJECTED', 'FAILED', 'stored_not_interpreted')
            """,
            (job_id, "%.txt"),
        )
        return bool(int((row or {}).get("value") or 0))

    @staticmethod
    def _owner(
        *,
        requester_id: str,
        conversation_type: str,
        enterprise_id: str,
        connector_id: str,
        conversation_id: str,
        sender_staff_id: str,
    ) -> FileOwner:
        if conversation_type == "group":
            if not sender_staff_id:
                raise NonRetryableExecutionError(
                    "DingTalk group file request is missing actual senderStaffId",
                    safe_message="无法验证当前群消息发送人",
                    error_code="file_group_sender_missing",
                )
            return FileOwner(
                WorkspaceOwnerType.GROUP_CONVERSATION,
                enterprise_id=enterprise_id,
                connector_id=connector_id,
                conversation_id=conversation_id,
            )
        return FileOwner(WorkspaceOwnerType.PRIVATE_USER, user_id=requester_id)

    @staticmethod
    def _canonical_item(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "file_id": str(item["file_id"]),
            "version_id": str(item["version_id"]),
            "display_name": str(item["display_name"]),
            "source_kind": str(item["source_kind"]),
            "allowed_actions": [str(value) for value in item["allowed_actions"]],
            "auto_materialize": bool(item.get("auto_materialize")),
            "conflict_candidate": bool(item.get("conflict_candidate")),
        }

    def _manifest_items(
        self,
        job_id: str,
        request: dict[str, Any],
        workspace: dict[str, Any],
    ) -> list[dict[str, Any]]:
        workspace_id = str(workspace["id"])
        regular = self.repository.database.execute(
            """
            select wf.file_id, wf.selected_version_id as version_id,
                   wf.logical_name as display_name, f.tenant_id, f.owner_type,
                   f.owner_user_id, f.owner_enterprise_id, f.owner_connector_id,
                   f.owner_conversation_id, f.status as file_status,
                   v.status as version_status, v.media_type, v.encoding,
                   v.size_bytes
              from task_workspace_file wf
              join managed_file f on f.id = wf.file_id
              join managed_file_version v on v.id = wf.selected_version_id
             where wf.workspace_id = ? and wf.status = 'ACTIVE'
             order by wf.logical_name, wf.file_id
            """,
            (workspace_id,),
        )
        by_identity: dict[tuple[str, str], dict[str, Any]] = {}
        for row in regular:
            self._require_file_boundary(row, workspace)
            if not self._eligible_txt(row):
                continue
            by_identity[(str(row["file_id"]), str(row["version_id"]))] = self._item(
                row,
                source_kind=SnapshotSourceKind.WORKSPACE,
                auto_materialize=False,
            )

        explicit = request.get("explicit_references") or []
        for reference in explicit:
            if not isinstance(reference, dict):
                self._invalid_reference()
            row = self._reference_row(
                workspace_id=workspace_id,
                file_id=str(reference.get("file_id") or ""),
                version_id=str(reference.get("version_id") or ""),
            )
            if row is None:
                self._invalid_reference()
            assert row is not None
            self._require_file_boundary(row, workspace)
            if not self._eligible_txt(row):
                self._invalid_reference()
            by_identity[(str(row["file_id"]), str(row["version_id"]))] = self._item(
                row,
                source_kind=SnapshotSourceKind.EXPLICIT_REFERENCE,
                auto_materialize=True,
                conflict_candidate=bool(row.get("conflict_candidate")),
            )

        txt_attachments = self.repository.database.execute(
            """
            select a.id as attachment_id, a.status as attachment_status,
                   a.file_name as attachment_name, b.file_id, b.version_id,
                   wf.logical_name as display_name, f.tenant_id, f.owner_type,
                   f.owner_user_id, f.owner_enterprise_id, f.owner_connector_id,
                   f.owner_conversation_id, f.status as file_status,
                   v.status as version_status, v.media_type, v.encoding,
                   v.size_bytes
              from message_attachment a
              left join message_attachment_file_binding b on b.attachment_id = a.id
              left join task_workspace_file wf
                on wf.workspace_id = ? and wf.file_id = b.file_id and wf.status = 'ACTIVE'
              left join managed_file f on f.id = b.file_id
              left join managed_file_version v on v.id = b.version_id
             where a.job_id = ? and lower(a.file_name) like ?
             order by a.ordinal
            """,
            (workspace_id, job_id, "%.txt"),
        )
        for row in txt_attachments:
            status = str(row.get("attachment_status") or "")
            if status not in {"READY", "REJECTED", "FAILED", "stored_not_interpreted"}:
                raise NonRetryableExecutionError(
                    "Task TXT attachment is still pending",
                    safe_message="文本附件尚未完成导入",
                    error_code="file_inputs_pending",
                )
            if status != "READY":
                continue
            if not all((row.get("file_id"), row.get("version_id"), row.get("display_name"))):
                raise NonRetryableExecutionError(
                    "Task TXT attachment was not imported through File Service",
                    safe_message="文本附件导入尚未完成",
                    error_code="file_attachment_not_imported",
                )
            self._require_file_boundary(row, workspace)
            if not self._eligible_txt(row):
                raise NonRetryableExecutionError(
                    "Imported task TXT attachment is invalid",
                    safe_message="文本附件不符合任务工作区要求",
                    error_code="file_attachment_invalid",
                )
            by_identity[(str(row["file_id"]), str(row["version_id"]))] = self._item(
                row,
                source_kind=SnapshotSourceKind.CURRENT_MESSAGE,
                auto_materialize=True,
            )

        conflicts = self.repository.database.execute(
            """
            select c.file_id, c.candidate_version_id as version_id,
                   wf.logical_name as display_name, f.tenant_id, f.owner_type,
                   f.owner_user_id, f.owner_enterprise_id, f.owner_connector_id,
                   f.owner_conversation_id, f.status as file_status,
                   v.status as version_status, v.media_type, v.encoding,
                   v.size_bytes
              from file_conflict_candidate c
              join task_workspace_file wf
                on wf.workspace_id = ? and wf.file_id = c.file_id and wf.status = 'ACTIVE'
              join managed_file f on f.id = c.file_id
              join managed_file_version v on v.id = c.candidate_version_id
             where c.status = 'OPEN'
             order by c.created_at, c.id
            """,
            (workspace_id,),
        )
        for row in conflicts:
            self._require_file_boundary(row, workspace)
            if self._eligible_txt(row):
                by_identity[(str(row["file_id"]), str(row["version_id"]))] = self._item(
                    row,
                    source_kind=SnapshotSourceKind.CONFLICT,
                    auto_materialize=False,
                    conflict_candidate=True,
                )
        items = list(by_identity.values())
        job = (
            self.repository.database.execute_one(
                "select business_application_route_decision_json from agent_job where id = ?",
                (job_id,),
            )
            or {}
        )
        try:
            route_decision = json.loads(
                str(job.get("business_application_route_decision_json") or "{}")
            )
        except json.JSONDecodeError:
            route_decision = {}
        features = (
            route_decision.get("task_file_features") if isinstance(route_decision, dict) else {}
        )
        edit_enabled = bool(
            isinstance(features, dict) and features.get("runtime_file_edit_enabled")
        )
        if not edit_enabled:
            for item in items:
                item["allowed_actions"] = [
                    action
                    for action in item["allowed_actions"]
                    if action not in {FileAction.EDIT.value, FileAction.COMMIT.value}
                ]
        return items

    def _reference_row(
        self, *, workspace_id: str, file_id: str, version_id: str
    ) -> dict[str, Any] | None:
        if not file_id or not version_id:
            return None
        return cast(
            dict[str, Any] | None,
            self.repository.database.execute_one(
                """
            select wf.file_id, v.id as version_id, wf.logical_name as display_name,
                   f.tenant_id, f.owner_type, f.owner_user_id,
                   f.owner_enterprise_id, f.owner_connector_id,
                   f.owner_conversation_id, f.status as file_status,
                   v.status as version_status, v.media_type, v.encoding,
                   v.size_bytes,
                   case when c.candidate_version_id is null then 0 else 1 end
                     as conflict_candidate
              from task_workspace_file wf
              join managed_file f on f.id = wf.file_id
              join managed_file_version v on v.file_id = wf.file_id and v.id = ?
              left join file_conflict_candidate c
                on c.file_id = wf.file_id and c.candidate_version_id = v.id
               and c.status = 'OPEN'
             where wf.workspace_id = ? and wf.file_id = ? and wf.status = 'ACTIVE'
               and (wf.selected_version_id = v.id or c.candidate_version_id = v.id)
            """,
                (version_id, workspace_id, file_id),
            ),
        )

    @staticmethod
    def _item(
        row: dict[str, Any],
        *,
        source_kind: SnapshotSourceKind,
        auto_materialize: bool,
        conflict_candidate: bool = False,
    ) -> dict[str, Any]:
        return {
            "file_id": str(row["file_id"]),
            "version_id": str(row["version_id"]),
            "display_name": str(row["display_name"]),
            "source_kind": source_kind.value,
            "allowed_actions": [
                action.value
                for action in (CONFLICT_ACTIONS if conflict_candidate else REGULAR_ACTIONS)
            ],
            "auto_materialize": auto_materialize,
            "conflict_candidate": conflict_candidate,
        }

    @staticmethod
    def _eligible_txt(row: dict[str, Any]) -> bool:
        return (
            is_task_txt_name(str(row.get("display_name") or ""))
            and str(row.get("media_type") or "").split(";", 1)[0].strip().lower() == "text/plain"
            and str(row.get("encoding") or "").lower() == "utf-8"
            and 0 <= int(row.get("size_bytes") or 0) <= MAX_TXT_BYTES
            and str(row.get("file_status") or "") == "ACTIVE"
            and str(row.get("version_status") or "") in {"AVAILABLE", "CONFLICT"}
        )

    @staticmethod
    def _require_request_boundary(request: dict[str, Any], workspace: dict[str, Any]) -> None:
        if (
            str(workspace.get("status")) != "ACTIVE"
            or str(request.get("tenant_id")) != str(workspace.get("tenant_id"))
            or str(request.get("business_application_publication_id"))
            != str(workspace.get("business_application_publication_id"))
            or str(request.get("retention_period")) != str(workspace.get("retention_period"))
        ):
            raise NonRetryableExecutionError(
                "Job file request no longer matches its workspace",
                safe_message="任务文件工作区已失效",
                error_code="file_workspace_expired",
            )

    @staticmethod
    def _require_file_boundary(row: dict[str, Any], workspace: dict[str, Any]) -> None:
        fields = (
            "tenant_id",
            "owner_type",
            "owner_user_id",
            "owner_enterprise_id",
            "owner_connector_id",
            "owner_conversation_id",
        )
        if any(str(row.get(field) or "") != str(workspace.get(field) or "") for field in fields):
            raise NonRetryableExecutionError(
                "Managed file owner boundary does not match workspace",
                safe_message="当前任务无权引用该文件",
                error_code="file_owner_boundary_denied",
            )

    @staticmethod
    def _invalid_reference() -> None:
        raise NonRetryableExecutionError(
            "Explicit file reference is not available in this workspace",
            safe_message="当前任务无权引用该文件",
            error_code="file_reference_denied",
        )
