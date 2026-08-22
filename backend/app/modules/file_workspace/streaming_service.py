from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO, Callable, Never, Protocol, cast

from app.modules.file_workspace.authorization import (
    FileAuthorizationContext,
    FileAuthorizationService,
)
from app.modules.document_processing import (
    GovernedDocumentProcessingService,
    ValidatedDocumentSource,
    validate_document_source,
)
from app.modules.file_workspace.contracts import (
    FILE_TRANSFER_META_KEY,
    FILE_TRANSFER_PROTOCOL,
)
from app.modules.file_workspace.domain import (
    CleanupResourceType,
    CommitDeliveryMode,
    CommitIntentStatus,
    CommitUserIntent,
    FileAction,
    FileOwner,
    FileSourceKind,
    FileVersionKind,
    FileVersionStatus,
    RetentionReason,
    StagingStatus,
    WorkspaceFileRole,
    WorkspaceOwnerType,
)
from app.modules.file_workspace.quota import WorkspaceQuotaService
from app.modules.file_workspace.repository import FileWorkspaceRepository
from app.modules.file_workspace.lifecycle_service import FileLifecycleService
from app.modules.file_workspace.storage import InternalStoredObject
from app.modules.file_workspace.text_format_policy import (
    TextFormatDefinition,
    TextStreamValidator,
    get_text_format_policy,
    text_format_for_name,
    validate_format_action,
)
from app.shared.exceptions import NonRetryableExecutionError, PermissionDenied


TRANSFER_TTL = timedelta(minutes=5)
INTERNAL_TRANSFER_META = "__file_transfer_meta"


class FilePrincipalPort(Protocol):
    def authenticate(
        self, token: str, *, tool_identifier: str = "task_workspace_get"
    ) -> tuple[dict[str, Any], FileAuthorizationContext, tuple[str, ...]]: ...


class FileObjectStoragePort(Protocol):
    @staticmethod
    def new_object_key(*, kind: str) -> str: ...

    def put_stream(
        self,
        stream: BinaryIO,
        *,
        kind: str,
        content_type: str,
        content_sha256: str,
        size_bytes: int,
        internal_object_key: str | None = None,
    ) -> InternalStoredObject: ...

    def open_stream(self, *, internal_object_key: str) -> BinaryIO: ...


class FileDeliveryIntentPort(Protocol):
    def enqueue(
        self,
        *,
        job_id: str,
        file_id: str,
        version_id: str,
        display_name: str,
    ) -> dict[str, str]: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _opaque(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class GovernedFileStreamingService:
    """Two-phase File MCP control and authenticated byte streaming boundary."""

    def __init__(
        self,
        repository: FileWorkspaceRepository,
        authorization: FileAuthorizationService,
        storage: FileObjectStoragePort,
        principal: FilePrincipalPort,
        *,
        now: Callable[[], datetime] = _utc_now,
        validator: TextStreamValidator | None = None,
        quota: WorkspaceQuotaService | None = None,
        lifecycle: FileLifecycleService | None = None,
        delivery_intents: FileDeliveryIntentPort | None = None,
        document_processing: GovernedDocumentProcessingService | None = None,
    ) -> None:
        self.repository = repository
        self.authorization = authorization
        self.storage = storage
        self.principal = principal
        self.now = now
        self.validator = validator or TextStreamValidator()
        self.quota = quota or WorkspaceQuotaService(repository.database)
        self.lifecycle = lifecycle
        self.delivery_intents = delivery_intents
        self.document_processing = document_processing

    def prepare_materialization(
        self,
        *,
        context: FileAuthorizationContext,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        file_id = str(arguments["file_id"])
        version_id = str(arguments["version_id"])
        self._deny_unreadable_document(file_id=file_id, version_id=version_id)
        representation = self.repository.database.execute_one(
            """
            select representation_id from agent_job_file_snapshot_item
             where snapshot_id = ? and file_id = ? and version_id = ?
            """,
            (context.manifest["id"], file_id, version_id),
        )
        from_initial_manifest = representation is not None
        if representation is None:
            self.repository.promote_catalog_working_set_item(
                job_id=str(context.claims["job_id"]),
                workspace_id=str(context.workspace["id"]),
                snapshot_id=str(context.manifest["id"]),
                catalog_revision_id=str(
                    context.manifest.get("workspace_catalog_revision_id") or ""
                ),
                file_id=file_id,
                version_id=version_id,
            )
            item = self.authorization.require_working_set_materialization(
                context, file_id=file_id, version_id=version_id
            )
            representation = {
                "representation_id": item.get("representation_id")
            }
        is_representation = bool(representation.get("representation_id"))
        if is_representation:
            if from_initial_manifest:
                item = self.authorization.require_manifest_representation(
                    context, file_id=file_id, version_id=version_id
                )
            content = {
                "size_bytes": int(item["representation_size_bytes"]),
                "content_sha256": str(item["representation_sha256"]),
            }
        else:
            if from_initial_manifest:
                item = self.authorization.require_manifest_action(
                    context,
                    file_id=file_id,
                    version_id=version_id,
                    action=FileAction.MATERIALIZE,
                )
            content = self.repository.require_content_available(version_id)
            if str(content["file_id"]) != file_id:
                self._deny("file_manifest_item_denied", "当前任务无权访问该文件")
        requested = str(arguments.get("preferred_name") or item["display_name"])
        if is_representation:
            if arguments.get("preferred_name") and Path(requested).suffix.lower() != ".md":
                self._deny("file_format_mismatch", "文档可读表示必须使用 Markdown 文件名")
            requested = f"{Path(requested).stem or 'document'}.md"
            format_code = "MARKDOWN"
            extension = ".md"
            allowed_actions = [FileAction.MATERIALIZE.value]
        else:
            definition = validate_format_action(
                format_code=str(item.get("format_code") or "TXT"),
                action=FileAction.MATERIALIZE,
            )
            requested_definition = text_format_for_name(
                requested,
            )
            if requested_definition.code is not definition.code:
                self._deny("file_format_mismatch", "文件名与冻结格式不一致")
            format_code = definition.code.value
            extension = definition.extension
            allowed_actions = self._item_actions(item)
        now = self.now()
        handle = _opaque("sandbox_entry")
        transfer_id = _opaque("file_transfer")
        stem = Path(requested).stem[:120] or "input"
        materialization_directory = "inputs/readonly" if is_representation else "inputs"
        relative_path = f"{materialization_directory}/{stem}-{handle[-8:]}{extension}"
        expires_at = _iso(now + TRANSFER_TTL)
        transfer = self.repository.get_or_create_materialization_transfer(
            transfer_id=transfer_id,
            job_id=str(context.claims["job_id"]),
            workspace_id=str(context.workspace["id"]),
            file_id=file_id,
            version_id=version_id,
            sandbox_entry_handle=handle,
            relative_path=relative_path,
            expected_size_bytes=int(content["size_bytes"]),
            expected_sha256=str(content["content_sha256"]),
            expires_at=expires_at,
            now=_iso(now),
            format_code=format_code,
        )
        transfer_id = str(transfer["transfer_id"])
        handle = str(transfer["sandbox_entry_handle"])
        relative_path = str(transfer["relative_path"])
        expires_at = str(transfer["expires_at"])
        return {
            "file_id": file_id,
            "version_id": version_id,
            "display_name": requested,
            "format_code": format_code,
            "allowed_actions": allowed_actions,
            "expires_at": expires_at,
            INTERNAL_TRANSFER_META: {
                FILE_TRANSFER_META_KEY: {
                    "protocol": FILE_TRANSFER_PROTOCOL,
                    "action": "MATERIALIZE",
                    "transfer_id": transfer_id,
                    "sandbox_entry_handle": handle,
                    "relative_path": relative_path,
                    "expected_size_bytes": int(content["size_bytes"]),
                    "expected_sha256": str(content["content_sha256"]),
                    "format_code": format_code,
                }
            },
        }

    def prepare_commit(
        self,
        *,
        context: FileAuthorizationContext,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        target_file_id = str(arguments.get("file_id") or "") or None
        base_version_id = str(arguments.get("base_version_id") or "") or None
        user_intent = CommitUserIntent(str(arguments["user_intent"]))
        display_name = str(arguments["display_name"])
        definition = text_format_for_name(
            display_name,
        )
        validate_format_action(
            format_code=definition.code,
            action=FileAction.COMMIT,
        )
        if target_file_id is not None and base_version_id is not None:
            item = self.authorization.require_manifest_action(
                context,
                file_id=target_file_id,
                version_id=base_version_id,
                action=FileAction.COMMIT,
            )
            if str(item.get("format_code") or "TXT") != definition.code.value:
                self._deny("file_format_mismatch", "修改文件时不得改变文件格式")
            base_version = self.repository.require_content_available(base_version_id)
            target_file = self.repository.get_file(target_file_id)
            if (
                str(base_version.get("file_id") or "") != target_file_id
                or str(base_version.get("format_code") or "TXT") != definition.code.value
                or str(target_file.get("format_code") or "TXT") != definition.code.value
            ):
                self._deny("file_format_mismatch", "修改文件时不得改变文件格式")
        elif user_intent is CommitUserIntent.MODIFY:
            self._deny("file_commit_target_required", "修改文件必须绑定基础版本")
        occupied = self.repository.database.execute_one(
            """
            select file_id from task_workspace_file
             where workspace_id = ? and logical_name = ? and status = 'ACTIVE'
            """,
            (context.workspace["id"], display_name),
        )
        if occupied is not None and str(occupied["file_id"]) != str(target_file_id or ""):
            self._deny(
                "file_logical_name_conflict",
                "工作区已有同名文件，请先列出文件并明确修改现有版本",
            )
        delivery_mode = CommitDeliveryMode(str(arguments["delivery_mode"]))
        if delivery_mode is CommitDeliveryMode.DEFAULT and (
            self.delivery_intents is None
            or not self._default_delivery_enabled(str(context.claims["job_id"]))
        ):
            delivery_mode = CommitDeliveryMode.WORKSPACE_ONLY
        canonical = {
            "tenant_id": str(context.claims["tenant_id"]),
            "job_id": str(context.claims["job_id"]),
            "workspace_id": str(context.workspace["id"]),
            "target_file_id": target_file_id or "",
            "base_version_id": base_version_id or "",
            "sandbox_entry_handle": str(arguments["sandbox_entry_handle"]),
            "display_name": display_name,
            "user_intent": user_intent.value,
            "delivery_mode": delivery_mode.value,
            "format_code": definition.code.value,
        }
        metadata_hash = hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        commit_id = _opaque("file_commit")
        expires_at = _iso(self.now() + TRANSFER_TTL)
        self.repository.create_commit_intent(
            intent_id=_opaque("commit_intent"),
            commit_id=commit_id,
            job_id=canonical["job_id"],
            workspace_id=canonical["workspace_id"],
            target_file_id=target_file_id,
            base_version_id=base_version_id,
            sandbox_entry_handle=canonical["sandbox_entry_handle"],
            display_name=canonical["display_name"],
            user_intent=user_intent,
            delivery_mode=CommitDeliveryMode(canonical["delivery_mode"]),
            metadata_hash=metadata_hash,
            expires_at=expires_at,
            format_code=definition.code.value,
        )
        return {
            "commit_id": commit_id,
            "display_name": canonical["display_name"],
            "format_code": definition.code.value,
            "expires_at": expires_at,
            INTERNAL_TRANSFER_META: {
                FILE_TRANSFER_META_KEY: {
                    "protocol": FILE_TRANSFER_PROTOCOL,
                    "action": "UPLOAD_COMMIT",
                    "commit_id": commit_id,
                    "sandbox_entry_handle": canonical["sandbox_entry_handle"],
                    "format_code": definition.code.value,
                }
            },
        }

    def deliver_version(
        self,
        *,
        context: FileAuthorizationContext,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        if self.delivery_intents is None:
            self._deny("file_delivery_not_ready", "文件交付尚未就绪")
        assert self.delivery_intents is not None
        file_id = str(arguments["file_id"])
        version_id = str(arguments["version_id"])
        display_name = self._require_deliverable_version(
            context=context,
            file_id=file_id,
            version_id=version_id,
        )
        receipt = self.delivery_intents.enqueue(
            job_id=str(context.claims["job_id"]),
            file_id=file_id,
            version_id=version_id,
            display_name=display_name,
        )
        return {
            "delivery_id": str(receipt["delivery_id"]),
            "file_id": file_id,
            "version_id": version_id,
            "delivery_status": str(receipt["status"]),
        }

    def _require_deliverable_version(
        self,
        *,
        context: FileAuthorizationContext,
        file_id: str,
        version_id: str,
    ) -> str:
        try:
            item = self.authorization.require_manifest_action(
                context,
                file_id=file_id,
                version_id=version_id,
                action=FileAction.DELIVER,
            )
            return str(item.get("display_name") or "result.txt")
        except PermissionDenied as manifest_denial:
            committed = self.repository.database.execute_one(
                """
                select display_name
                  from file_commit_intent
                 where job_id = ? and workspace_id = ?
                   and status = 'COMMITTED' and result_version_id = ?
                """,
                (context.claims["job_id"], context.workspace["id"], version_id),
            )
            if committed is None:
                raise manifest_denial
        version = self.repository.require_content_available(version_id)
        if str(version["file_id"]) != file_id or str(version["status"]) != "AVAILABLE":
            self._deny("file_delivery_version_invalid", "文件交付版本无效")
        file_row = self.repository.get_file(file_id)
        self._require_owner_boundary(file_row, context.workspace)
        return str(committed["display_name"])

    def _default_delivery_enabled(self, job_id: str) -> bool:
        row = (
            self.repository.database.execute_one(
                "select business_application_route_decision_json from agent_job where id = ?",
                (job_id,),
            )
            or {}
        )
        try:
            route = json.loads(str(row.get("business_application_route_decision_json") or "{}"))
        except json.JSONDecodeError:
            return False
        features = route.get("task_file_features") if isinstance(route, dict) else None
        return bool(isinstance(features, dict) and features.get("default_file_delivery_enabled"))

    async def download_transfer(
        self, *, transfer_id: str, token: str
    ) -> tuple[AsyncIterator[bytes], str]:
        claims, context, _visible = self.principal.authenticate(
            token, tool_identifier="file_prepare_materialization"
        )
        transfer = self.repository.consume_materialization_transfer(
            transfer_id=transfer_id,
            job_id=str(claims["job_id"]),
            now=_iso(self.now()),
        )
        if str(transfer["workspace_id"]) != str(context.workspace["id"]):
            self._deny("file_transfer_binding_mismatch", "文件传输与当前任务不匹配")
        frozen = self.repository.database.execute_one(
            """
            select representation_id from agent_job_file_snapshot_item
             where snapshot_id = ? and file_id = ? and version_id = ?
            """,
            (context.manifest["id"], transfer["file_id"], transfer["version_id"]),
        )
        if frozen and frozen.get("representation_id"):
            item = self.authorization.require_manifest_representation(
                context,
                file_id=str(transfer["file_id"]),
                version_id=str(transfer["version_id"]),
            )
            content = {
                "size_bytes": int(item["live_representation_size_bytes"]),
                "content_sha256": str(item["live_representation_sha256"]),
                "object_key": str(item["object_key"]),
            }
        elif frozen is None:
            item = self.authorization.require_working_set_materialization(
                context,
                file_id=str(transfer["file_id"]),
                version_id=str(transfer["version_id"]),
            )
            if item.get("representation_id"):
                content = {
                    "size_bytes": int(item["live_representation_size_bytes"]),
                    "content_sha256": str(item["live_representation_sha256"]),
                    "object_key": str(item["object_key"]),
                }
            else:
                content = self.repository.require_content_available(
                    str(transfer["version_id"])
                )
        else:
            self.authorization.require_manifest_action(
                context,
                file_id=str(transfer["file_id"]),
                version_id=str(transfer["version_id"]),
                action=FileAction.MATERIALIZE,
            )
            content = self.repository.require_content_available(str(transfer["version_id"]))
            if str(content.get("format_code") or "TXT") != str(
                transfer.get("format_code") or "TXT"
            ):
                self._deny("file_format_mismatch", "文件传输格式不一致")
        if int(content["size_bytes"]) != int(transfer["expected_size_bytes"]) or str(
            content["content_sha256"]
        ) != str(transfer["expected_sha256"]):
            self._deny("file_transfer_integrity_mismatch", "文件完整性校验失败")
        stream = await asyncio.to_thread(
            self.storage.open_stream,
            internal_object_key=str(content["object_key"]),
        )

        async def chunks() -> AsyncIterator[bytes]:
            try:
                while True:
                    chunk = await asyncio.to_thread(stream.read, 64 * 1024)
                    if not chunk:
                        break
                    yield bytes(chunk)
            finally:
                await asyncio.to_thread(stream.close)

        return chunks(), "application/octet-stream"

    async def download_delivery(
        self,
        *,
        delivery_id: str,
        service_claims: dict[str, Any],
    ) -> tuple[AsyncIterator[bytes], dict[str, str | int]]:
        if str(service_claims.get("sub") or "") != "delivery-worker":
            self._deny("file_delivery_principal_invalid", "文件交付身份无效")
        binding = self.repository.database.execute_one(
            """
            select d.file_id, d.file_version_id, d.file_content_sha256,
                   d.principal_user_id, d.session_id,
                   d.application_publication_id, d.agent_publication_id,
                   d.job_id, d.status, a.content as artifact_content,
                   j.internal_user_id, j.session_id as current_session_id,
                   j.business_application_publication_id,
                   j.agent_publication_id as current_agent_publication_id
              from delivery_outbox d
              join agent_job j on j.id = d.job_id
              join agent_artifact a on a.id = d.result_artifact_id
             where d.id = ? and d.delivery_kind = 'FILE_VERSION'
            """,
            (delivery_id,),
        )
        if binding is None or str(binding["status"]) != "RUNNING":
            self._deny("file_delivery_binding_invalid", "文件交付意图无效")
        assert binding is not None
        expected = {
            "principal_user_id": "internal_user_id",
            "session_id": "current_session_id",
            "application_publication_id": "business_application_publication_id",
            "agent_publication_id": "current_agent_publication_id",
        }
        if any(
            str(binding[left] or "") != str(binding[right] or "")
            for left, right in expected.items()
        ):
            self._deny("file_delivery_provenance_mismatch", "文件交付来源已变化")
        version = self.repository.require_content_available(str(binding["file_version_id"]))
        if (
            str(version["file_id"]) != str(binding["file_id"])
            or str(version["status"]) != "AVAILABLE"
            or str(version["content_sha256"]) != str(binding["file_content_sha256"])
        ):
            self._deny("file_delivery_version_invalid", "文件交付版本无效")
        try:
            artifact = json.loads(str(binding["artifact_content"]))
            display_name = str(artifact["display_name"])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise NonRetryableExecutionError(
                "File Delivery artifact is invalid",
                safe_message="文件交付信息无效",
                error_code="file_delivery_artifact_invalid",
            ) from exc
        definition = get_text_format_policy().by_code(
            str(version.get("format_code") or "TXT")
        )
        named = text_format_for_name(display_name)
        file_row = self.repository.get_file(str(binding["file_id"]))
        if (
            named.code is not definition.code
            or str(file_row.get("format_code") or "TXT") != definition.code.value
            or str(version.get("media_type") or "") != definition.canonical_media_type
            or int(version.get("size_bytes") or 0) > 15 * 1024 * 1024
        ):
            self._deny("file_delivery_version_invalid", "文件交付格式无效")
        stream = await asyncio.to_thread(
            self.storage.open_stream,
            internal_object_key=str(version["object_key"]),
        )

        async def chunks() -> AsyncIterator[bytes]:
            try:
                while True:
                    chunk = await asyncio.to_thread(stream.read, 64 * 1024)
                    if not chunk:
                        break
                    yield bytes(chunk)
            finally:
                await asyncio.to_thread(stream.close)

        return chunks(), {
            "display_name": display_name,
            "size_bytes": int(version["size_bytes"]),
            "sha256": str(version["content_sha256"]),
            "format_code": str(version.get("format_code") or "TXT"),
            "media_type": str(version.get("media_type") or "text/plain"),
        }

    async def upload_commit(
        self,
        *,
        commit_id: str,
        token: str,
        body: AsyncIterator[bytes],
    ) -> dict[str, Any]:
        claims, context, _visible = self.principal.authenticate(
            token, tool_identifier="file_create_commit_intent"
        )
        intent = self.repository.get_commit_intent_by_commit_id(commit_id)
        self._require_commit_binding(intent, claims=claims, context=context)
        definition = validate_format_action(
            format_code=str(intent.get("format_code") or "TXT"),
            action=FileAction.COMMIT,
        )
        reservation_id = ""
        with tempfile.TemporaryFile(mode="w+b") as content:
            validated = await self.validator.validate_and_copy_async(
                body,
                content,
                display_name=str(intent["display_name"]),
                media_type=definition.canonical_media_type,
                agent_output=True,
                expected_format=definition.code,
            )
            intent = self.repository.begin_commit_upload(
                commit_id=commit_id,
                content_sha256=validated.content_sha256,
                size_bytes=validated.size_bytes,
                now=_iso(self.now()),
            )
            terminal = self._terminal_receipt(intent)
            if terminal is not None:
                return terminal
            reservation = self.quota.reserve(
                workspace_id=str(intent["workspace_id"]),
                operation_type="FILE_COMMIT",
                operation_id=commit_id,
                logical_file_slots=int(not str(intent.get("target_file_id") or "")),
                billable_bytes=validated.size_bytes,
                expires_at=str(intent["expires_at"]),
                now=_iso(self.now()),
            )
            reservation_id = str(reservation["id"])
            try:
                staging = self.repository.get_staging_for_intent(str(intent["id"]))
                if staging is None:
                    object_key = self.storage.new_object_key(kind="staging")
                    try:
                        staging = self.repository.create_staging(
                            intent_id=str(intent["id"]), object_key=object_key
                        )
                    except Exception:
                        staging = self.repository.get_staging_for_intent(str(intent["id"]))
                        if staging is None:
                            raise
                if str(staging["status"]) not in {"UPLOADING", "COMPLETE"}:
                    self._deny("file_commit_staging_unavailable", "文件提交暂存状态无效")
                if str(staging["status"]) == "UPLOADING":
                    content.seek(0)
                    await asyncio.to_thread(
                        self.storage.put_stream,
                        content,
                        kind="staging",
                        content_type=definition.canonical_media_type,
                        content_sha256=validated.content_sha256,
                        size_bytes=validated.size_bytes,
                        internal_object_key=str(staging["object_key"]),
                    )
                    staging = self.repository.update_staging(
                        staging_id=str(staging["id"]),
                        status=StagingStatus.COMPLETE,
                        size_bytes=validated.size_bytes,
                        content_sha256=validated.content_sha256,
                    )
            except Exception:
                if "staging" in locals():
                    self._record_compensation(intent=intent, staging=staging)
                self.quota.finalize_reservation(
                    reservation_id,
                    committed=False,
                    now=_iso(self.now()),
                )
                raise
        try:
            result = self._publish(
                intent_id=str(intent["id"]), staging_id=str(staging["id"])
            )
            self.quota.finalize_reservation(
                reservation_id,
                committed=True,
                now=_iso(self.now()),
            )
            return result
        except Exception as exc:
            latest = self.repository.get_commit_intent(str(intent["id"]))
            terminal = self._terminal_receipt(latest)
            if terminal is not None:
                self.quota.finalize_reservation(
                    reservation_id,
                    committed=True,
                    now=_iso(self.now()),
                )
                return terminal
            logical_name_conflict = self._is_logical_name_conflict(exc)
            self._record_compensation(
                intent=latest,
                staging=staging,
                failure_code=(
                    "file_logical_name_conflict"
                    if logical_name_conflict
                    else "file_commit_publish_failed"
                ),
            )
            if reservation_id:
                self.quota.finalize_reservation(
                    reservation_id,
                    committed=False,
                    now=_iso(self.now()),
                )
            if logical_name_conflict:
                self._deny(
                    "file_logical_name_conflict",
                    "工作区已有同名文件，请先列出文件并明确修改现有版本",
                )
            raise

    async def import_attachment(
        self,
        *,
        attachment_id: str,
        service_claims: dict[str, Any],
        media_type: str,
        body: AsyncIterator[bytes],
    ) -> dict[str, Any]:
        if str(service_claims.get("sub") or "") != "file-worker":
            self._deny("file_worker_principal_invalid", "文件工作身份无效")
        row = self.repository.database.execute_one(
            """
            select a.*,
                   coalesce(a.task_workspace_id, j.task_workspace_id)
                     as resolved_task_workspace_id,
                   coalesce(j.internal_user_id, m.sender_id, s.requester_id) as internal_user_id,
                   coalesce(j.source_channel, s.source_channel) as source_channel,
                   m.session_id
              from message_attachment a
              join agent_message m on m.id = a.message_id
              join agent_session s on s.id = m.session_id
              left join agent_job j on j.id = a.job_id
             where a.id = ?
            """,
            (attachment_id,),
        )
        if row is None:
            self._deny("file_attachment_not_found", "未找到聊天附件")
        assert row is not None
        workspace_id = str(row.get("resolved_task_workspace_id") or "")
        if workspace_id:
            workspace = self.repository.get_workspace(workspace_id)
            if str(workspace["session_id"]) != str(row["session_id"]):
                self._deny(
                    "file_workspace_boundary_mismatch",
                    "附件与任务文件工作区边界不一致",
                )
        definition: TextFormatDefinition | None = None
        document_source: ValidatedDocumentSource | None = None
        document_profile_code = "NONE"
        if workspace_id:
            document_profile_code = self._workspace_document_profile(workspace_id)
            try:
                definition = text_format_for_name(
                    str(row["file_name"]),
                )
            except NonRetryableExecutionError:
                definition = None
        reservation_id = ""
        with tempfile.TemporaryFile(mode="w+b") as content:
            if definition is not None:
                validated = await self.validator.validate_and_copy_async(
                    body,
                    content,
                    display_name=str(row["file_name"]),
                    media_type=media_type,
                    agent_output=False,
                    expected_format=definition.code,
                )
                size_bytes = validated.size_bytes
                content_sha256 = validated.content_sha256
            else:
                size_bytes, content_sha256 = await self._copy_attachment_stream(body, content)
                if document_profile_code != "NONE":
                    if self.document_processing is None:
                        self._deny(
                            "document_processing_unavailable",
                            "文档处理依赖尚未就绪",
                        )
                    document_source = validate_document_source(
                        content,
                        display_name=str(row["file_name"]),
                        declared_media_type=media_type,
                        declared_size_bytes=size_bytes,
                        allow_image_extension_canonicalization=(
                            str(row.get("media_type") or "").lower() == "image"
                        ),
                    )
            existing_hash = str(row.get("sha256") or "")
            if existing_hash and str(row.get("object_key") or ""):
                if existing_hash != content_sha256 or int(row.get("size_bytes") or 0) != size_bytes:
                    self._deny(
                        "file_attachment_idempotency_conflict",
                        "附件标识已绑定不同内容",
                    )
                return self._attachment_receipt(attachment_id)
            if workspace_id and (definition is not None or document_source is not None):
                reservation = self.quota.reserve(
                    workspace_id=workspace_id,
                    operation_type="ATTACHMENT_IMPORT",
                    operation_id=attachment_id,
                    logical_file_slots=1,
                    billable_bytes=size_bytes,
                    expires_at=_iso(self.now() + timedelta(minutes=30)),
                    now=_iso(self.now()),
                )
                reservation_id = str(reservation["id"])
            object_key = self.storage.new_object_key(kind="attachment")
            content.seek(0)
            try:
                await asyncio.to_thread(
                    self.storage.put_stream,
                    content,
                    kind="attachment",
                    content_type=(
                        definition.canonical_media_type
                        if definition is not None
                        else (
                            document_source.media_type
                            if document_source is not None
                            else media_type.split(";", 1)[0][:128]
                        )
                    ),
                    content_sha256=content_sha256,
                    size_bytes=size_bytes,
                    internal_object_key=object_key,
                )
            except Exception:
                if reservation_id:
                    self.quota.finalize_reservation(
                        reservation_id,
                        committed=False,
                        now=_iso(self.now()),
                    )
                raise
        timestamp = _iso(self.now())
        try:
            self.repository.database.execute(
                """
                update message_attachment
                   set size_bytes = ?, sha256 = ?, object_bucket = 'file-service',
                       object_key = ?, updated_at = ?
                 where id = ? and (sha256 = '' or sha256 is null)
                """,
                (size_bytes, content_sha256, object_key, timestamp, attachment_id),
            )
            if definition is not None:
                self._publish_attachment_text(
                    attachment={**row, "task_workspace_id": workspace_id},
                    object_key=object_key,
                    size_bytes=size_bytes,
                    content_sha256=content_sha256,
                    definition=definition,
                )
            elif document_source is not None:
                self._publish_attachment_document(
                    attachment={**row, "task_workspace_id": workspace_id},
                    object_key=object_key,
                    size_bytes=size_bytes,
                    content_sha256=content_sha256,
                    source=document_source,
                )
            self._ensure_attachment_cleanup(attachment_id)
            if reservation_id:
                self.quota.finalize_reservation(
                    reservation_id,
                    committed=True,
                    now=_iso(self.now()),
                )
            return self._attachment_receipt(attachment_id)
        except Exception:
            self._ensure_attachment_cleanup(attachment_id, reason="ATTACHMENT_IMPORT_COMPENSATION")
            if reservation_id:
                self.quota.finalize_reservation(
                    reservation_id,
                    committed=False,
                    now=_iso(self.now()),
                )
            raise

    async def run_maintenance(self, *, service_claims: dict[str, Any]) -> dict[str, Any]:
        if str(service_claims.get("sub") or "") != "file-worker":
            self._deny("file_worker_principal_invalid", "文件工作身份无效")
        if self.lifecycle is None:
            self._deny("file_lifecycle_not_ready", "文件生命周期处理尚未就绪")
        assert self.lifecycle is not None
        result = cast(dict[str, Any], await asyncio.to_thread(self.lifecycle.run_once))
        if self.document_processing is not None:
            reconciliation = await asyncio.to_thread(
                self.document_processing.reconcile_attachment_readability
            )
            processing = await asyncio.to_thread(
                self.document_processing.cleanup_expired_transfers,
                now=self.now(),
            )
            picture_cleanup = await asyncio.to_thread(
                self.document_processing.cleanup_picture_artifacts,
                now=self.now(),
            )
            result.update(
                {
                    "representation_transfers_expired": processing["expired"],
                    "representation_staging_deleted": processing["deleted"],
                    "representation_staging_delete_failed": processing["failed"],
                    "document_readability_reconciled": reconciliation["reconciled"],
                    "document_processing_release_job_ids": reconciliation["release_job_ids"],
                    "document_picture_cleanup_claimed": picture_cleanup["claimed"],
                    "document_picture_cleanup_deleted": picture_cleanup["deleted"],
                    "document_picture_cleanup_retried": picture_cleanup["retried"],
                    "document_picture_cleanup_dead": picture_cleanup["dead"],
                }
            )
        return result

    async def maintenance_metrics(self, *, service_claims: dict[str, Any]) -> dict[str, Any]:
        if str(service_claims.get("sub") or "") != "file-worker":
            self._deny("file_worker_principal_invalid", "文件工作身份无效")
        if self.lifecycle is None:
            self._deny("file_lifecycle_not_ready", "文件生命周期处理尚未就绪")
        assert self.lifecycle is not None
        result = cast(dict[str, Any], await asyncio.to_thread(self.lifecycle.metrics))
        if self.document_processing is not None:
            result["document_processing"] = await asyncio.to_thread(
                self.document_processing.repository.processing_summary
            )
        return result

    async def _copy_attachment_stream(
        self, body: AsyncIterator[bytes], destination: BinaryIO
    ) -> tuple[int, str]:
        digest = hashlib.sha256()
        size_bytes = 0
        async for chunk in body:
            if not isinstance(chunk, bytes):
                self._deny("file_stream_invalid", "附件流无效")
            size_bytes += len(chunk)
            if size_bytes > 25 * 1024 * 1024:
                self._deny("file_attachment_too_large", "聊天附件超过 25 MiB")
            digest.update(chunk)
            destination.write(chunk)
        return size_bytes, digest.hexdigest()

    def _publish_attachment_text(
        self,
        *,
        attachment: dict[str, Any],
        object_key: str,
        size_bytes: int,
        content_sha256: str,
        definition: TextFormatDefinition,
    ) -> None:
        workspace_id = str(attachment.get("task_workspace_id") or "")
        if not workspace_id:
            return
        existing = self.repository.database.execute_one(
            "select * from message_attachment_file_binding where attachment_id = ?",
            (attachment["id"],),
        )
        if existing is not None:
            version = self.repository.get_version(str(existing["version_id"]))
            if (
                str(version["content_sha256"]) != content_sha256
                or int(version["size_bytes"]) != size_bytes
            ):
                self._deny(
                    "file_attachment_idempotency_conflict",
                    "附件标识已绑定不同内容",
                )
            return
        with self.repository.database.unit_of_work():
            workspace = self.repository.get_workspace(workspace_id)
            if str(workspace["status"]) != "ACTIVE":
                self._deny("file_workspace_expired", "任务文件工作区已失效")
            display_name = self._available_attachment_name(
                workspace_id=workspace_id,
                requested=str(attachment["file_name"]),
            )
            file_id = _opaque("managed_file")
            version_id = _opaque("file_version")
            self.repository.create_file(
                file_id=file_id,
                tenant_id=str(workspace["tenant_id"]),
                owner=self._owner(workspace),
                display_name=display_name,
                actor_id="file-worker",
                source_received_at=str(attachment.get("created_at") or "") or None,
                format_code=definition.code.value,
            )
            self.repository.create_version(
                version_id=version_id,
                file_id=file_id,
                version_number=1,
                version_kind=FileVersionKind.ATTACHMENT,
                status=FileVersionStatus.AVAILABLE,
                media_type=definition.canonical_media_type,
                encoding="utf-8",
                size_bytes=size_bytes,
                content_sha256=content_sha256,
                object_key=object_key,
                source_kind=FileSourceKind.MESSAGE_ATTACHMENT,
                actor_id="file-worker",
                format_code=definition.code.value,
                source_reference_digest=content_sha256,
                advance_current_from="",
            )
            self.repository.link_workspace_file(
                workspace_id=workspace_id,
                file_id=file_id,
                version_id=version_id,
                logical_name=display_name,
                role=WorkspaceFileRole.INPUT,
            )
            self.repository.add_external_reference(
                file_id=file_id,
                version_id=version_id,
                provider=(
                    "DINGTALK"
                    if str(attachment.get("source_channel") or "").startswith("ding")
                    else "CHANNEL"
                ),
                source_type="CHAT_ATTACHMENT",
                source_id=str(attachment["id"]),
                source_digest=content_sha256,
            )
            expires_at = self._attachment_expiry(attachment)
            self.repository.bind_attachment(
                attachment_id=str(attachment["id"]),
                file_id=file_id,
                version_id=version_id,
                retention_expires_at=expires_at,
            )
            self.repository.add_retention(
                version_id=version_id,
                reason=RetentionReason.MESSAGE_ATTACHMENT,
                source_id=str(attachment["id"]),
                starts_at=str(attachment.get("created_at") or _iso(self.now())),
                expires_at=expires_at,
                retention_days=int(attachment.get("retention_days") or 360),
            )
            self.repository.add_domain_outbox(
                event_type="file.attachment.imported",
                aggregate_type="managed_file_version",
                aggregate_id=version_id,
                payload={
                    "attachment_id": str(attachment["id"]),
                    "file_id": file_id,
                    "version_id": version_id,
                    "workspace_id": workspace_id,
                    "size_bytes": size_bytes,
                    "content_sha256": content_sha256,
                    "format_code": definition.code.value,
                },
            )

    def _publish_attachment_document(
        self,
        *,
        attachment: dict[str, Any],
        object_key: str,
        size_bytes: int,
        content_sha256: str,
        source: ValidatedDocumentSource,
    ) -> None:
        workspace_id = str(attachment.get("task_workspace_id") or "")
        if not workspace_id or self.document_processing is None:
            self._deny("document_processing_unavailable", "文档处理依赖尚未就绪")
        existing = self.repository.database.execute_one(
            "select * from message_attachment_file_binding where attachment_id = ?",
            (attachment["id"],),
        )
        if existing is not None:
            version = self.repository.get_version(str(existing["version_id"]))
            if (
                str(version["content_sha256"]) != content_sha256
                or int(version["size_bytes"]) != size_bytes
            ):
                self._deny(
                    "file_attachment_idempotency_conflict",
                    "附件标识已绑定不同内容",
                )
            return
        with self.repository.database.unit_of_work():
            workspace = self.repository.get_workspace(workspace_id)
            if str(workspace["status"]) != "ACTIVE":
                self._deny("file_workspace_expired", "任务文件工作区已失效")
            requested_name = self._canonical_document_attachment_name(
                requested=str(attachment["file_name"]),
                source=source,
            )
            display_name = self._available_attachment_name(
                workspace_id=workspace_id,
                requested=requested_name,
            )
            file_id = _opaque("managed_file")
            version_id = _opaque("file_version")
            self.repository.create_file(
                file_id=file_id,
                tenant_id=str(workspace["tenant_id"]),
                owner=self._owner(workspace),
                display_name=display_name,
                actor_id="file-worker",
                source_received_at=str(attachment.get("created_at") or "") or None,
                format_code=source.format_code.value,
            )
            self.repository.create_version(
                version_id=version_id,
                file_id=file_id,
                version_number=1,
                version_kind=FileVersionKind.ATTACHMENT,
                status=FileVersionStatus.AVAILABLE,
                media_type=source.media_type,
                encoding="",
                size_bytes=size_bytes,
                content_sha256=content_sha256,
                object_key=object_key,
                source_kind=FileSourceKind.MESSAGE_ATTACHMENT,
                actor_id="file-worker",
                format_code=source.format_code.value,
                source_reference_digest=content_sha256,
                advance_current_from="",
            )
            self.repository.link_workspace_file(
                workspace_id=workspace_id,
                file_id=file_id,
                version_id=version_id,
                logical_name=display_name,
                role=WorkspaceFileRole.INPUT,
            )
            self.repository.add_external_reference(
                file_id=file_id,
                version_id=version_id,
                provider=(
                    "DINGTALK"
                    if str(attachment.get("source_channel") or "").startswith("ding")
                    else "CHANNEL"
                ),
                source_type="CHAT_ATTACHMENT",
                source_id=str(attachment["id"]),
                source_digest=content_sha256,
            )
            expires_at = self._attachment_expiry(attachment)
            self.repository.bind_attachment(
                attachment_id=str(attachment["id"]),
                file_id=file_id,
                version_id=version_id,
                retention_expires_at=expires_at,
            )
            self.repository.add_retention(
                version_id=version_id,
                reason=RetentionReason.MESSAGE_ATTACHMENT,
                source_id=str(attachment["id"]),
                starts_at=str(attachment.get("created_at") or _iso(self.now())),
                expires_at=expires_at,
                retention_days=int(attachment.get("retention_days") or 360),
            )
            run = self.document_processing.request_processing(
                tenant_id=str(workspace["tenant_id"]),
                source_file_id=file_id,
                source_version_id=version_id,
                actor_id="file-worker",
                correlation_id=str(attachment.get("id") or "")[:128],
                profile_code=self._workspace_document_profile(str(workspace["id"])),
            )
            self.repository.database.execute(
                """
                update message_attachment
                   set readability_status = 'PENDING', file_processing_run_id = ?,
                       readability_error_code = '', readability_updated_at = ?
                 where id = ?
                """,
                (run["id"], _iso(self.now()), attachment["id"]),
            )

    def _ensure_attachment_cleanup(
        self, attachment_id: str, *, reason: str = "RETENTION_EXPIRED"
    ) -> None:
        row = self.repository.database.execute_one(
            "select expires_at, created_at from message_attachment where id = ?",
            (attachment_id,),
        )
        if row is None:
            return
        exists = self.repository.database.execute_one(
            """
            select id from file_cleanup_fact
             where resource_type = 'ATTACHMENT_CONTENT' and resource_id = ?
               and reason = ?
            """,
            (attachment_id, reason),
        )
        if exists is not None:
            return
        due_at = str(row.get("expires_at") or self._attachment_expiry(row))
        self.repository.enqueue_cleanup(
            resource_type=CleanupResourceType.ATTACHMENT_CONTENT,
            resource_id=attachment_id,
            reason=reason,
            due_at=due_at,
        )

    def _attachment_receipt(self, attachment_id: str) -> dict[str, Any]:
        row = self.repository.database.execute_one(
            """
            select a.id as attachment_id, a.size_bytes, a.sha256,
                   a.readability_status, a.file_processing_run_id,
                   b.file_id, b.version_id
              from message_attachment a
              left join message_attachment_file_binding b on b.attachment_id = a.id
             where a.id = ?
            """,
            (attachment_id,),
        )
        if row is None:
            self._deny("file_attachment_not_found", "未找到聊天附件")
        assert row is not None
        return {
            "attachment_id": attachment_id,
            "size_bytes": int(row.get("size_bytes") or 0),
            "sha256": str(row.get("sha256") or ""),
            "file_id": str(row.get("file_id") or ""),
            "version_id": str(row.get("version_id") or ""),
            "readability_status": str(row.get("readability_status") or "NOT_REQUIRED"),
            "processing_run_id": str(row.get("file_processing_run_id") or ""),
            "status": "IMPORTED",
        }

    def _available_attachment_name(self, *, workspace_id: str, requested: str) -> str:
        occupied = {
            str(row["logical_name"])
            for row in self.repository.database.execute(
                """
            select logical_name from task_workspace_file
             where workspace_id = ? and status = 'ACTIVE'
            """,
                (workspace_id,),
            )
        }
        if requested not in occupied:
            return requested
        path = Path(requested)
        suffix = path.suffix
        stem = path.stem or "attachment"
        for sequence in range(2, len(occupied) + 2):
            marker = f" ({sequence})"
            stem_limit = max(1, 255 - len(marker) - len(suffix))
            candidate = f"{stem[:stem_limit]}{marker}{suffix}"
            if candidate not in occupied:
                return candidate
        self._deny(
            "file_workspace_name_conflict",
            "任务工作区中无法生成唯一文件名",
        )

    @staticmethod
    def _canonical_document_attachment_name(
        *, requested: str, source: ValidatedDocumentSource
    ) -> str:
        path = Path(requested)
        if path.suffix.lower() == source.canonical_extension:
            return requested
        stem = path.stem[:220] or "attachment"
        return f"{stem}{source.canonical_extension}"

    def _attachment_expiry(self, attachment: dict[str, Any]) -> str:
        existing = str(attachment.get("expires_at") or "")
        if existing:
            return existing
        created = str(attachment.get("created_at") or "")
        try:
            starts_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except ValueError:
            starts_at = self.now()
        if starts_at.tzinfo is None:
            starts_at = starts_at.replace(tzinfo=UTC)
        days = int(attachment.get("retention_days") or 360)
        return _iso(starts_at + timedelta(days=days))

    def _publish(self, *, intent_id: str, staging_id: str) -> dict[str, Any]:
        database = self.repository.database
        with database.unit_of_work():
            intent = self.repository.get_commit_intent(intent_id)
            terminal = self._terminal_receipt(intent)
            if terminal is not None:
                return terminal
            if str(intent["status"]) != "UPLOADING":
                self._deny("file_commit_state_invalid", "文件提交状态已变化")
            staging = self.repository.get_staging(staging_id)
            if (
                str(staging["status"]) != "COMPLETE"
                or str(staging["content_sha256"]) != str(intent["content_sha256"])
                or int(staging["size_bytes"]) != int(intent["size_bytes"])
            ):
                self._deny("file_commit_staging_invalid", "文件提交暂存校验失败")
            self._lock("task_workspace", str(intent["workspace_id"]))
            workspace = self.repository.get_workspace(str(intent["workspace_id"]))
            if str(workspace["status"]) != "ACTIVE":
                self._deny("file_workspace_expired", "任务文件工作区已失效")
            definition = validate_format_action(
                format_code=str(intent.get("format_code") or "TXT"),
                action=FileAction.COMMIT,
            )
            named = text_format_for_name(
                str(intent["display_name"]),
            )
            if named.code is not definition.code:
                self._deny("file_format_mismatch", "文件名与提交格式不一致")
            target_file_id = str(intent.get("target_file_id") or "")
            if target_file_id:
                return self._publish_existing(intent, staging, workspace)
            return self._publish_new(intent, staging, workspace)

    def _publish_existing(
        self,
        intent: dict[str, Any],
        staging: dict[str, Any],
        workspace: dict[str, Any],
    ) -> dict[str, Any]:
        file_id = str(intent["target_file_id"])
        self._lock("managed_file", file_id)
        file_row = self.repository.get_file(file_id)
        self._require_owner_boundary(file_row, workspace)
        current_version_id = str(file_row.get("current_version_id") or "")
        base_version_id = str(intent["base_version_id"])
        format_code = str(intent.get("format_code") or "TXT")
        base_version = self.repository.require_content_available(base_version_id)
        if (
            str(file_row.get("format_code") or "TXT") != format_code
            or str(base_version.get("format_code") or "TXT") != format_code
            or str(base_version.get("file_id") or "") != file_id
        ):
            self._deny("file_format_mismatch", "修改文件时不得改变文件格式")
        definition = get_text_format_policy().by_code(format_code)
        version_id = _opaque("file_version")
        version_number = self._next_version_number(file_id)
        conflict = current_version_id != base_version_id
        self.repository.create_version(
            version_id=version_id,
            file_id=file_id,
            version_number=version_number,
            version_kind=FileVersionKind.CONFLICT if conflict else FileVersionKind.WORKING,
            status=FileVersionStatus.CONFLICT if conflict else FileVersionStatus.AVAILABLE,
            media_type=definition.canonical_media_type,
            encoding="utf-8",
            size_bytes=int(intent["size_bytes"]),
            content_sha256=str(intent["content_sha256"]),
            object_key=str(staging["object_key"]),
            source_kind=FileSourceKind.CONFLICT if conflict else FileSourceKind.AGENT_EDITED,
            actor_id=str(intent["job_id"]),
            format_code=definition.code.value,
            parent_version_id=current_version_id or None,
            base_version_id=base_version_id,
            advance_current_from=None if conflict else base_version_id,
        )
        if conflict:
            self.repository.record_conflict(
                intent_id=str(intent["id"]),
                file_id=file_id,
                base_version_id=base_version_id,
                current_version_id=current_version_id,
                candidate_version_id=version_id,
            )
            status = CommitIntentStatus.CONFLICT
        else:
            self.repository.update_workspace_file_version(
                workspace_id=str(workspace["id"]),
                file_id=file_id,
                version_id=version_id,
                role=WorkspaceFileRole.WORKING,
                logical_name=str(intent["display_name"]),
            )
            status = CommitIntentStatus.COMMITTED
        return self._finish_publish(intent, staging, version_id=version_id, status=status)

    def _publish_new(
        self,
        intent: dict[str, Any],
        staging: dict[str, Any],
        workspace: dict[str, Any],
    ) -> dict[str, Any]:
        file_id = _opaque("managed_file")
        version_id = _opaque("file_version")
        owner = self._owner(workspace)
        definition = get_text_format_policy().by_code(
            str(intent.get("format_code") or "TXT")
        )
        self.repository.create_file(
            file_id=file_id,
            tenant_id=str(workspace["tenant_id"]),
            owner=owner,
            display_name=str(intent["display_name"]),
            actor_id=str(intent["job_id"]),
            format_code=definition.code.value,
        )
        self.repository.create_version(
            version_id=version_id,
            file_id=file_id,
            version_number=1,
            version_kind=FileVersionKind.OUTPUT,
            status=FileVersionStatus.AVAILABLE,
            media_type=definition.canonical_media_type,
            encoding="utf-8",
            size_bytes=int(intent["size_bytes"]),
            content_sha256=str(intent["content_sha256"]),
            object_key=str(staging["object_key"]),
            source_kind=FileSourceKind.AGENT_GENERATED,
            actor_id=str(intent["job_id"]),
            format_code=definition.code.value,
            advance_current_from="",
        )
        self.repository.link_workspace_file(
            workspace_id=str(workspace["id"]),
            file_id=file_id,
            version_id=version_id,
            logical_name=str(intent["display_name"]),
            role=WorkspaceFileRole.OUTPUT,
        )
        return self._finish_publish(
            intent, staging, version_id=version_id, status=CommitIntentStatus.COMMITTED
        )

    def _finish_publish(
        self,
        intent: dict[str, Any],
        staging: dict[str, Any],
        *,
        version_id: str,
        status: CommitIntentStatus,
    ) -> dict[str, Any]:
        self.repository.update_staging(
            staging_id=str(staging["id"]), status=StagingStatus.PUBLISHED
        )
        self.repository.transition_commit_intent(
            str(intent["id"]),
            status,
            result_version_id=version_id if status is CommitIntentStatus.COMMITTED else None,
            conflict_version_id=version_id if status is CommitIntentStatus.CONFLICT else None,
        )
        self.repository.add_domain_outbox(
            event_type=(
                "file.version.committed"
                if status is CommitIntentStatus.COMMITTED
                else "file.version.conflict_created"
            ),
            aggregate_type="managed_file_version",
            aggregate_id=version_id,
            payload={
                "file_id": str(self.repository.get_version(version_id)["file_id"]),
                "version_id": version_id,
                "job_id": str(intent["job_id"]),
                "workspace_id": str(intent["workspace_id"]),
                "status": status.value,
                "size_bytes": int(intent["size_bytes"]),
                "content_sha256": str(intent["content_sha256"]),
                "format_code": str(intent.get("format_code") or "TXT"),
            },
        )
        return self._commit_receipt(intent, version_id=version_id, status=status.value)

    def _record_compensation(
        self,
        *,
        intent: dict[str, Any],
        staging: dict[str, Any],
        failure_code: str = "file_commit_publish_failed",
    ) -> None:
        try:
            with self.repository.database.unit_of_work():
                current = self.repository.get_commit_intent(str(intent["id"]))
                if str(current["status"]) in {"COMMITTED", "CONFLICT"}:
                    return
                self.repository.update_staging(
                    staging_id=str(staging["id"]),
                    status=StagingStatus.CLEANUP_PENDING,
                    failure_code=failure_code,
                )
                self.repository.enqueue_cleanup(
                    resource_type=CleanupResourceType.STAGING_OBJECT,
                    resource_id=str(staging["id"]),
                    reason="COMMIT_PUBLISH_FAILED",
                    due_at=_iso(self.now()),
                )
                if str(current["status"]) == "UPLOADING":
                    self.repository.transition_commit_intent(
                        str(current["id"]),
                        CommitIntentStatus.REJECTED,
                        failure_code=failure_code,
                    )
        except Exception:
            # Never hide the original upload/publish failure. A periodic staging
            # scan remains able to discover an unreferenced non-published object.
            return

    def _terminal_receipt(self, intent: dict[str, Any]) -> dict[str, Any] | None:
        status = str(intent["status"])
        version_id = str(
            intent.get("result_version_id") or intent.get("conflict_candidate_version_id") or ""
        )
        if status not in {"COMMITTED", "CONFLICT"} or not version_id:
            return None
        return self._commit_receipt(intent, version_id=version_id, status=status)

    def _commit_receipt(
        self,
        intent: dict[str, Any],
        *,
        version_id: str,
        status: str,
    ) -> dict[str, Any]:
        version = self.repository.get_version(version_id)
        file_id = str(version["file_id"])
        delivery_id = ""
        delivery_status = "NOT_REQUESTED"
        if (
            status == CommitIntentStatus.COMMITTED.value
            and str(intent["delivery_mode"]) == CommitDeliveryMode.DEFAULT.value
            and self.delivery_intents is not None
        ):
            delivery = self.delivery_intents.enqueue(
                job_id=str(intent["job_id"]),
                file_id=file_id,
                version_id=version_id,
                display_name=str(intent["display_name"]),
            )
            delivery_id = str(delivery["delivery_id"])
            delivery_status = str(delivery["status"])
        return {
            "file_id": file_id,
            "version_id": version_id,
            "size_bytes": int(intent["size_bytes"]),
            "sha256": str(intent["content_sha256"]),
            "status": status,
            "delivery_id": delivery_id,
            "delivery_status": delivery_status,
            "format_code": str(version.get("format_code") or "TXT"),
        }

    @staticmethod
    def _is_logical_name_conflict(exc: Exception) -> bool:
        constraint_name = str(getattr(getattr(exc, "diag", None), "constraint_name", "") or "")
        if constraint_name == "uq_task_workspace_file_active_name":
            return True
        detail = str(exc).lower()
        return "uq_task_workspace_file_active_name" in detail or (
            "unique" in detail
            and "task_workspace_file.workspace_id" in detail
            and "task_workspace_file.logical_name" in detail
        )

    def _lock(self, table: str, identity: str) -> None:
        if table not in {"task_workspace", "managed_file"}:
            raise RuntimeError("Unsupported task-file lock")
        suffix = " for update" if self.repository.database.engine == "postgres" else ""
        row = self.repository.database.execute_one(
            f"select id from {table} where id = ?{suffix}", (identity,)
        )
        if row is None:
            self._deny("file_state_conflict", "文件状态已变化，请重试")

    def _next_version_number(self, file_id: str) -> int:
        row = self.repository.database.execute_one(
            "select coalesce(max(version_number), 0) + 1 as value from managed_file_version where file_id = ?",
            (file_id,),
        )
        return int(cast(dict[str, Any], row)["value"])

    def _workspace_document_profile(self, workspace_id: str) -> str:
        row = self.repository.database.execute_one(
            """
            select p.document_processing_profile_code
              from task_workspace w
              join business_application_publication p
                on p.id = w.business_application_publication_id
             where w.id = ?
            """,
            (workspace_id,),
        )
        if row is None:
            self._deny("file_workspace_expired", "任务文件工作区已失效")
        assert row is not None
        code = str(row.get("document_processing_profile_code") or "NONE")
        if code not in {
            "NONE",
            "docling-layout-ocr-v2",
        }:
            self._deny("document_processing_profile_invalid", "文档处理Profile无效")
        return code

    @staticmethod
    def _item_actions(item: dict[str, Any]) -> list[str]:
        try:
            actions = json.loads(str(item.get("allowed_actions_json") or "[]"))
        except json.JSONDecodeError as exc:
            raise NonRetryableExecutionError(
                "Job File Manifest actions are invalid",
                safe_message="任务文件清单无效",
                error_code="file_manifest_actions_invalid",
            ) from exc
        if not isinstance(actions, list) or any(not isinstance(value, str) for value in actions):
            GovernedFileStreamingService._deny("file_manifest_actions_invalid", "任务文件清单无效")
        return cast(list[str], actions)

    @staticmethod
    def _require_commit_binding(
        intent: dict[str, Any],
        *,
        claims: dict[str, Any],
        context: FileAuthorizationContext,
    ) -> None:
        if (
            str(intent["job_id"]) != str(claims["job_id"])
            or str(intent["workspace_id"]) != str(context.workspace["id"])
        ):
            GovernedFileStreamingService._deny(
                "file_commit_binding_mismatch", "文件提交与当前任务不匹配"
            )

    @staticmethod
    def _require_owner_boundary(file_row: dict[str, Any], workspace: dict[str, Any]) -> None:
        for field in (
            "tenant_id",
            "owner_type",
            "owner_user_id",
            "owner_enterprise_id",
            "owner_connector_id",
            "owner_conversation_id",
        ):
            if str(file_row.get(field) or "") != str(workspace.get(field) or ""):
                GovernedFileStreamingService._deny(
                    "file_owner_boundary_denied", "当前任务无权修改该文件"
                )

    @staticmethod
    def _owner(workspace: dict[str, Any]) -> FileOwner:
        owner_type = WorkspaceOwnerType(str(workspace["owner_type"]))
        return FileOwner(
            owner_type,
            user_id=str(workspace.get("owner_user_id") or ""),
            enterprise_id=str(workspace.get("owner_enterprise_id") or ""),
            connector_id=str(workspace.get("owner_connector_id") or ""),
            conversation_id=str(workspace.get("owner_conversation_id") or ""),
        )

    def _deny_unreadable_document(self, *, file_id: str, version_id: str) -> None:
        row = self.repository.database.execute_one(
            """
            select f.format_code,
                   coalesce((
                     select a.readability_status
                       from message_attachment_file_binding b
                       join message_attachment a on a.id = b.attachment_id
                      where b.version_id = v.id
                      order by a.readability_updated_at desc, a.id desc
                      limit 1
                   ), 'NOT_REQUIRED') as readability_status
              from managed_file f
              join managed_file_version v on v.file_id = f.id
             where f.id = ? and v.id = ?
            """,
            (file_id, version_id),
        )
        if row is None:
            return
        format_code = str(row.get("format_code") or "")
        readability = str(row.get("readability_status") or "NOT_REQUIRED")
        if format_code not in {"PDF", "DOCX", "PPTX", "XLSX", "PNG", "JPEG", "WEBP"} and (
            readability == "NOT_REQUIRED"
        ):
            return
        markdown = self.repository.database.execute_one(
            """
            select status
              from file_representation
             where source_version_id = ? and kind = 'MARKDOWN'
               and status in ('AVAILABLE', 'PARTIAL')
             order by created_at desc
             limit 1
            """,
            (version_id,),
        )
        if markdown is not None:
            return
        if readability in {"NO_TEXT", "UNAVAILABLE"}:
            self._deny("file_processing_failed", "文档可读内容生成失败")
        self._deny("file_readable_content_not_ready", "文档可读内容尚未生成")

    @staticmethod
    def _deny(code: str, safe_message: str) -> Never:
        raise NonRetryableExecutionError(
            "Governed file streaming operation denied",
            safe_message=safe_message,
            error_code=code,
        )
