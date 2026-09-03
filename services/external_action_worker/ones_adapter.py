from __future__ import annotations

from dataclasses import replace
import json
from typing import Any

from app.modules.external_action.domain import json_hash
from app.modules.external_action.repository import ExternalActionRepository
from app.modules.identity.application.ones_identity import OnesIdentityVerifier
from app.modules.identity.infrastructure.ones_identity_verifier import (
    UrllibOnesIdentityVerifier,
)
from app.modules.mcp_audit import McpAuditCoordinator
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.shared.config import OnesIdentitySettings
from app.shared.exceptions import NonRetryableExecutionError, RetryableExecutionError
from app.shared.ones_tool_contracts import (
    ONES_CREATE_BUG_TOOL_IDENTIFIER,
    ONES_UPDATE_TASK_TOOL_IDENTIFIER,
    require_ones_tool_contract,
)
from services.external_action_worker.runtime import ExternalActionExecutionOutcome
from services.ones_mcp_server.provider.http_client import OnesProviderHttpClient
from services.ones_mcp_server.provider.bug_create import OnesBugCreateProvider
from services.ones_mcp_server.provider.target import validate_provider_target
from services.ones_mcp_server.provider.task_update import OnesTaskUpdateProvider
from services.ones_mcp_server.errors import OnesProviderUnauthorized
from services.ones_mcp_server.task_update import compile_task_update
from services.ones_mcp_server.task_update_catalog import TaskUpdateFieldCatalog
from services.ones_mcp_server.bug_create import compile_bug_create, compiled_bug_matches_readback
from services.ones_mcp_server.bug_create_catalog import BugCreateFieldCatalog


def _authorization_denied(
    code: str,
    safe_message: str,
    internal_message: str,
) -> NonRetryableExecutionError:
    return NonRetryableExecutionError(
        internal_message,
        safe_message=safe_message,
        error_code=code,
    )


class OnesExternalActionAdapter:
    def __init__(
        self,
        runtime: Any,
        *,
        login_verifier: OnesIdentityVerifier | None = None,
        create_provider: OnesBugCreateProvider | None = None,
    ) -> None:
        self.runtime = runtime
        self.catalog = TaskUpdateFieldCatalog.load()
        self.create_catalog = BugCreateFieldCatalog.load()
        self._provider: OnesTaskUpdateProvider | None = None
        self._create_provider = create_provider
        self._login_verifier = login_verifier

    @property
    def provider(self) -> OnesTaskUpdateProvider:
        if self._provider is not None:
            return self._provider
        target = validate_provider_target(
            self.runtime.settings.ones_mcp.provider_base_url,
            allowed_hosts=self.runtime.settings.ones_mcp.provider_allowed_hosts,
            app_env=self.runtime.settings.environment,
            allow_insecure_local=self.runtime.settings.ones_mcp.allow_insecure_local,
        )
        self._provider = OnesTaskUpdateProvider(
            OnesProviderHttpClient(
                target,
                timeout_seconds=self.runtime.settings.ones_mcp.timeout_seconds,
                max_response_bytes=self.runtime.settings.ones_mcp.max_response_bytes,
            ),
            catalog=self.catalog,
        )
        return self._provider

    @property
    def create_provider(self) -> OnesBugCreateProvider:
        if self._create_provider is not None:
            return self._create_provider
        target = validate_provider_target(
            self.runtime.settings.ones_mcp.provider_base_url,
            allowed_hosts=self.runtime.settings.ones_mcp.provider_allowed_hosts,
            app_env=self.runtime.settings.environment,
            allow_insecure_local=self.runtime.settings.ones_mcp.allow_insecure_local,
        )
        self._create_provider = OnesBugCreateProvider(
            OnesProviderHttpClient(
                target,
                timeout_seconds=self.runtime.settings.ones_mcp.timeout_seconds,
                max_response_bytes=self.runtime.settings.ones_mcp.max_response_bytes,
            ),
            catalog=self.create_catalog,
        )
        return self._create_provider

    @property
    def login_verifier(self) -> OnesIdentityVerifier:
        if self._login_verifier is not None:
            return self._login_verifier
        target = validate_provider_target(
            self.runtime.settings.ones_mcp.provider_base_url,
            allowed_hosts=self.runtime.settings.ones_mcp.provider_allowed_hosts,
            app_env=self.runtime.settings.environment,
            allow_insecure_local=self.runtime.settings.ones_mcp.allow_insecure_local,
        )
        settings = replace(
            self.runtime.settings.ones_identity,
            base_url=target.base_url,
            allowed_hosts=(target.host,),
            timeout_seconds=self.runtime.settings.ones_mcp.timeout_seconds,
            max_response_bytes=self.runtime.settings.ones_mcp.max_response_bytes,
            allow_insecure_local=target.allow_insecure_local,
        )
        if not isinstance(settings, OnesIdentitySettings):
            raise TypeError("ONES identity settings are invalid")
        self._login_verifier = UrllibOnesIdentityVerifier(
            settings,
            environment=self.runtime.settings.environment,
        )
        return self._login_verifier

    def execute(self, intent: dict[str, Any]) -> ExternalActionExecutionOutcome:
        if str(intent.get("operation_code") or "") == "ones.task.create":
            return self._execute_create(intent)
        identity, credential = self._reauthorize(intent)
        precondition, request, provider_payload = self._validated_frozen_request(intent)
        try:
            snapshot, compiled = self._preflight(
                intent,
                identity,
                credential,
                request,
            )
        except OnesProviderUnauthorized:
            credential = self._refresh_credential(intent, identity, credential)
            try:
                snapshot, compiled = self._preflight(
                    intent,
                    identity,
                    credential,
                    request,
                )
            except OnesProviderUnauthorized:
                self._mark_reauth_required(
                    credential,
                    error_code="ones_provider_unauthorized_after_refresh",
                )
                raise NonRetryableExecutionError(
                    "ONES Provider rejected the refreshed credential",
                    safe_message="ONES 身份需要本人重新验证，本次更新未执行",
                    error_code="ones_credential_reverification_required",
                ) from None
        if snapshot.server_update_stamp != str(precondition.get("server_update_stamp") or ""):
            raise NonRetryableExecutionError(
                "ONES task changed after confirmation",
                safe_message="缺陷已发生变化，本次确认已失效，请重新发起",
                error_code="ones_task_update_precondition_changed",
            )
        if compiled is None:
            return ExternalActionExecutionOutcome(
                result={"updated": True, "verified": True, "already_applied": True},
                provider_request_id=snapshot.uuid,
                card_status_text="ONES 缺陷已是确认值，无需重复写入",
            )
        if compiled.provider_payload != provider_payload:
            raise NonRetryableExecutionError(
                "ONES frozen Provider payload drifted",
                safe_message="缺陷更新参数已失效，请重新发起",
                error_code="ones_task_update_payload_drift",
            )
        try:
            result = self.provider.update_task(
                team_uuid=str(intent["execution_scope_id"]),
                provider_user_id=str(identity["external_subject_id"]),
                token=credential.secrets.token,
                payload=provider_payload,
            )
        except RetryableExecutionError as uncertain:
            if self._readback_matches(intent, identity, credential, request):
                return ExternalActionExecutionOutcome(
                    result={"updated": True, "verified": True, "reconciled": True},
                    provider_request_id=snapshot.uuid,
                    card_status_text="ONES 缺陷更新结果已只读核对成功",
                )
            raise uncertain
        if not self._readback_matches(intent, identity, credential, request):
            raise NonRetryableExecutionError(
                "ONES update readback did not match confirmed values",
                safe_message="ONES 已受理更新，但回读值不一致，请人工核对",
                error_code="ones_task_update_readback_mismatch",
            )
        return ExternalActionExecutionOutcome(
            result={**result, "verified": True},
            provider_request_id=snapshot.uuid,
            card_status_text="ONES 缺陷更新成功",
        )

    def _execute_create(self, intent: dict[str, Any]) -> ExternalActionExecutionOutcome:
        identity, credential = self._reauthorize(intent)
        precondition, request = self._validated_frozen_create(intent)
        identity_revision = int(identity.get("revision") or 0)
        if identity_revision != int(precondition.get("identity_revision") or -1):
            raise NonRetryableExecutionError(
                "ONES identity revision changed after confirmation",
                safe_message="原 ONES 身份绑定已变化，本次创建未执行",
                error_code="ones_bug_create_identity_changed",
            )
        try:
            preflight = self.create_provider.preflight_create(
                team_uuid=str(intent["execution_scope_id"]),
                provider_user_id=str(identity["external_subject_id"]),
                token=credential.secrets.token,
                arguments=request,
            )
        except OnesProviderUnauthorized:
            credential = self._refresh_credential(intent, identity, credential)
            try:
                preflight = self.create_provider.preflight_create(
                    team_uuid=str(intent["execution_scope_id"]),
                    provider_user_id=str(identity["external_subject_id"]),
                    token=credential.secrets.token,
                    arguments=request,
                )
            except OnesProviderUnauthorized:
                self._mark_reauth_required(
                    credential,
                    error_code="ones_provider_unauthorized_after_refresh",
                )
                raise NonRetryableExecutionError(
                    "ONES Provider rejected the refreshed credential",
                    safe_message="ONES 身份需要本人重新验证，本次创建未执行",
                    error_code="ones_credential_reverification_required",
                ) from None
        if (
            preflight.layout_version != str(precondition.get("layout_version") or "")
            or preflight.validation_hash != str(precondition.get("validation_hash") or "")
        ):
            raise NonRetryableExecutionError(
                "ONES defect-create preflight changed after confirmation",
                safe_message="ONES 创建权限、布局或引用值已变化，请重新生成提案",
                error_code="ones_bug_create_precondition_changed",
            )
        compiled = compile_bug_create(
            request,
            catalog=self.create_catalog,
            team_uuid=str(intent["execution_scope_id"]),
            task_uuid=str(intent["target_resource_id"]),
            current_user_uuid=str(identity["external_subject_id"]),
            display_values=preflight.display_values,
        )
        request_hash = self.create_provider.request_hash(compiled.provider_payload)
        repository = ExternalActionRepository(self.runtime.database)
        attempt, started = repository.mark_provider_attempt_started(
            str(intent["id"]),
            request_hash=request_hash,
            catalog_hash=self.create_catalog.content_sha256,
        )
        if not started:
            if (
                str(attempt.get("provider_attempt_status") or "") != "STARTED"
                or str(attempt.get("provider_request_hash") or "") != request_hash
                or str(attempt.get("provider_catalog_hash") or "")
                != self.create_catalog.content_sha256
            ):
                raise NonRetryableExecutionError(
                    "ONES create Provider attempt facts are invalid",
                    safe_message="缺陷创建尝试记录不一致，请人工核对",
                    error_code="ones_bug_create_attempt_invalid",
                )
            return self._reconcile_create(
                intent,
                identity,
                credential,
                compiled,
                status_text="原创建尝试已开始，已按固定标识完成只读核验",
            )
        self.runtime.audit_service.record(
            "external_action.provider_attempt_started",
            status="STARTED",
            summary="ONES defect create Provider attempt persisted before external I/O",
            job_id=str(intent["job_id"]),
            actor_id=str(intent["actor_user_id"]),
            payload={
                "action_intent_id": str(intent["id"]),
                "operation_code": "ones.task.create",
                "request_hash": request_hash,
                "field_catalog_hash": self.create_catalog.content_sha256,
            },
        )
        try:
            try:
                result = self.create_provider.create_bug(
                    team_uuid=str(intent["execution_scope_id"]),
                    provider_user_id=str(identity["external_subject_id"]),
                    token=credential.secrets.token,
                    payload=compiled.provider_payload,
                )
            except OnesProviderUnauthorized:
                credential = self._refresh_credential(intent, identity, credential)
                try:
                    result = self.create_provider.create_bug(
                        team_uuid=str(intent["execution_scope_id"]),
                        provider_user_id=str(identity["external_subject_id"]),
                        token=credential.secrets.token,
                        payload=compiled.provider_payload,
                    )
                except OnesProviderUnauthorized:
                    self._mark_reauth_required(
                        credential,
                        error_code="ones_provider_unauthorized_after_refresh",
                    )
                    raise NonRetryableExecutionError(
                        "ONES Provider rejected the refreshed credential",
                        safe_message="ONES 身份需要本人重新验证，本次创建未执行",
                        error_code="ones_credential_reverification_required",
                    ) from None
        except RetryableExecutionError as uncertain:
            try:
                return self._reconcile_create(
                    intent,
                    identity,
                    credential,
                    compiled,
                    status_text="ONES 缺陷创建结果已按固定标识核验成功",
                )
            except RetryableExecutionError:
                raise uncertain
        except NonRetryableExecutionError as provider_error:
            if str(getattr(provider_error, "error_code", "")) in {
                "ones_provider_forbidden",
                "ones_provider_operation_unavailable",
                "ones_provider_request_rejected",
                "ones_bug_create_payload_invalid",
                "ones_credential_identity_changed",
                "ones_credential_reverification_required",
            }:
                raise
            try:
                return self._reconcile_create(
                    intent,
                    identity,
                    credential,
                    compiled,
                    status_text="ONES 返回无效结果后已按固定标识核验创建成功",
                )
            except RetryableExecutionError as readback_error:
                raise readback_error from provider_error
        except Exception as provider_error:
            try:
                return self._reconcile_create(
                    intent,
                    identity,
                    credential,
                    compiled,
                    status_text="ONES 调用中断后已按固定标识核验创建成功",
                )
            except RetryableExecutionError as readback_error:
                raise readback_error from provider_error
        reconciled = self._reconcile_create(
            intent,
            identity,
            credential,
            compiled,
            status_text="ONES 缺陷创建成功并已完整回查",
        )
        return ExternalActionExecutionOutcome(
            result={**result, **reconciled.result, "verified": True},
            provider_request_id=str(intent["target_resource_id"]),
            card_status_text=reconciled.card_status_text,
            card_fields=reconciled.card_fields,
        )

    def _reconcile_create(
        self,
        intent: dict[str, Any],
        identity: dict[str, Any],
        credential: Any,
        compiled: Any,
        *,
        status_text: str,
    ) -> ExternalActionExecutionOutcome:
        try:
            readback = self.create_provider.read_created_bug(
                team_uuid=str(intent["execution_scope_id"]),
                task_uuid=str(intent["target_resource_id"]),
                provider_user_id=str(identity["external_subject_id"]),
                token=credential.secrets.token,
            )
        except Exception as exc:
            raise RetryableExecutionError(
                "ONES defect-create readback failed after Provider attempt",
                safe_message="缺陷创建结果无法可靠核验，请人工核对",
                error_code="ones_bug_create_readback_unavailable",
            ) from exc
        if readback is None or not compiled_bug_matches_readback(compiled, readback):
            raise RetryableExecutionError(
                "ONES defect-create readback did not match the confirmed snapshot",
                safe_message="缺陷创建结果不确定或回读字段不一致，请人工核对",
                error_code="ones_bug_create_readback_mismatch",
            )
        number = int(readback["number"])
        summary = compiled.summary
        fields = {
            str(item["label"]): str(item["value"])
            for item in summary["fields"]
            if isinstance(item, dict)
        }
        card_text = (
            f"缺陷编号：#{number}\n标题：{fields.get('标题', '')}\n"
            f"所属项目：{fields.get('所属项目', '')}\n负责人：{fields.get('负责人', '')}"
        )
        return ExternalActionExecutionOutcome(
            result={"created": True, "verified": True, "number": number},
            provider_request_id=str(intent["target_resource_id"]),
            card_status_text=status_text,
            card_fields={
                "providerName": "ONES",
                "operationName": "创建缺陷",
                "targetName": fields.get("标题", ""),
                "detailText": card_text,
            },
        )

    def _validated_frozen_create(
        self,
        intent: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        precondition = self._json_object(intent.get("precondition_json"))
        frozen = self._json_object(intent.get("arguments_json"))
        request = self._json_object(frozen.get("request"))
        McpAuditCoordinator.reject_auth_material(precondition)
        McpAuditCoordinator.reject_auth_material(frozen)
        if (
            not request
            or precondition.get("confirmed_values") != request
            or json_hash(precondition) != str(intent.get("precondition_hash") or "")
        ):
            raise NonRetryableExecutionError(
                "ONES frozen defect-create facts are invalid",
                safe_message="缺陷创建确认数据已失效，请重新发起",
                error_code="ones_bug_create_intent_invalid",
            )
        expected_fingerprint = json_hash(
            {
                "job_id": str(intent["job_id"]),
                "tool_identifier": str(intent["tool_identifier"]),
                "arguments_hash": json_hash(request),
                "execution_external_identity_id": str(intent["execution_external_identity_id"]),
                "execution_scope_id": str(intent["execution_scope_id"]),
                "target_resource_type": str(intent["target_resource_type"]),
                "target_resource_id": str(intent["target_resource_id"]),
                "precondition_hash": str(intent["precondition_hash"]),
                "field_catalog_hash": str(intent["field_catalog_hash"]),
            }
        )
        if expected_fingerprint != str(intent.get("intent_fingerprint") or ""):
            raise NonRetryableExecutionError(
                "ONES defect-create fingerprint is invalid",
                safe_message="缺陷创建确认数据已失效，请重新发起",
                error_code="ones_bug_create_intent_invalid",
            )
        return precondition, request

    def _preflight(
        self,
        intent: dict[str, Any],
        identity: dict[str, Any],
        credential: Any,
        request: dict[str, Any],
    ) -> tuple[Any, Any]:
        snapshot = self.provider.read_task(
            team_uuid=str(intent["execution_scope_id"]),
            task_uuid=str(intent["target_resource_id"]),
            provider_user_id=str(identity["external_subject_id"]),
            token=credential.secrets.token,
        )
        resolved = self.provider.resolve_entities(
            snapshot=snapshot,
            arguments=request,
            provider_user_id=str(identity["external_subject_id"]),
            token=credential.secrets.token,
        )
        return snapshot, compile_task_update(
            request,
            snapshot=snapshot,
            catalog=self.catalog,
            resolved_entities=resolved,
        )

    def _refresh_credential(
        self,
        intent: dict[str, Any],
        identity: dict[str, Any],
        credential: Any,
    ) -> Any:
        repository = self.runtime.external_identity_credential_repository
        try:
            verified = self.login_verifier.verify(
                email=credential.secrets.email,
                password=credential.secrets.password,
            )
            if (
                verified.user_uuid != str(identity["external_subject_id"])
                or str(intent["execution_scope_id"]) not in verified.team_uuids
            ):
                raise NonRetryableExecutionError(
                    "ONES identity or Team changed during credential refresh",
                    safe_message="ONES 身份信息已变化，请本人重新验证",
                    error_code="ones_credential_identity_changed",
                )
            repository.rotate_token(
                credential_id=credential.id,
                expected_revision=credential.revision,
                token=verified.token,
            )
            refreshed = repository.resolve_active(credential.id)
            self.runtime.audit_service.record(
                "external_action.ones_credential_refreshed",
                status="SUCCEEDED",
                summary="ONES credential refreshed before confirmed write",
                job_id=str(intent["job_id"]),
                actor_id=str(intent["actor_user_id"]),
                payload={
                    "action_intent_id": str(intent["id"]),
                    "credential_revision": refreshed.revision,
                },
            )
            return refreshed
        except Exception as exc:
            self._mark_reauth_required(
                credential,
                error_code=str(getattr(exc, "error_code", "") or "ones_credential_refresh_failed"),
            )
            raise NonRetryableExecutionError(
                "ONES credential refresh failed before confirmed write",
                safe_message="ONES 身份需要本人重新验证，本次更新未执行",
                error_code="ones_credential_reverification_required",
            ) from exc

    def _mark_reauth_required(self, credential: Any, *, error_code: str) -> None:
        try:
            self.runtime.external_identity_credential_repository.mark_reauth_required(
                credential_id=credential.id,
                expected_revision=credential.revision,
                error_code=error_code,
            )
        except Exception:
            pass

    def reconcile_interrupted(
        self,
        intent: dict[str, Any],
    ) -> ExternalActionExecutionOutcome | None:
        try:
            if str(intent.get("operation_code") or "") == "ones.task.create":
                if str(intent.get("provider_attempt_status") or "") != "STARTED":
                    return None
                identity, credential = self._reauthorize(intent)
                precondition, request = self._validated_frozen_create(intent)
                display_values = self._json_object(precondition.get("display_values"))
                if not display_values:
                    return None
                compiled = compile_bug_create(
                    request,
                    catalog=self.create_catalog,
                    team_uuid=str(intent["execution_scope_id"]),
                    task_uuid=str(intent["target_resource_id"]),
                    current_user_uuid=str(identity["external_subject_id"]),
                    display_values=display_values,
                )
                return self._reconcile_create(
                    intent,
                    identity,
                    credential,
                    compiled,
                    status_text="Worker 中断后已按固定标识核验 ONES 缺陷创建成功",
                )
            identity, credential = self._reauthorize(intent)
            _precondition, request, _provider_payload = self._validated_frozen_request(intent)
            if not self._readback_matches(intent, identity, credential, request):
                return None
            return ExternalActionExecutionOutcome(
                result={"updated": True, "verified": True, "reconciled": True},
                provider_request_id=str(intent["target_resource_id"]),
                card_status_text="Worker 中断后已只读核对 ONES 缺陷更新成功",
            )
        except Exception:
            return None

    def _validated_frozen_request(
        self,
        intent: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        precondition = self._json_object(intent.get("precondition_json"))
        frozen = self._json_object(intent.get("arguments_json"))
        request = self._json_object(frozen.get("request"))
        provider_payload = self._json_object(frozen.get("provider_payload"))
        McpAuditCoordinator.reject_auth_material(precondition)
        McpAuditCoordinator.reject_auth_material(frozen)
        if (
            not request
            or not provider_payload
            or request.get("uuid") != intent.get("target_resource_id")
            or precondition.get("confirmed_values") != request
            or json_hash(precondition) != str(intent.get("precondition_hash") or "")
        ):
            raise NonRetryableExecutionError(
                "ONES frozen execution facts are invalid",
                safe_message="缺陷更新确认数据已失效，请重新发起",
                error_code="ones_task_update_intent_invalid",
            )
        expected_fingerprint = json_hash(
            {
                "job_id": str(intent["job_id"]),
                "tool_identifier": str(intent["tool_identifier"]),
                "arguments_hash": json_hash(request),
                "execution_external_identity_id": str(intent["execution_external_identity_id"]),
                "execution_scope_id": str(intent["execution_scope_id"]),
                "target_resource_type": str(intent["target_resource_type"]),
                "target_resource_id": str(intent["target_resource_id"]),
                "precondition_hash": str(intent["precondition_hash"]),
                "field_catalog_hash": str(intent["field_catalog_hash"]),
            }
        )
        if expected_fingerprint != str(intent.get("intent_fingerprint") or ""):
            raise NonRetryableExecutionError(
                "ONES execution fingerprint is invalid",
                safe_message="缺陷更新确认数据已失效，请重新发起",
                error_code="ones_task_update_intent_invalid",
            )
        return precondition, request, provider_payload

    def _readback_matches(
        self,
        intent: dict[str, Any],
        identity: dict[str, Any],
        credential: Any,
        request: dict[str, Any],
        *,
        allow_credential_refresh: bool = True,
    ) -> bool:
        try:
            snapshot = self.provider.read_task(
                team_uuid=str(intent["execution_scope_id"]),
                task_uuid=str(intent["target_resource_id"]),
                provider_user_id=str(identity["external_subject_id"]),
                token=credential.secrets.token,
            )
            resolved = self.provider.resolve_entities(
                snapshot=snapshot,
                arguments=request,
                provider_user_id=str(identity["external_subject_id"]),
                token=credential.secrets.token,
            )
            return (
                compile_task_update(
                    request,
                    snapshot=snapshot,
                    catalog=self.catalog,
                    resolved_entities=resolved,
                )
                is None
            )
        except OnesProviderUnauthorized:
            if not allow_credential_refresh:
                return False
            try:
                refreshed = self._refresh_credential(intent, identity, credential)
            except Exception:
                return False
            return self._readback_matches(
                intent,
                identity,
                refreshed,
                request,
                allow_credential_refresh=False,
            )
        except Exception:
            return False

    def _reauthorize(self, intent: dict[str, Any]) -> tuple[dict[str, Any], Any]:
        tool_identifier = str(intent.get("tool_identifier") or "")
        if tool_identifier not in {
            ONES_UPDATE_TASK_TOOL_IDENTIFIER,
            ONES_CREATE_BUG_TOOL_IDENTIFIER,
        }:
            raise NonRetryableExecutionError(
                "ONES external action Tool is unsupported",
                safe_message="ONES 外部操作工具合同无效，请重新发起",
                error_code="ones_external_action_contract_drift",
            )
        is_create = tool_identifier == ONES_CREATE_BUG_TOOL_IDENTIFIER
        operation_label = "创建" if is_create else "更新"
        error_prefix = "ones_bug_create" if is_create else "ones_task_update"
        contract = require_ones_tool_contract(tool_identifier)
        definition = MCP_TOOL_MANIFEST.get(tool_identifier)
        if (
            contract.effect != "mutation"
            or definition is None
            or str(intent.get("execution_provider_code") or "") != "ones"
            or str(intent.get("confirmation_channel_code") or "") != "dingtalk"
            or str(intent.get("server_code") or "") != "ones-mcp"
            or definition.server_code != "ones-mcp"
            or str(intent.get("schema_hash") or "") != definition.schema_hash
            or str(intent.get("confirmation_policy") or "") != definition.confirmation_policy
            or str(intent.get("operation_code") or "") != definition.operation_code
            or str(intent.get("target_resource_type") or "") != "task"
            or not str(intent.get("target_resource_id") or "")
        ):
            raise NonRetryableExecutionError(
                "ONES external action manifest facts drifted",
                safe_message=(
                    "ONES 创建授权或工具合同已变化，请重新发起并确认"
                    if is_create
                    else "ONES 更新授权或工具合同已变化，请重新发起并确认"
                ),
                error_code=(
                    "ones_bug_create_contract_drift"
                    if is_create
                    else "ones_task_update_contract_drift"
                ),
            )
        expected_catalog = self.create_catalog if is_create else self.catalog
        if (
            str(intent.get("field_catalog_version") or "") != expected_catalog.catalog_version
            or str(intent.get("field_catalog_hash") or "") != expected_catalog.content_sha256
        ):
            raise NonRetryableExecutionError(
                "ONES external action field catalog facts drifted",
                safe_message=(
                    "缺陷创建字段目录已变化，请重新发起并确认"
                    if is_create
                    else "缺陷更新字段目录已变化，请重新发起并确认"
                ),
                error_code=(
                    "ones_bug_create_catalog_drift"
                    if is_create
                    else "ones_task_update_catalog_drift"
                ),
            )
        job = self.runtime.database.execute_one(
            """
            select j.session_id, j.internal_user_id, j.business_application_id,
                   j.agent_publication_id, j.business_application_publication_id,
                   j.source_connector_id,
                   u.status as user_status, u.account_type as user_account_type
              from agent_job j join app_user u on u.id = j.internal_user_id
             where j.id = ?
            """,
            (intent["job_id"],),
        )
        if (
            job is None
            or str(job["session_id"]) != str(intent["session_id"])
            or str(job["internal_user_id"]) != str(intent["actor_user_id"])
            or str(job["business_application_id"]) != str(intent["business_application_id"])
            or str(job["agent_publication_id"]) != str(intent["agent_publication_id"])
            or str(job["business_application_publication_id"])
            != str(intent["application_publication_id"])
            or str(job["source_connector_id"]) != str(intent["source_connector_id"])
            or str(job["user_status"]) != "enabled"
            or str(job["user_account_type"]) != "human"
        ):
            raise _authorization_denied(
                f"{error_prefix}_actor_revoked",
                f"当前用户或任务授权已失效，本次{operation_label}未执行",
                "ONES external action actor facts are no longer eligible",
            )
        verified = self.runtime.mcp_tool_snapshot_service.verify(str(intent["job_id"]))
        matches = [
            item
            for item in verified["snapshot"].get("tools") or []
            if isinstance(item, dict)
            and str(item.get("server_code") or "") == "ones-mcp"
            and str(item.get("tool_identifier") or "") == tool_identifier
            and str(item.get("schema_hash") or "") == definition.schema_hash
        ]
        if len(matches) != 1:
            raise _authorization_denied(
                f"{error_prefix}_job_snapshot_revoked",
                f"当前 Job 的 ONES {operation_label}授权已失效，本次{operation_label}未执行",
                "ONES external action Tool is absent from the Job snapshot",
            )
        self.runtime.business_authorization_service.require(
            user_id=str(intent["actor_user_id"]),
            application_id=str(intent["business_application_id"]),
            tool_identifier=tool_identifier,
            stage="ones_external_action_execute",
        )
        confirmation_identity = self.runtime.database.execute_one(
            """
            select id, union_id from user_external_identity
             where user_id = ? and provider = 'dingtalk' and status = 'enabled'
               and dingtalk_enterprise_id = ? and external_subject_id = ?
            """,
            (
                intent["actor_user_id"],
                intent["dingtalk_enterprise_id"],
                intent["target_external_subject_id"],
            ),
        )
        if confirmation_identity is None or str(
            confirmation_identity.get("union_id") or intent["target_external_subject_id"]
        ) != str(intent["target_union_id"]):
            raise _authorization_denied(
                f"{error_prefix}_confirmation_identity_revoked",
                f"确认该操作的钉钉身份已失效，本次{operation_label}未执行",
                "ONES external action confirmation identity is no longer eligible",
            )
        identity = self.runtime.database.execute_one(
            """
            select * from user_external_identity
             where id = ? and user_id = ? and provider = 'ones' and status = 'enabled'
            """,
            (intent["execution_external_identity_id"], intent["actor_user_id"]),
        )
        if identity is None:
            raise _authorization_denied(
                f"{error_prefix}_identity_revoked",
                f"原 ONES 身份已解绑或变更，本次{operation_label}未执行",
                "ONES external action identity is no longer eligible",
            )
        metadata = self._json_object(identity.get("metadata_json"))
        teams = metadata.get("team_uuids")
        if not isinstance(teams, list) or str(intent["execution_scope_id"]) not in teams:
            raise _authorization_denied(
                f"{error_prefix}_team_revoked",
                f"原确认的 ONES Team 已失效，本次{operation_label}未执行",
                "ONES external action Team scope is no longer eligible",
            )
        credentials = self.runtime.external_identity_credential_repository
        if credentials is None:
            raise _authorization_denied(
                f"{error_prefix}_credential_unavailable",
                f"ONES 身份凭据暂不可用，本次{operation_label}未执行",
                "ONES external action credential repository is unavailable",
            )
        credential_row = credentials.get_by_identity(str(identity["id"]))
        if credential_row is None or str(credential_row.get("status") or "") != "ACTIVE":
            raise _authorization_denied(
                f"{error_prefix}_reauthentication_required",
                f"ONES 身份需要本人重新验证，本次{operation_label}未执行",
                "ONES external action credential is no longer eligible",
            )
        credential = credentials.resolve_active(str(credential_row["id"]))
        if credential.provider != "ones":
            raise _authorization_denied(
                f"{error_prefix}_credential_provider_drift",
                f"ONES 身份凭据类型已变化，本次{operation_label}未执行",
                "ONES external action credential Provider drifted",
            )
        return identity, credential

    @staticmethod
    def _json_object(value: object) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        try:
            parsed = json.loads(str(value or "{}"))
        except (TypeError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
