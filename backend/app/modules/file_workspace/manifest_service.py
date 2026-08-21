from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Never

from app.modules.channel.domain.channel_event import ChannelFileReference
from app.modules.file_workspace.clock import (
    canonicalize_file_time_fields,
    to_utc_rfc3339,
)
from app.modules.file_workspace.domain import (
    DOCUMENT_MANIFEST_ACTIONS,
    GOVERNED_DOCUMENT_FORMATS,
    FileAction,
    FileOwner,
    RetentionPeriod,
    SnapshotSourceKind,
    WorkspaceOwnerType,
)
from app.modules.file_workspace.repository import FileWorkspaceRepository
from app.modules.file_workspace.text_format_policy import (
    MAX_TEXT_BYTES,
    FileFormatPolicyVersion,
    TextFormatCode,
    get_text_format_policy,
    normalize_file_format_policy_version,
    text_format_for_name,
)
from app.modules.file_workspace.workspace_service import TaskWorkspaceService
from app.shared.exceptions import NonRetryableExecutionError


CONFLICT_ACTIONS = (
    FileAction.READ_METADATA,
    FileAction.MATERIALIZE,
    FileAction.EDIT,
    FileAction.COMMIT,
)
TXT_OUTPUT_FORMAT_MARKERS = ("txt", "文本文件", "文本文档")
MARKDOWN_OUTPUT_FORMAT_MARKERS = (
    ".md",
    "md文件",
    "md文档",
    "markdown文件",
    "markdown文档",
    "markdownfile",
    "markdowndocument",
)
DOCUMENT_INPUT_SUFFIXES = frozenset(
    {".pdf", ".docx", ".pptx", ".xlsx", ".png", ".jpg", ".jpeg", ".webp"}
)
TXT_OUTPUT_ACTION_MARKERS = (
    "生成",
    "创建",
    "新建",
    "修改",
    "编辑",
    "保存",
    "写入",
    "制作",
    "绘制",
    "画",
    "输出",
    "导出",
    "做",
    "generate",
    "create",
    "edit",
    "save",
    "write",
    "make",
    "draw",
    "export",
)


def is_task_text_name(value: str, *, policy_version: object) -> bool:
    try:
        text_format_for_name(value, policy_version=policy_version)
    except NonRetryableExecutionError:
        return False
    return True


def is_task_txt_name(value: str) -> bool:
    """Legacy text-v1 compatibility helper; new callers pass a policy."""
    return is_task_text_name(value, policy_version=FileFormatPolicyVersion.TEXT_V1)


def is_explicit_txt_output_request(message: str) -> bool:
    """Legacy text-v1 compatibility helper."""

    return is_explicit_text_output_request(
        message,
        policy_version=FileFormatPolicyVersion.TEXT_V1,
    )


def is_explicit_text_output_request(message: str, *, policy_version: object) -> bool:
    """Conservative format+action signal for pre-creating a workspace."""

    normalized = "".join(message.lower().split())
    format_markers = list(TXT_OUTPUT_FORMAT_MARKERS)
    if normalize_file_format_policy_version(policy_version) is FileFormatPolicyVersion.TEXT_V2:
        format_markers.extend(MARKDOWN_OUTPUT_FORMAT_MARKERS)
    if not any(marker in normalized for marker in format_markers):
        return False
    return any(marker in normalized for marker in TXT_OUTPUT_ACTION_MARKERS)


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
        file_format_policy_version: object = FileFormatPolicyVersion.TEXT_V1,
        force_create: bool = False,
    ) -> dict[str, Any] | None:
        policy_version = normalize_file_format_policy_version(file_format_policy_version)
        has_text_input = any(
            is_task_text_name(
                str(getattr(item, "file_name", "")),
                policy_version=policy_version,
            )
            or Path(str(getattr(item, "file_name", ""))).suffix.lower() in DOCUMENT_INPUT_SUFFIXES
            for item in attachments
        ) or bool(file_references)
        active = self.repository.get_active_workspace(session_id)
        if active is None and not (has_text_input or requests_file_output or force_create):
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
            has_file_input=has_text_input or force_create,
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
        return workspace

    def register_request(
        self,
        *,
        job_id: str,
        workspace: dict[str, Any],
        requester_id: str,
        publication_id: str,
        file_references: tuple[ChannelFileReference, ...],
        file_format_policy_version: object = FileFormatPolicyVersion.TEXT_V1,
    ) -> dict[str, Any]:
        return self.repository.register_job_file_request(
            job_id=job_id,
            workspace_id=str(workspace["id"]),
            tenant_id=str(workspace["tenant_id"]),
            principal_user_id=requester_id,
            publication_id=publication_id,
            retention_period=RetentionPeriod(str(workspace["retention_period"])),
            file_format_policy_version=normalize_file_format_policy_version(
                file_format_policy_version
            ).value,
            explicit_references=(
                {
                    "file_id": item.file_id,
                    "version_id": item.version_id,
                    "auto_materialize": item.auto_materialize,
                }
                for item in file_references
            ),
        )

    def finalize(self, job_id: str) -> dict[str, Any] | None:
        existing = self.repository.database.execute_one(
            "select id from agent_job_file_snapshot where job_id = ?", (job_id,)
        )
        if existing is not None:
            return self.repository.get_job_snapshot(job_id)
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
            policy_version = normalize_file_format_policy_version(
                pending.get("file_format_policy_version")
            ).value
            manifest_hash = hashlib.sha256(
                json.dumps(
                    {
                        "schema_version": 4,
                        "file_format_policy_version": policy_version,
                        "items": canonical,
                    },
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
                file_format_policy_version=policy_version,
                manifest_hash=manifest_hash,
                items=canonical,
            )
            self.repository.finalize_job_file_request(job_id)
            return snapshot

    def runtime_manifest(self, job_id: str) -> dict[str, Any]:
        """Project the immutable Job snapshot into the bounded Runtime contract."""

        snapshot = self.repository.get_job_snapshot(job_id)
        policy_version = normalize_file_format_policy_version(
            snapshot.get("file_format_policy_version")
        )
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
            try:
                frozen_actions = {FileAction(action) for action in actions}
            except ValueError as exc:
                raise NonRetryableExecutionError(
                    "Job File Manifest action is unknown",
                    safe_message="任务文件清单无效",
                    error_code="file_manifest_actions_invalid",
                ) from exc
            representation_id = item.get("representation_id")
            format_code = str(item.get("format_code") or "TXT")
            representation: dict[str, Any] = {}
            if representation_id:
                if (
                    format_code not in GOVERNED_DOCUMENT_FORMATS
                    or frozen_actions != DOCUMENT_MANIFEST_ACTIONS
                    or str(item.get("representation_kind") or "") != "MARKDOWN"
                    or str(item.get("representation_format_code") or "") != "MARKDOWN"
                    or int(item.get("representation_size_bytes") or 0) < 1
                    or len(str(item.get("representation_sha256") or "")) != 64
                    or not item.get("representation_created_at")
                ):
                    raise NonRetryableExecutionError(
                        "Job File Manifest representation is invalid",
                        safe_message="任务文件清单无效",
                        error_code="file_manifest_invalid",
                    )
                representation = {
                    "representation_id": str(representation_id),
                    "representation_kind": "MARKDOWN",
                    "representation_size_bytes": int(item["representation_size_bytes"]),
                    "representation_sha256": str(item["representation_sha256"]),
                    "representation_format_code": "MARKDOWN",
                    "representation_created_at": str(item["representation_created_at"]),
                }
            elif format_code in GOVERNED_DOCUMENT_FORMATS:
                if frozen_actions != DOCUMENT_MANIFEST_ACTIONS:
                    raise NonRetryableExecutionError(
                        "Job File Manifest actions exceed the frozen format policy",
                        safe_message="任务文件清单无效",
                        error_code="file_manifest_actions_invalid",
                    )
            else:
                definition = get_text_format_policy(policy_version).by_code(format_code)
                if not frozen_actions.issubset(definition.actions):
                    raise NonRetryableExecutionError(
                        "Job File Manifest actions exceed the frozen format policy",
                        safe_message="任务文件清单无效",
                        error_code="file_manifest_actions_invalid",
                    )
                format_code = definition.code.value
            projected.append(
                {
                    "file_id": str(item["file_id"]),
                    "version_id": str(item["version_id"]),
                    "display_name": str(item["display_name"]),
                    "format_code": format_code,
                    "source_kind": str(item["source_kind"]),
                    "allowed_actions": actions,
                    "auto_materialize": bool(item.get("auto_materialize")),
                    "conflict_candidate": bool(item.get("conflict_candidate")),
                    "source_received_at": (
                        str(item.get("source_received_at"))
                        if item.get("source_received_at")
                        else None
                    ),
                    "version_created_at": str(item.get("version_created_at") or ""),
                    **representation,
                }
            )
        canonical = [self._canonical_item(item) for item in projected]
        schema_version = int(snapshot.get("schema_version") or 1)
        if schema_version >= 4:
            hash_value: object = {
                "schema_version": 4,
                "file_format_policy_version": policy_version.value,
                "items": canonical,
            }
        elif schema_version >= 3:
            for canonical_item in canonical:
                for key in (
                    "representation_id",
                    "representation_kind",
                    "representation_size_bytes",
                    "representation_sha256",
                    "representation_format_code",
                    "representation_created_at",
                ):
                    canonical_item.pop(key, None)
            hash_value = {
                "schema_version": 3,
                "file_format_policy_version": policy_version.value,
                "items": canonical,
            }
        else:
            for canonical_item in canonical:
                canonical_item.pop("format_code", None)
                for key in tuple(canonical_item):
                    if key.startswith("representation_"):
                        canonical_item.pop(key, None)
            hash_value = canonical
        actual_hash = hashlib.sha256(
            json.dumps(
                hash_value,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if actual_hash != str(snapshot.get("manifest_hash") or ""):
            raise NonRetryableExecutionError(
                "Job File Manifest hash does not match",
                safe_message="任务文件清单无效",
                error_code="file_manifest_invalid",
            )
        readability_rows = self.repository.database.execute(
            """
            select file_name, readability_status, readability_error_code
              from message_attachment
             where job_id = ? and readability_status in ('PARTIAL', 'NO_TEXT', 'UNAVAILABLE')
             order by ordinal, id
            """,
            (job_id,),
        )
        return {
            "schema_version": schema_version,
            "file_format_policy_version": policy_version.value,
            "manifest_hash": str(snapshot["manifest_hash"]),
            "observed_at": to_utc_rfc3339(snapshot.get("created_at")) or "",
            "items": [canonicalize_file_time_fields(item) for item in projected],
            **(
                {
                    "readability_notices": [
                        {
                            "file_name": str(row.get("file_name") or "")[:255],
                            "status": str(row["readability_status"]),
                            "error_code": str(row.get("readability_error_code") or "")[:128],
                        }
                        for row in readability_rows
                    ]
                }
                if readability_rows
                else {}
            ),
        }

    def has_pending_text_attachments(self, job_id: str) -> bool:
        request = (
            self.repository.database.execute_one(
                "select file_format_policy_version from agent_job_file_request where job_id = ?",
                (job_id,),
            )
            or {}
        )
        policy_version = normalize_file_format_policy_version(
            request.get("file_format_policy_version")
        )
        rows = self.repository.database.execute(
            """
            select file_name, status from message_attachment
             where job_id = ?
            """,
            (job_id,),
        )
        return any(
            is_task_text_name(
                str(row.get("file_name") or ""),
                policy_version=policy_version,
            )
            and str(row.get("status") or "")
            not in {"READY", "REJECTED", "FAILED", "stored_not_interpreted"}
            for row in rows
        )

    def has_pending_txt_attachments(self, job_id: str) -> bool:
        """Compatibility alias; behavior follows the request's frozen policy."""
        return self.has_pending_text_attachments(job_id)

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
            "format_code": str(item.get("format_code") or "TXT"),
            "source_kind": str(item["source_kind"]),
            "allowed_actions": [str(value) for value in item["allowed_actions"]],
            "auto_materialize": bool(item.get("auto_materialize")),
            "conflict_candidate": bool(item.get("conflict_candidate")),
            "source_received_at": item.get("source_received_at"),
            "version_created_at": str(item["version_created_at"]),
            "representation_id": item.get("representation_id"),
            "representation_kind": item.get("representation_kind"),
            "representation_size_bytes": item.get("representation_size_bytes"),
            "representation_sha256": item.get("representation_sha256"),
            "representation_format_code": item.get("representation_format_code"),
            "representation_created_at": item.get("representation_created_at"),
        }

    def _manifest_items(
        self,
        job_id: str,
        request: dict[str, Any],
        workspace: dict[str, Any],
    ) -> list[dict[str, Any]]:
        workspace_id = str(workspace["id"])
        policy_version = normalize_file_format_policy_version(
            request.get("file_format_policy_version")
        )
        regular = self.repository.database.execute(
            """
            select wf.file_id, wf.selected_version_id as version_id,
                   wf.logical_name as display_name, f.tenant_id, f.owner_type,
                   f.owner_user_id, f.owner_enterprise_id, f.owner_connector_id,
                   f.owner_conversation_id, f.status as file_status,
                   f.format_code as file_format_code,
                   v.status as version_status, v.format_code as version_format_code,
                   v.media_type, v.encoding,
                   v.size_bytes, f.source_received_at,
                   v.created_at as version_created_at
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
            identity = (str(row["file_id"]), str(row["version_id"]))
            if self._eligible_text(row, policy_version=policy_version):
                by_identity[identity] = self._item(
                    row,
                    source_kind=SnapshotSourceKind.WORKSPACE,
                    auto_materialize=False,
                    policy_version=policy_version,
                )
            elif self._eligible_document(row):
                by_identity[identity] = self._document_item(
                    row,
                    source_kind=SnapshotSourceKind.WORKSPACE,
                    auto_materialize=False,
                )

        explicit = request.get("explicit_references") or []
        for reference in explicit:
            if not isinstance(reference, dict):
                self._invalid_reference()
            reference_row = self._reference_row(
                workspace_id=workspace_id,
                file_id=str(reference.get("file_id") or ""),
                version_id=str(reference.get("version_id") or ""),
            )
            historical = reference_row is None
            if reference_row is None:
                reference_row = self._retained_reference_row(
                    session_id=str(workspace.get("session_id") or ""),
                    file_id=str(reference.get("file_id") or ""),
                    version_id=str(reference.get("version_id") or ""),
                )
            if reference_row is None:
                self._invalid_reference()
            self._require_file_boundary(reference_row, workspace)
            identity = (str(reference_row["file_id"]), str(reference_row["version_id"]))
            auto_materialize = bool(reference.get("auto_materialize", True))
            if not self._content_available(reference_row):
                if not historical:
                    self._invalid_reference()
                by_identity[identity] = self._metadata_only_item(
                    reference_row,
                    source_kind=SnapshotSourceKind.EXPLICIT_REFERENCE,
                )
                continue
            if self._eligible_text(reference_row, policy_version=policy_version):
                item = self._item(
                    reference_row,
                    source_kind=SnapshotSourceKind.EXPLICIT_REFERENCE,
                    auto_materialize=auto_materialize,
                    conflict_candidate=bool(reference_row.get("conflict_candidate")),
                    policy_version=policy_version,
                )
            elif self._eligible_document(reference_row):
                item = self._document_item(
                    reference_row,
                    source_kind=SnapshotSourceKind.EXPLICIT_REFERENCE,
                    auto_materialize=auto_materialize,
                    conflict_candidate=bool(reference_row.get("conflict_candidate")),
                )
            else:
                self._invalid_reference()
            if historical:
                item["allowed_actions"] = [
                    action
                    for action in item["allowed_actions"]
                    if action not in {FileAction.EDIT.value, FileAction.COMMIT.value}
                ]
            by_identity[identity] = item

        text_attachments = self.repository.database.execute(
            """
            select a.id as attachment_id, a.status as attachment_status,
                   a.file_name as attachment_name, b.file_id, b.version_id,
                   wf.logical_name as display_name, f.tenant_id, f.owner_type,
                   f.owner_user_id, f.owner_enterprise_id, f.owner_connector_id,
                   f.owner_conversation_id, f.status as file_status,
                   f.format_code as file_format_code,
                   v.status as version_status, v.format_code as version_format_code,
                   v.media_type, v.encoding,
                   v.size_bytes, f.source_received_at,
                   v.created_at as version_created_at,
                   a.readability_status, a.readability_error_code,
                   r.id as representation_id, r.kind as representation_kind,
                   r.size_bytes as representation_size_bytes,
                   r.content_sha256 as representation_sha256,
                   r.created_at as representation_created_at
              from message_attachment a
              left join message_attachment_file_binding b on b.attachment_id = a.id
              left join task_workspace_file wf
                on wf.workspace_id = ? and wf.file_id = b.file_id and wf.status = 'ACTIVE'
              left join managed_file f on f.id = b.file_id
              left join managed_file_version v on v.id = b.version_id
              left join file_representation r
                on r.processing_run_id = a.file_processing_run_id
               and r.kind = 'MARKDOWN' and r.status = 'AVAILABLE'
             where a.job_id = ?
             order by a.ordinal
            """,
            (workspace_id, job_id),
        )
        for row in text_attachments:
            is_text = is_task_text_name(
                str(row.get("attachment_name") or ""),
                policy_version=policy_version,
            )
            is_document = str(row.get("readability_status") or "NOT_REQUIRED") != "NOT_REQUIRED"
            if not is_text and not is_document:
                continue
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
            if is_document:
                readability = str(row.get("readability_status") or "")
                if readability == "PENDING":
                    by_identity[(str(row["file_id"]), str(row["version_id"]))] = {
                        "file_id": str(row["file_id"]),
                        "version_id": str(row["version_id"]),
                        "display_name": str(row["display_name"]),
                        "format_code": str(row.get("file_format_code") or "PDF"),
                        "source_kind": SnapshotSourceKind.CURRENT_MESSAGE.value,
                        "allowed_actions": [
                            FileAction.READ_METADATA.value,
                            FileAction.RETAIN.value,
                            FileAction.DELIVER.value,
                        ],
                        "auto_materialize": False,
                        "conflict_candidate": False,
                        "source_received_at": str(row.get("source_received_at"))
                        if row.get("source_received_at")
                        else None,
                        "version_created_at": str(row["version_created_at"]),
                        "representation_id": None,
                        "representation_kind": None,
                        "representation_size_bytes": None,
                        "representation_sha256": None,
                        "representation_format_code": None,
                        "representation_created_at": None,
                    }
                    continue
                if readability not in {"AVAILABLE", "PARTIAL"}:
                    continue
                if not row.get("representation_id"):
                    raise NonRetryableExecutionError(
                        "Document representation is unavailable",
                        safe_message="文档可读表示不可用",
                        error_code="file_representation_unavailable",
                    )
                self._require_file_boundary(row, workspace)
                item = {
                    "file_id": str(row["file_id"]),
                    "version_id": str(row["version_id"]),
                    "display_name": str(row["display_name"]),
                    "format_code": str(row.get("file_format_code") or "PDF"),
                    "source_kind": SnapshotSourceKind.CURRENT_MESSAGE.value,
                    "allowed_actions": [
                        FileAction.READ_METADATA.value,
                        FileAction.RETAIN.value,
                        FileAction.DELIVER.value,
                    ],
                    "auto_materialize": True,
                    "conflict_candidate": False,
                    "source_received_at": str(row.get("source_received_at"))
                    if row.get("source_received_at")
                    else None,
                    "version_created_at": str(row["version_created_at"]),
                    "representation_id": str(row["representation_id"]),
                    "representation_kind": "MARKDOWN",
                    "representation_size_bytes": int(row["representation_size_bytes"]),
                    "representation_sha256": str(row["representation_sha256"]),
                    "representation_format_code": "MARKDOWN",
                    "representation_created_at": str(row["representation_created_at"]),
                }
                by_identity[(str(row["file_id"]), str(row["version_id"]))] = item
                continue
            if not self._eligible_text(row, policy_version=policy_version):
                raise NonRetryableExecutionError(
                    "Imported task TXT attachment is invalid",
                    safe_message="文本附件不符合任务工作区要求",
                    error_code="file_attachment_invalid",
                )
            by_identity[(str(row["file_id"]), str(row["version_id"]))] = self._item(
                row,
                source_kind=SnapshotSourceKind.CURRENT_MESSAGE,
                auto_materialize=True,
                policy_version=policy_version,
            )

        conflicts = self.repository.database.execute(
            """
            select c.file_id, c.candidate_version_id as version_id,
                   wf.logical_name as display_name, f.tenant_id, f.owner_type,
                   f.owner_user_id, f.owner_enterprise_id, f.owner_connector_id,
                   f.owner_conversation_id, f.status as file_status,
                   f.format_code as file_format_code,
                   v.status as version_status, v.format_code as version_format_code,
                   v.media_type, v.encoding,
                   v.size_bytes, f.source_received_at,
                   v.created_at as version_created_at
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
            identity = (str(row["file_id"]), str(row["version_id"]))
            if self._eligible_text(row, policy_version=policy_version):
                by_identity[identity] = self._item(
                    row,
                    source_kind=SnapshotSourceKind.CONFLICT,
                    auto_materialize=False,
                    conflict_candidate=True,
                    policy_version=policy_version,
                )
            elif self._eligible_document(row):
                by_identity[identity] = self._document_item(
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
        return self.repository.database.execute_one(
            """
            select wf.file_id, v.id as version_id, wf.logical_name as display_name,
                   f.tenant_id, f.owner_type, f.owner_user_id,
                   f.owner_enterprise_id, f.owner_connector_id,
                   f.owner_conversation_id, f.status as file_status,
                   f.format_code as file_format_code,
                   v.status as version_status, v.format_code as version_format_code,
                   v.media_type, v.encoding,
                   v.size_bytes, f.source_received_at,
                   v.created_at as version_created_at,
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
        )

    def _retained_reference_row(
        self, *, session_id: str, file_id: str, version_id: str
    ) -> dict[str, Any] | None:
        if not session_id or not file_id or not version_id:
            return None
        now = datetime.now(UTC).isoformat()
        return self.repository.database.execute_one(
            """
            select f.id as file_id, v.id as version_id,
                   coalesce(
                     (
                       select wf.logical_name
                         from task_workspace_file wf
                        where wf.file_id = f.id
                        order by case wf.status when 'ACTIVE' then 0 else 1 end,
                                 wf.updated_at desc
                        limit 1
                     ),
                     f.display_name
                   ) as display_name,
                   f.tenant_id, f.owner_type, f.owner_user_id,
                   f.owner_enterprise_id, f.owner_connector_id,
                   f.owner_conversation_id, f.status as file_status,
                   f.format_code as file_format_code,
                   v.status as version_status, v.format_code as version_format_code,
                   v.media_type, v.encoding,
                   v.size_bytes, f.source_received_at,
                   v.created_at as version_created_at,
                   0 as conflict_candidate
              from managed_file f
              join managed_file_version v on v.file_id = f.id and v.id = ?
             where f.id = ?
               and v.status != 'DELETED'
               and f.status != 'DELETED'
               and (
                 exists (
                   select 1
                     from task_workspace tw
                     join task_workspace_file wf on wf.workspace_id = tw.id
                    where tw.session_id = ? and wf.file_id = f.id
                 )
                 or exists (
                   select 1
                     from message_attachment_file_binding b
                     join message_attachment a on a.id = b.attachment_id
                     join agent_message m on m.id = a.message_id
                    where b.version_id = v.id and m.session_id = ?
                 )
               )
               and (
                 v.status = 'CONTENT_UNAVAILABLE'
                 or f.status = 'CONTENT_UNAVAILABLE'
                 or not exists (
                   select 1 from file_retention_fact r where r.version_id = v.id
                 )
                 or exists (
                   select 1 from file_retention_fact r
                    where r.version_id = v.id and r.expires_at > ?
                 )
               )
            """,
            (version_id, file_id, session_id, session_id, now),
        )

    @staticmethod
    def _content_available(row: dict[str, Any]) -> bool:
        return str(row.get("file_status") or "") == "ACTIVE" and str(
            row.get("version_status") or ""
        ) in {"AVAILABLE", "CONFLICT"}

    @staticmethod
    def _metadata_only_item(
        row: dict[str, Any],
        *,
        source_kind: SnapshotSourceKind,
    ) -> dict[str, Any]:
        format_code = str(row.get("file_format_code") or "TXT")
        if format_code in GOVERNED_DOCUMENT_FORMATS:
            allowed = [
                action.value for action in FileAction if action in DOCUMENT_MANIFEST_ACTIONS
            ]
        else:
            allowed = [FileAction.READ_METADATA.value]
        return {
            "file_id": str(row["file_id"]),
            "version_id": str(row["version_id"]),
            "display_name": str(row["display_name"]),
            "format_code": format_code,
            "source_kind": source_kind.value,
            "allowed_actions": allowed,
            "auto_materialize": False,
            "conflict_candidate": False,
            "source_received_at": (
                str(row.get("source_received_at")) if row.get("source_received_at") else None
            ),
            "version_created_at": str(row["version_created_at"]),
        }

    @staticmethod
    def _item(
        row: dict[str, Any],
        *,
        source_kind: SnapshotSourceKind,
        auto_materialize: bool,
        conflict_candidate: bool = False,
        policy_version: object = FileFormatPolicyVersion.TEXT_V1,
    ) -> dict[str, Any]:
        format_code = TextFormatCode(str(row.get("file_format_code") or "TXT"))
        definition = get_text_format_policy(policy_version).by_code(format_code)
        allowed = definition.actions
        if conflict_candidate:
            allowed = allowed.intersection(CONFLICT_ACTIONS)
        return {
            "file_id": str(row["file_id"]),
            "version_id": str(row["version_id"]),
            "display_name": str(row["display_name"]),
            "format_code": format_code.value,
            "source_kind": source_kind.value,
            "allowed_actions": [action.value for action in FileAction if action in allowed],
            "auto_materialize": auto_materialize,
            "conflict_candidate": conflict_candidate,
            "source_received_at": (
                str(row.get("source_received_at")) if row.get("source_received_at") else None
            ),
            "version_created_at": str(row["version_created_at"]),
        }

    def _document_item(
        self,
        row: dict[str, Any],
        *,
        source_kind: SnapshotSourceKind,
        auto_materialize: bool,
        conflict_candidate: bool = False,
    ) -> dict[str, Any]:
        representation = self._latest_markdown_representation(str(row["version_id"]))
        ready = representation is not None
        item: dict[str, Any] = {
            "file_id": str(row["file_id"]),
            "version_id": str(row["version_id"]),
            "display_name": str(row["display_name"]),
            "format_code": str(row.get("file_format_code") or "PDF"),
            "source_kind": source_kind.value,
            "allowed_actions": [
                action.value for action in FileAction if action in DOCUMENT_MANIFEST_ACTIONS
            ],
            "auto_materialize": bool(auto_materialize and ready),
            "conflict_candidate": conflict_candidate,
            "source_received_at": (
                str(row.get("source_received_at")) if row.get("source_received_at") else None
            ),
            "version_created_at": str(row["version_created_at"]),
            "representation_id": None,
            "representation_kind": None,
            "representation_size_bytes": None,
            "representation_sha256": None,
            "representation_format_code": None,
            "representation_created_at": None,
        }
        if representation is None:
            return item
        item.update(
            {
                "representation_id": str(representation["representation_id"]),
                "representation_kind": "MARKDOWN",
                "representation_size_bytes": int(representation["representation_size_bytes"]),
                "representation_sha256": str(representation["representation_sha256"]),
                "representation_format_code": "MARKDOWN",
                "representation_created_at": str(representation["representation_created_at"]),
            }
        )
        return item

    def _latest_markdown_representation(self, version_id: str) -> dict[str, Any] | None:
        if not version_id:
            return None
        return self.repository.database.execute_one(
            """
            select id as representation_id,
                   size_bytes as representation_size_bytes,
                   content_sha256 as representation_sha256,
                   created_at as representation_created_at
              from file_representation
             where source_version_id = ? and kind = 'MARKDOWN'
               and status in ('AVAILABLE', 'PARTIAL')
               and coalesce(size_bytes, 0) > 0
               and length(coalesce(content_sha256, '')) = 64
             order by created_at desc
             limit 1
            """,
            (version_id,),
        )

    @staticmethod
    def _eligible_document(row: dict[str, Any]) -> bool:
        format_code = str(row.get("file_format_code") or "")
        return (
            format_code in GOVERNED_DOCUMENT_FORMATS
            and str(row.get("version_format_code") or "") == format_code
            and str(row.get("file_status") or "") == "ACTIVE"
            and str(row.get("version_status") or "") in {"AVAILABLE", "CONFLICT"}
        )

    @staticmethod
    def _eligible_text(row: dict[str, Any], *, policy_version: object) -> bool:
        try:
            definition = text_format_for_name(
                str(row.get("display_name") or ""),
                policy_version=policy_version,
            )
        except NonRetryableExecutionError:
            return False
        return (
            str(row.get("file_format_code") or "TXT") == definition.code.value
            and str(row.get("version_format_code") or "TXT") == definition.code.value
            and str(row.get("media_type") or "").split(";", 1)[0].strip().lower()
            == definition.canonical_media_type
            and str(row.get("encoding") or "").lower() == "utf-8"
            and 0 <= int(row.get("size_bytes") or 0) <= MAX_TEXT_BYTES
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
    def _invalid_reference() -> Never:
        raise NonRetryableExecutionError(
            "Explicit file reference is not available in this workspace",
            safe_message="当前任务无权引用该文件",
            error_code="file_reference_denied",
        )
