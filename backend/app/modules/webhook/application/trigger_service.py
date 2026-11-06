from __future__ import annotations

import hmac
from typing import Any


from app.modules.agent_config.application.service import AgentConfigService
from app.modules.authorization_center.application.service import AuthorizationCenterService
from app.modules.audit.application.audit_service import AuditService
from app.modules.channel.infrastructure.connector_registry import ConnectorRegistry
from app.modules.identity.application.authorization import AuthorizationEvaluator
from app.modules.identity.infrastructure import IdentityRepository
from app.modules.platform_config.application.validation import validate_secret_ref
from app.modules.webhook.application.mapping import WebhookMapper
from app.modules.webhook.domain.models import (
    AuthenticationType,
    CODE_RE,
    SECRET_REF_PREFIXES,
    TriggerSchema,
    config_hash,
    ensure_no_secret_values,
    is_strong_bearer_token,
    normalize_config,
)
from app.modules.webhook.infrastructure import WebhookTriggerRepository
from app.shared.database import operation_unit_of_work
from app.shared.exceptions import AppError, NonRetryableExecutionError


class TriggerValidator:
    def __init__(
        self,
        *,
        repository: WebhookTriggerRepository,
        identity_repository: IdentityRepository,
        connector_registry: ConnectorRegistry,
        agent_config_service: AgentConfigService,
    ) -> None:
        self.repository = repository
        self.identity_repository = identity_repository
        self.connector_registry = connector_registry
        self.agent_config_service = agent_config_service

    def validate(  # noqa: C901
        self, *, definition: dict[str, Any], config: dict[str, Any]
    ) -> tuple[list[dict[str, str]], dict[str, Any]]:
        errors: list[dict[str, str]] = []
        if int(config.get("schema_version") or 0) != 2:
            errors.append({"field": "schema_version", "message": "请重新保存简化 Webhook 配置"})
        if str(config.get("adapter") or "") not in {item.value for item in TriggerSchema}:
            errors.append({"field": "adapter", "message": "不支持此适配器"})
        expected_adapter = {
            "grafana": TriggerSchema.GRAFANA_ALERTMANAGER_V1.value,
            "generic": TriggerSchema.GENERIC_JSON_V1.value,
        }.get(str(definition.get("trigger_type") or ""))
        if expected_adapter and str(config.get("adapter") or "") != expected_adapter:
            errors.append(
                {
                    "field": "adapter",
                    "message": "适配器与触发器类型不匹配",
                }
            )
        account = self.identity_repository.get_user(str(definition["service_account_id"]))
        if str(account.get("account_type")) != "service":
            errors.append({"field": "service_account", "message": "必须选择服务账号"})
        if str(account.get("status")) != "enabled":
            errors.append({"field": "service_account", "message": "服务账号已停用"})
        try:
            self.connector_registry.require_ingress(str(definition["connector_id"]))
        except Exception as exc:
            errors.append(
                {
                    "field": "connector_id",
                    "message": getattr(exc, "safe_message", "接入连接器不可用"),
                }
            )

        auth = config.get("authentication") or {}
        auth_type = str(auth.get("type") or "")
        if auth_type != AuthenticationType.BEARER_V1.value:
            errors.append(
                {
                    "field": "authentication.type",
                    "message": "外部 Webhook 只支持标准 Bearer Token",
                }
            )
        secret_ref = str(auth.get("secret_ref") or "")
        if not secret_ref.startswith(SECRET_REF_PREFIXES):
            if secret_ref.startswith(("vault:", "kms:")):
                message = "Provider 尚未实现"
            elif secret_ref.startswith("env:"):
                message = "env 凭据引用必须先导入凭据中心"
            else:
                message = "必须选择凭据中心 Secret"
            errors.append(
                {
                    "field": "authentication.secret_ref",
                    "message": message,
                }
            )
        else:
            try:
                secret = self.connector_registry.resolve_reference(secret_ref)
            except Exception:
                secret = ""
            if not secret:
                errors.append(
                    {
                        "field": "authentication.secret_ref",
                        "message": "无法解析凭据引用",
                    }
                )
            elif not is_strong_bearer_token(secret):
                errors.append(
                    {
                        "field": "authentication.secret_ref",
                        "message": "Bearer Token 必须至少包含 32 个高熵字符",
                    }
                )
            else:
                for binding in self.repository.active_authentication_bindings(
                    exclude_trigger_id=str(definition["id"])
                ):
                    existing_ref = str(binding["secret_ref"])
                    try:
                        existing = self.connector_registry.resolve_reference(existing_ref)
                    except Exception:
                        existing = ""
                    if existing_ref == secret_ref or (
                        existing
                        and hmac.compare_digest(
                            secret.encode("utf-8"),
                            existing.encode("utf-8"),
                        )
                    ):
                        errors.append(
                            {
                                "field": "authentication.secret_ref",
                                "message": "每个 Webhook binding 必须使用唯一 Bearer Token",
                            }
                        )
                        break

        if not config.get("role_ids"):
            errors.append({"field": "role_ids", "message": "请至少选择一个业务角色"})
        return errors, {"role_ids": config.get("role_ids", [])}


class WebhookTriggerService:
    def __init__(
        self,
        *,
        repository: WebhookTriggerRepository,
        identity_repository: IdentityRepository,
        authorization: AuthorizationEvaluator,
        audit_service: AuditService,
        validator: TriggerValidator,
        mapper: WebhookMapper,
        role_service: AuthorizationCenterService,
    ) -> None:
        self.repository = repository
        self.identity_repository = identity_repository
        self.authorization = authorization
        self.audit_service = audit_service
        self.validator = validator
        self.mapper = mapper
        self.role_service = role_service

    def list(self, *, actor_id: str) -> list[dict[str, Any]]:
        self._require(actor_id, "read")
        return self.repository.list_definitions()

    def get(self, *, actor_id: str, code: str) -> dict[str, Any]:
        self._require(actor_id, "read", code)
        definition = self.repository.get_definition(code)
        latest = self.repository.latest_revision(str(definition["id"]))
        current = None
        if definition.get("current_publication_id"):
            current = self.repository.get_publication(str(definition["current_publication_id"]))
        return {
            "definition": definition,
            "draft": latest,
            "current_publication": current,
            "publications": self.repository.list_publications(str(definition["id"])),
        }

    @operation_unit_of_work(lambda service: service.repository.database)
    def create(
        self,
        *,
        actor_id: str,
        code: str,
        name: str,
        trigger_type: str,
        connector_id: str,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require(actor_id, "edit")
        if self.repository.database.execute_one(
            "select id from webhook_trigger_definition where code = ?", (code,)
        ):
            raise NonRetryableExecutionError(
                "Webhook code already exists",
                safe_message="Webhook 编码已存在，请使用其他编码",
                error_code="validation_failed",
                field_errors=[{"field": "code", "message": "编码已存在"}],
            )
        if not CODE_RE.fullmatch(code):
            raise NonRetryableExecutionError(
                "Webhook Trigger code is invalid",
                safe_message="Webhook 触发器编码无效",
                error_code="validation_failed",
                field_errors=[{"field": "code", "message": "只能使用小写字母、数字和连字符"}],
            )
        self.validator.connector_registry.require_ingress(connector_id)
        with self.repository.database.unit_of_work():
            service = self.identity_repository.create_user(
                username=f"svc-webhook-{code}",
                display_name=f"Webhook: {name}",
                account_type="service",
            )
            definition = self.repository.create_definition(
                code=code,
                name=name.strip(),
                trigger_type=trigger_type,
                connector_id=connector_id,
                service_account_id=str(service["id"]),
                actor_id=actor_id,
            )
            draft = None
            if config is not None:
                normalized = self._normalize(config)
                draft = self.repository.save_draft(
                    trigger_id=str(definition["id"]),
                    expected_revision=0,
                    config=normalized,
                    config_hash=config_hash(normalized),
                    actor_id=actor_id,
                )
        self._audit(
            "webhook.trigger.created",
            actor_id=actor_id,
            code=code,
            after_hash=config_hash(draft["config"]) if draft else "",
            extra={"service_account_id": service["id"]},
        )
        return {"definition": definition, "draft": draft, "service_account": service}

    @operation_unit_of_work(lambda service: service.repository.database)
    def save_draft(
        self,
        *,
        actor_id: str,
        code: str,
        expected_revision: int,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        self._require(actor_id, "edit", code)
        definition = self.repository.get_definition(code)
        normalized = self._normalize(config)
        revision = self.repository.save_draft(
            trigger_id=str(definition["id"]),
            expected_revision=expected_revision,
            config=normalized,
            config_hash=config_hash(normalized),
            actor_id=actor_id,
        )
        self._audit(
            "webhook.trigger.draft_saved",
            actor_id=actor_id,
            code=code,
            after_hash=str(revision["config_hash"]),
            extra={"revision": revision["revision"]},
        )
        return revision

    @operation_unit_of_work(lambda service: service.repository.database)
    def validate_revision(self, *, actor_id: str, code: str, revision_id: str) -> dict[str, Any]:
        self._require(actor_id, "edit", code)
        definition = self.repository.get_definition(code)
        revision = self.repository.get_revision(revision_id)
        self._assert_revision_owner(definition, revision)
        errors, summary = self.validator.validate(definition=definition, config=revision["config"])
        try:
            self.role_service.validate_service_roles(
                actor_id=actor_id, role_ids=revision["config"].get("role_ids", [])
            )
        except AppError as exc:
            errors.append({"field": "role_ids", "message": exc.safe_message})
        result = self.repository.set_validation(revision_id, errors=errors, summary=summary)
        self._audit(
            "webhook.trigger.validated",
            actor_id=actor_id,
            code=code,
            after_hash=str(revision["config_hash"]),
            extra={"revision": revision["revision"], "valid": not errors},
        )
        return result

    def preview(
        self,
        *,
        actor_id: str,
        code: str,
        revision_id: str,
        sample_payload: dict[str, Any],
    ) -> dict[str, Any]:
        self._require(actor_id, "edit", code)
        definition = self.repository.get_definition(code)
        revision = self.repository.get_revision(revision_id)
        self._assert_revision_owner(definition, revision)
        errors, summary = self.validator.validate(definition=definition, config=revision["config"])
        try:
            self.role_service.validate_service_roles(
                actor_id=actor_id, role_ids=revision["config"].get("role_ids", [])
            )
        except AppError as exc:
            errors.append({"field": "role_ids", "message": exc.safe_message})
        if errors:
            raise NonRetryableExecutionError(
                "Webhook Trigger validation failed",
                safe_message="Webhook 触发器配置无效",
                error_code="validation_failed",
                field_errors=errors,
            )
        return {
            **self.mapper.preview(config=revision["config"], payload=sample_payload),
            "authorization": summary,
            "side_effects": False,
        }

    @operation_unit_of_work(lambda service: service.repository.database)
    def publish(self, *, actor_id: str, code: str, revision_id: str) -> dict[str, Any]:
        self._require(actor_id, "publish", code)
        definition = self.repository.get_definition(code)
        revision = self.repository.get_revision(revision_id)
        self._assert_revision_owner(definition, revision)
        errors, summary = self.validator.validate(definition=definition, config=revision["config"])
        try:
            self.role_service.validate_service_roles(
                actor_id=actor_id, role_ids=revision["config"].get("role_ids", [])
            )
        except AppError as exc:
            errors.append({"field": "role_ids", "message": exc.safe_message})
        if errors:
            self.repository.set_validation(revision_id, errors=errors, summary=summary)
            raise NonRetryableExecutionError(
                "Webhook Trigger validation failed",
                safe_message="Webhook 触发器配置无效",
                error_code="validation_failed",
                field_errors=errors,
            )
        self.role_service.replace_service_roles(
            actor_id=actor_id,
            user_id=str(definition["service_account_id"]),
            role_ids=revision["config"]["role_ids"],
        )
        snapshot = {
            **revision["config"],
            "service_account_id": definition["service_account_id"],
            "source_connector_id": definition["connector_id"],
        }
        with self.repository.database.unit_of_work():
            self.repository.set_validation(revision_id, errors=[], summary=summary)
            publication = self.repository.create_publication(
                trigger_id=str(definition["id"]),
                revision_id=revision_id,
                revision=int(revision["revision"]),
                snapshot=snapshot,
                config_hash=config_hash(revision["config"]),
                actor_id=actor_id,
            )
        self._audit(
            "webhook.trigger.published",
            actor_id=actor_id,
            code=code,
            after_hash=str(publication["config_hash"]),
            extra={"publication_id": publication["id"], "revision": publication["revision"]},
        )
        return publication

    @operation_unit_of_work(lambda service: service.repository.database)
    def update_definition(
        self,
        *,
        actor_id: str,
        code: str,
        expected_revision: int,
        name: str,
        connector_id: str,
        status: str,
    ) -> dict[str, Any]:
        self._require(actor_id, "edit", code)
        before = self.repository.get_definition(code)
        if status == "enabled" and not before.get("current_publication_id"):
            raise NonRetryableExecutionError(
                "Webhook must be published before enabling",
                safe_message="请先完成配置校验和发布，再启用 Webhook",
                error_code="webhook_not_published",
            )
        # An unavailable ingress must never prevent an administrator from stopping it.
        if status == "enabled" or connector_id != str(before["connector_id"]):
            self.validator.connector_registry.require_ingress(connector_id)
        updated = self.repository.update_definition(
            code=code,
            expected_revision=expected_revision,
            name=name.strip(),
            connector_id=connector_id,
            status=status,
        )
        self._audit(
            "webhook.trigger.updated",
            actor_id=actor_id,
            code=code,
            before_hash=config_hash(
                {
                    "name": before["name"],
                    "connector_id": before["connector_id"],
                    "status": before["status"],
                }
            ),
            after_hash=config_hash(
                {
                    "name": updated["name"],
                    "connector_id": updated["connector_id"],
                    "status": updated["status"],
                }
            ),
        )
        return updated

    @operation_unit_of_work(lambda service: service.repository.database)
    def rollback(
        self,
        *,
        actor_id: str,
        code: str,
        publication_id: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        self._require(actor_id, "publish", code)
        before = self.repository.get_definition(code)
        selected = self.repository.get_publication(publication_id)
        config = {
            k: v
            for k, v in selected["snapshot"].items()
            if k not in {"service_account_id", "source_connector_id"}
        }
        self._normalize(config)
        errors, _ = self.validator.validate(definition=before, config=config)
        if errors or str(selected["trigger_id"]) != str(before["id"]):
            raise NonRetryableExecutionError(
                "Invalid rollback",
                safe_message="该版本无法回滚",
                error_code="validation_failed",
                field_errors=errors,
            )
        self.role_service.replace_service_roles(
            actor_id=actor_id,
            user_id=str(before["service_account_id"]),
            role_ids=config["role_ids"],
        )
        publication = self.repository.set_current_publication(
            code=code,
            publication_id=publication_id,
            expected_revision=expected_revision,
        )
        self._audit(
            "webhook.trigger.rolled_back",
            actor_id=actor_id,
            code=code,
            before_hash=str(before.get("current_publication_id") or ""),
            after_hash=publication_id,
        )
        return publication

    @operation_unit_of_work(lambda service: service.repository.database)
    def rotate_public_id(
        self, *, actor_id: str, code: str, expected_revision: int, confirm: bool
    ) -> dict[str, Any]:
        self._require(actor_id, "rotate", code)
        if not confirm:
            raise NonRetryableExecutionError(
                "Public ID rotation requires confirmation",
                safe_message="请确认轮换公开 ID",
                error_code="confirmation_required",
            )
        before = self.repository.get_definition(code)
        updated = self.repository.rotate_public_id(code=code, expected_revision=expected_revision)
        self._audit(
            "webhook.trigger.public_id_rotated",
            actor_id=actor_id,
            code=code,
            before_hash=config_hash({"public_id": before["public_id"]}),
            after_hash=config_hash({"public_id": updated["public_id"]}),
        )
        return updated

    @operation_unit_of_work(lambda service: service.repository.database)
    def set_service_account_enabled(
        self,
        *,
        actor_id: str,
        code: str,
        expected_revision: int,
        enabled: bool,
    ) -> dict[str, Any]:
        self._require(actor_id, "manage_service_account", code)
        updated = self.repository.set_service_account_status(
            code=code, expected_revision=expected_revision, enabled=enabled
        )
        self._audit(
            "webhook.trigger.service_account_status_changed",
            actor_id=actor_id,
            code=code,
            after_hash=config_hash({"enabled": enabled}),
            extra={"service_account_id": updated["service_account_id"]},
        )
        return updated

    def _normalize(self, config: dict[str, Any]) -> dict[str, Any]:
        ensure_no_secret_values(config)
        normalized = normalize_config(config)
        secret_ref = str((normalized.get("authentication") or {}).get("secret_ref") or "")
        try:
            validate_secret_ref(secret_ref)
        except NonRetryableExecutionError as exc:
            raise NonRetryableExecutionError(
                "Invalid Webhook secret reference",
                safe_message=exc.safe_message,
                error_code="validation_failed",
                field_errors=[
                    {
                        "field": "authentication.secret_ref",
                        "message": exc.safe_message,
                    }
                ],
            ) from None
        return normalized

    def _assert_revision_owner(self, definition: dict[str, Any], revision: dict[str, Any]) -> None:
        if str(revision["trigger_id"]) != str(definition["id"]):
            raise NonRetryableExecutionError(
                "Revision belongs to another Trigger",
                safe_message="修订版本不属于此触发器",
            )

    def _require(self, actor_id: str, action: str, code: str = "*") -> None:
        self.authorization.require(
            user_id=actor_id,
            resource_type="webhook_trigger",
            resource_code=code,
            action=action,
        )

    def _audit(
        self,
        event_type: str,
        *,
        actor_id: str,
        code: str,
        before_hash: str = "",
        after_hash: str = "",
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.audit_service.record(
            event_type,
            status="SUCCEEDED",
            summary=event_type.replace(".", " "),
            actor_id=actor_id,
            payload={
                "trigger_code": code,
                "before_hash": before_hash,
                "after_hash": after_hash,
                **(extra or {}),
            },
        )
