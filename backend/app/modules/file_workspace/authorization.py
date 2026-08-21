from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Never, Protocol

from app.modules.file_workspace.domain import (
    DOCUMENT_MANIFEST_ACTIONS,
    GOVERNED_DOCUMENT_FORMATS,
    FileAction,
    WorkspaceOwnerType,
)
from app.modules.file_workspace.text_format_policy import (
    get_text_format_policy,
    normalize_file_format_policy_version,
    text_format_for_name,
)
from app.shared.database import Database
from app.shared.exceptions import PermissionDenied


class BusinessAccessPort(Protocol):
    def require(
        self,
        *,
        user_id: str,
        application_id: str,
        tool_identifier: str,
        stage: str,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class FileAuthorizationContext:
    claims: dict[str, Any]
    job: dict[str, Any]
    workspace: dict[str, Any]
    manifest: dict[str, Any]


class FileAuthorizationService:
    def __init__(self, database: Database, business_access: BusinessAccessPort) -> None:
        self.database = database
        self.business_access = business_access

    def require_job(
        self,
        *,
        claims: dict[str, Any],
        tool_identifier: str,
    ) -> FileAuthorizationContext:
        row = self.database.execute_one(
            """
            select j.*, s.external_conversation_id,
                   s.source_connector_id as session_connector_id,
                   s.application_publication_id as session_publication_id,
                   u.status as user_status, u.account_type as user_account_type,
                   w.tenant_id as workspace_tenant_id,
                   w.owner_type, w.owner_user_id, w.owner_enterprise_id,
                   w.owner_connector_id, w.owner_conversation_id,
                   w.status as workspace_status,
                   w.business_application_publication_id as workspace_publication_id
              from agent_job j
              join agent_session s on s.id = j.session_id
              join app_user u on u.id = j.internal_user_id
              join task_workspace w on w.id = j.task_workspace_id
             where j.id = ?
            """,
            (claims["job_id"],),
        )
        if row is None:
            self._deny("file_job_invalid")
        assert row is not None
        expected = {
            "sub": str(row.get("internal_user_id") or ""),
            "tenant_id": str(row.get("workspace_tenant_id") or ""),
            "job_id": str(row.get("id") or ""),
            "session_id": str(row.get("session_id") or ""),
            "agent_publication_id": str(row.get("agent_publication_id") or ""),
            "application_publication_id": str(row.get("business_application_publication_id") or ""),
        }
        if any(str(claims.get(key) or "") != value for key, value in expected.items()):
            self._deny("file_principal_provenance_mismatch")
        if (
            str(row.get("status")) != "RUNNING"
            or str(row.get("user_status")) != "enabled"
            or str(row.get("user_account_type")) != "human"
            or str(row.get("workspace_status")) != "ACTIVE"
            or str(row.get("session_publication_id"))
            != str(row.get("business_application_publication_id"))
            or str(row.get("workspace_publication_id"))
            != str(row.get("business_application_publication_id"))
        ):
            self._deny("file_job_not_authorized")
        self._require_owner(row, sender_user_id=str(claims["sub"]))
        manifest = self.database.execute_one(
            "select * from agent_job_file_snapshot where job_id = ?",
            (claims["job_id"],),
        )
        if (
            manifest is None
            or str(manifest.get("workspace_id")) != str(row.get("task_workspace_id"))
            or str(manifest.get("tenant_id")) != str(claims["tenant_id"])
            or str(manifest.get("principal_user_id")) != str(claims["sub"])
            or str(manifest.get("business_application_publication_id"))
            != str(claims["application_publication_id"])
        ):
            self._deny("file_manifest_invalid")
        self.business_access.require(
            user_id=str(claims["sub"]),
            application_id=str(row.get("business_application_id") or ""),
            tool_identifier=tool_identifier,
            stage="file_principal_resolve",
        )
        workspace = {
            "id": row["task_workspace_id"],
            "tenant_id": row["workspace_tenant_id"],
            "owner_type": row["owner_type"],
            "owner_user_id": row["owner_user_id"],
            "owner_enterprise_id": row["owner_enterprise_id"],
            "owner_connector_id": row["owner_connector_id"],
            "owner_conversation_id": row["owner_conversation_id"],
            "status": row["workspace_status"],
        }
        return FileAuthorizationContext(dict(claims), row, workspace, manifest)

    def require_manifest_action(
        self,
        context: FileAuthorizationContext,
        *,
        file_id: str,
        version_id: str,
        action: FileAction,
    ) -> dict[str, Any]:
        item = self.database.execute_one(
            """
            select i.*, f.tenant_id, f.owner_type, f.owner_user_id,
                   f.owner_enterprise_id, f.owner_connector_id,
                   f.owner_conversation_id, f.status as file_status,
                   f.format_code as file_format_code,
                   v.status as version_status, v.version_number, v.media_type,
                   v.format_code as version_format_code,
                   v.size_bytes, v.content_sha256, v.content_deleted_at
              from agent_job_file_snapshot_item i
              join managed_file f on f.id = i.file_id
              join managed_file_version v on v.id = i.version_id
             where i.snapshot_id = ? and i.file_id = ? and i.version_id = ?
            """,
            (context.manifest["id"], file_id, version_id),
        )
        if item is None or str(item.get("tenant_id")) != str(context.claims["tenant_id"]):
            self._deny("file_manifest_item_denied")
        assert item is not None
        try:
            actions = json.loads(str(item.get("allowed_actions_json") or "[]"))
        except json.JSONDecodeError:
            self._deny("file_manifest_actions_invalid")
        if not isinstance(actions, list) or any(not isinstance(value, str) for value in actions):
            self._deny("file_manifest_actions_invalid")
        try:
            frozen_actions = {FileAction(value) for value in actions}
        except ValueError:
            self._deny("file_manifest_actions_invalid")
        if item.get("representation_id"):
            if (
                str(item.get("format_code") or "") not in GOVERNED_DOCUMENT_FORMATS
                or frozen_actions != DOCUMENT_MANIFEST_ACTIONS
                or action not in frozen_actions
            ):
                self._deny("file_manifest_action_denied")
        elif str(item.get("format_code") or "") in GOVERNED_DOCUMENT_FORMATS:
            if frozen_actions != DOCUMENT_MANIFEST_ACTIONS or action not in frozen_actions:
                self._deny("file_manifest_action_denied")
        else:
            policy_version = normalize_file_format_policy_version(
                context.manifest.get("file_format_policy_version")
            )
            definition = get_text_format_policy(policy_version).by_code(
                str(item.get("format_code") or "TXT")
            )
            if not frozen_actions.issubset(definition.actions):
                self._deny("file_manifest_actions_invalid")
            named = text_format_for_name(
                str(item.get("display_name") or ""),
                policy_version=policy_version,
            )
            if (
                named.code is not definition.code
                or str(item.get("file_format_code") or "TXT") != definition.code.value
                or str(item.get("version_format_code") or "TXT") != definition.code.value
            ):
                self._deny("file_manifest_format_invalid")
            if action.value not in actions or action not in definition.actions:
                self._deny("file_manifest_action_denied")
        if action is not FileAction.READ_METADATA and (
            str(item.get("file_status")) != "ACTIVE"
            or str(item.get("version_status")) not in {"AVAILABLE", "CONFLICT"}
        ):
            self._deny("file_content_unavailable")
        if str(item.get("owner_type")) != str(context.workspace["owner_type"]):
            self._deny("file_owner_boundary_denied")
        if str(item.get("owner_type")) == WorkspaceOwnerType.PRIVATE_USER.value:
            if str(item.get("owner_user_id")) != str(context.claims["sub"]):
                self._deny("file_private_owner_denied")
        elif any(
            str(item.get(field) or "") != str(context.workspace[field] or "")
            for field in (
                "owner_enterprise_id",
                "owner_connector_id",
                "owner_conversation_id",
            )
        ):
            self._deny("file_group_boundary_denied")
        return item

    def require_manifest_representation(
        self,
        context: FileAuthorizationContext,
        *,
        file_id: str,
        version_id: str,
    ) -> dict[str, Any]:
        item = self.database.execute_one(
            """
            select i.*, f.tenant_id, f.owner_type, f.owner_user_id,
                   f.owner_enterprise_id, f.owner_connector_id,
                   f.owner_conversation_id, f.status as file_status,
                   v.status as version_status, r.status as representation_status,
                   r.source_file_id, r.source_version_id, r.object_key,
                   r.size_bytes as live_representation_size_bytes,
                   r.content_sha256 as live_representation_sha256,
                   r.content_deleted_at as representation_content_deleted_at
              from agent_job_file_snapshot_item i
              join managed_file f on f.id = i.file_id
              join managed_file_version v on v.id = i.version_id
              join file_representation r on r.id = i.representation_id
             where i.snapshot_id = ? and i.file_id = ? and i.version_id = ?
            """,
            (context.manifest["id"], file_id, version_id),
        )
        if (
            item is None
            or str(item.get("tenant_id")) != str(context.claims["tenant_id"])
            or str(item.get("source_file_id")) != file_id
            or str(item.get("source_version_id")) != version_id
            or str(item.get("representation_kind") or "") != "MARKDOWN"
            or str(item.get("representation_format_code") or "") != "MARKDOWN"
            or str(item.get("representation_status") or "") != "AVAILABLE"
            or item.get("representation_content_deleted_at")
            or int(item.get("live_representation_size_bytes") or -1)
            != int(item.get("representation_size_bytes") or -2)
            or str(item.get("live_representation_sha256") or "")
            != str(item.get("representation_sha256") or "")
            or str(item.get("file_status") or "") != "ACTIVE"
            or str(item.get("version_status") or "") not in {"AVAILABLE", "CONFLICT"}
        ):
            self._deny("file_representation_denied")
        assert item is not None
        if str(item.get("owner_type")) != str(context.workspace["owner_type"]):
            self._deny("file_owner_boundary_denied")
        if str(item.get("owner_type")) == WorkspaceOwnerType.PRIVATE_USER.value:
            if str(item.get("owner_user_id")) != str(context.claims["sub"]):
                self._deny("file_private_owner_denied")
        elif any(
            str(item.get(field) or "") != str(context.workspace[field] or "")
            for field in (
                "owner_enterprise_id",
                "owner_connector_id",
                "owner_conversation_id",
            )
        ):
            self._deny("file_group_boundary_denied")
        return item

    def require_working_set_materialization(
        self,
        context: FileAuthorizationContext,
        *,
        file_id: str,
        version_id: str,
    ) -> dict[str, Any]:
        item = self.database.execute_one(
            """
            select working.*, file.tenant_id, file.owner_type,
                   file.owner_user_id, file.owner_enterprise_id,
                   file.owner_connector_id, file.owner_conversation_id,
                   file.status as file_status, file.format_code as file_format_code,
                   version.status as version_status,
                   version.format_code as version_format_code,
                   version.version_number, version.media_type,
                   version.size_bytes, version.content_sha256,
                   member.logical_name as display_name,
                   member.format_code, member.readability_status,
                   representation.status as representation_status,
                   representation.source_file_id,
                   representation.source_version_id,
                   representation.object_key,
                   representation.size_bytes as live_representation_size_bytes,
                   representation.content_sha256 as live_representation_sha256,
                   representation.content_deleted_at as representation_content_deleted_at
              from agent_job_file_working_set_item working
              join task_workspace_catalog_revision revision
                on revision.id = working.workspace_catalog_revision_id
              join task_workspace_catalog_member member
                on member.workspace_id = working.workspace_id
               and member.file_id = working.file_id
               and member.version_id = working.version_id
               and member.valid_from_revision <= revision.revision
               and (member.valid_to_revision is null
                    or member.valid_to_revision > revision.revision)
              join managed_file file on file.id = working.file_id
              join managed_file_version version on version.id = working.version_id
              left join file_representation representation
                on representation.id = working.representation_id
             where working.job_id = ? and working.snapshot_id = ?
               and working.workspace_id = ? and working.file_id = ?
               and working.version_id = ?
            """,
            (
                context.claims["job_id"],
                context.manifest["id"],
                context.workspace["id"],
                file_id,
                version_id,
            ),
        )
        if (
            item is None
            or str(item.get("tenant_id") or "") != str(context.claims["tenant_id"])
            or str(item.get("file_status") or "") != "ACTIVE"
            or str(item.get("version_status") or "") not in {"AVAILABLE", "CONFLICT"}
            or not self.database.execute_one(
                """
                select 1 as active from task_workspace_file
                 where workspace_id = ? and file_id = ? and status = 'ACTIVE'
                """,
                (context.workspace["id"], file_id),
            )
        ):
            self._deny("file_working_set_item_denied")
        assert item is not None
        has_representation = bool(item.get("representation_id"))
        if has_representation and (
            str(item.get("representation_kind") or "") != "MARKDOWN"
            or str(item.get("representation_status") or "") != "AVAILABLE"
            or str(item.get("source_file_id") or "") != file_id
            or str(item.get("source_version_id") or "") != version_id
            or item.get("representation_content_deleted_at")
            or int(item.get("live_representation_size_bytes") or -1)
            != int(item.get("representation_size_bytes") or -2)
            or str(item.get("live_representation_sha256") or "")
            != str(item.get("representation_sha256") or "")
        ):
            self._deny("file_representation_denied")
        if not has_representation:
            policy = normalize_file_format_policy_version(
                context.manifest.get("file_format_policy_version")
            )
            definition = get_text_format_policy(policy).by_code(
                str(item.get("format_code") or "TXT")
            )
            if FileAction.MATERIALIZE not in definition.actions:
                self._deny("file_working_set_action_denied")
        if str(item.get("owner_type")) != str(context.workspace["owner_type"]):
            self._deny("file_owner_boundary_denied")
        if str(item.get("owner_type")) == WorkspaceOwnerType.PRIVATE_USER.value:
            if str(item.get("owner_user_id")) != str(context.claims["sub"]):
                self._deny("file_private_owner_denied")
        elif any(
            str(item.get(field) or "") != str(context.workspace[field] or "")
            for field in (
                "owner_enterprise_id",
                "owner_connector_id",
                "owner_conversation_id",
            )
        ):
            self._deny("file_group_boundary_denied")
        item["allowed_actions_json"] = json.dumps([FileAction.MATERIALIZE.value])
        return item

    @staticmethod
    def _require_owner(row: dict[str, Any], *, sender_user_id: str) -> None:
        owner_type = WorkspaceOwnerType(str(row.get("owner_type") or ""))
        if owner_type is WorkspaceOwnerType.PRIVATE_USER:
            if str(row.get("owner_user_id") or "") != sender_user_id:
                FileAuthorizationService._deny("file_private_owner_denied")
            return
        if (
            str(row.get("owner_connector_id") or "")
            != str(row.get("session_connector_id") or row.get("source_connector_id") or "")
            or str(row.get("owner_conversation_id") or "")
            != str(row.get("external_conversation_id") or "")
            or not str(row.get("owner_enterprise_id") or "")
        ):
            FileAuthorizationService._deny("file_group_boundary_denied")

    @staticmethod
    def _deny(code: str) -> Never:
        raise PermissionDenied(
            "File authorization denied",
            safe_message="当前任务无权访问该文件",
            error_code=code,
        )
