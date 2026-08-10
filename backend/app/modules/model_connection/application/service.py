from __future__ import annotations

import hashlib
import ipaddress
import json
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any, NoReturn, Protocol
from urllib.parse import urlsplit, urlunsplit

from app.modules.audit.application.audit_service import AuditService
from app.modules.identity.application.authorization import AuthorizationEvaluator
from app.modules.model_connection.domain import (
    ANTHROPIC_COMPATIBLE_PROTOCOL,
    DEFAULT_MODEL_CONNECTION_CODE,
    ModelConnectionConfig,
    ModelRuntimeBinding,
)
from app.modules.model_connection.infrastructure import ModelConnectionRepository
from app.modules.platform_config.application.secrets import SecretProviderPort
from app.modules.platform_config.infrastructure.repository import PlatformConfigRepository
from app.shared.database import (
    assert_external_io_allowed,
    operation_unit_of_work,
)
from app.shared.exceptions import NonRetryableExecutionError, NotFound


DEFAULT_AGENT_CODE = "default-diagnostic-agent"
DEFAULT_ALLOWED_HOSTS = frozenset({"api.deepseek.com"})
EFFORT_LEVELS = frozenset({"low", "medium", "high", "max"})
MAX_DISCOVERY_BYTES = 256 * 1024
MAX_DISCOVERED_MODELS = 200
MAX_MODEL_ID_LENGTH = 200
STABLE_PROBE_ERROR_CODES = frozenset(
    {
        "deepseek_url_invalid",
        "deepseek_credential_rejected",
        "deepseek_model_discovery_failed",
        "deepseek_model_list_empty",
        "deepseek_model_unavailable",
        "model_connection_test_failed",
        "model_connection_test_timeout",
        "model_connection_test_unavailable",
        "model_connection_credential_unavailable",
        "model_connection_rotation_required",
        "revision_conflict",
        "credential_ownership_conflict",
        "validation_failed",
    }
)
CONFIG_FIELDS = frozenset(
    {
        "schema_version",
        "protocol",
        "base_url",
        "model",
        "default_opus_model",
        "default_sonnet_model",
        "default_haiku_model",
        "subagent_model",
        "effort_level",
    }
)


class ModelConnectionTester(Protocol):
    def __call__(
        self,
        binding: ModelRuntimeBinding,
        api_key: str,
        timeout_seconds: int,
    ) -> dict[str, Any]: ...


class RuntimeModelProbe(Protocol):
    def probe(
        self,
        *,
        revision_id: str,
        config_hash: str,
        timeout_seconds: int,
    ) -> dict[str, Any]: ...


class ModelDiscoverer(Protocol):
    def __call__(
        self,
        models_url: str,
        api_key: str,
        timeout_seconds: int,
    ) -> list[dict[str, str]]: ...


class UnavailableModelSecretProvider:
    def resolve(self, ref: str) -> str:
        del ref
        self._raise()

    def create_secret(
        self,
        *,
        code: str,
        value: str,
        purpose: str = "",
        actor_id: str = "",
        metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        del code, value, purpose, actor_id, metadata
        self._raise()

    def rotate_secret(self, *, code: str, value: str, actor_id: str = "") -> dict[str, object]:
        del code, value, actor_id
        self._raise()

    def disable_secret(self, *, code: str, actor_id: str = "") -> dict[str, object]:
        del code, actor_id
        self._raise()

    @staticmethod
    def _raise() -> NoReturn:
        raise NonRetryableExecutionError(
            "Master Key file is required for model credentials",
            safe_message="尚未配置模型凭据加密",
            error_code="model_credential_encryption_unavailable",
        )


class ModelConnectionService:
    def __init__(
        self,
        repository: ModelConnectionRepository,
        platform_repository: PlatformConfigRepository,
        secret_provider: SecretProviderPort,
        authorization: AuthorizationEvaluator,
        audit_service: AuditService,
        *,
        allowed_hosts: set[str] | frozenset[str] | None = None,
        dns_resolver: Callable[..., list[tuple[Any, ...]]] | None = None,
        tester: ModelConnectionTester | None = None,
        runtime_probe: RuntimeModelProbe | None = None,
        model_discoverer: ModelDiscoverer | None = None,
        redirect_checker: Callable[[str, int], None] | None = None,
    ) -> None:
        self.repository = repository
        self.platform_repository = platform_repository
        self.secret_provider = secret_provider
        self.authorization = authorization
        self.audit_service = audit_service
        self.allowed_hosts = frozenset(
            str(item).strip().lower()
            for item in (allowed_hosts or DEFAULT_ALLOWED_HOSTS)
            if str(item).strip()
        )
        self.dns_resolver = dns_resolver or socket.getaddrinfo
        self.tester = tester
        self.runtime_probe = runtime_probe
        self.model_discoverer = model_discoverer or _fetch_deepseek_models
        self.redirect_checker = redirect_checker or _assert_provider_does_not_redirect

    def list_connections(self) -> list[dict[str, Any]]:
        return [self._public_connection(item) for item in self.repository.list_connections()]

    def get(self, code: str) -> dict[str, Any]:
        connection = self.repository.get_connection(code)
        revisions = self.repository.list_revisions(str(connection["id"]))
        current = revisions[0] if revisions else None
        if connection.get("current_revision_id"):
            current = self.repository.get_revision(str(connection["current_revision_id"]))
        return {
            **self._public_connection(connection),
            "current_revision": self._public_revision(current) if current else None,
            "revisions": [self._public_revision(item) for item in revisions],
        }

    def discover_models(
        self,
        *,
        actor_id: str,
        code: str,
        base_url: str,
        credential_source: str,
        api_key: str = "",
        timeout_seconds: int = 10,
    ) -> dict[str, Any]:
        self._require_agent_editor(actor_id)
        self._require_secret_admin(actor_id)
        self.repository.get_connection(code)
        normalized_base_url = self.normalize_base_url(base_url, validate_dns=True)
        credential = self._resolve_probe_credential(
            code=code,
            credential_source=credential_source,
            api_key=api_key,
        )
        started = time.monotonic()
        try:
            models = self._discover_model_options(
                normalized_base_url,
                credential,
                timeout_seconds,
            )
        except Exception as exc:
            self._record_probe_audit(
                actor_id=actor_id,
                code=code,
                action="discover",
                status="FAILED",
                provider_host=urlsplit(normalized_base_url).hostname or "",
                duration_ms=int((time.monotonic() - started) * 1000),
                error_code=_stable_probe_error_code(exc),
            )
            raise _safe_probe_error(exc) from exc
        result: dict[str, Any] = {
            "provider_host": urlsplit(normalized_base_url).hostname or "",
            "normalized_base_url": normalized_base_url,
            "models": models,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "credential_source": credential_source,
        }
        self._record_probe_audit(
            actor_id=actor_id,
            code=code,
            action="discover",
            status="SUCCEEDED",
            provider_host=str(result["provider_host"]),
            duration_ms=int(result["duration_ms"]),
        )
        return result

    def test_draft(
        self,
        *,
        actor_id: str,
        code: str,
        credential_source: str,
        config: dict[str, Any],
        api_key: str = "",
        timeout_seconds: int = 15,
    ) -> dict[str, Any]:
        self._require_agent_editor(actor_id)
        self._require_secret_admin(actor_id)
        connection = self.repository.get_connection(code)
        normalized = self.normalize_config(config, validate_dns=True)
        credential = self._resolve_probe_credential(
            code=code,
            credential_source=credential_source,
            api_key=api_key,
        )
        started = time.monotonic()
        binding = self._temporary_binding(connection, normalized)
        try:
            models = self._discover_model_options(
                str(normalized["base_url"]),
                credential,
                timeout_seconds,
            )
            self._require_discovered_models(normalized, models)
            self._test_temporary_binding(binding, credential, timeout_seconds)
        except Exception as exc:
            self._record_probe_audit(
                actor_id=actor_id,
                code=code,
                action="test-draft",
                status="FAILED",
                provider_host=binding.provider_host,
                model=binding.model,
                duration_ms=int((time.monotonic() - started) * 1000),
                error_code=_stable_probe_error_code(exc),
            )
            raise _safe_probe_error(exc) from exc
        result: dict[str, Any] = {
            "success": True,
            "provider_host": binding.provider_host,
            "model": binding.model,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "runtime": "claude_agent_sdk",
            "detail": "连接成功",
        }
        self._record_probe_audit(
            actor_id=actor_id,
            code=code,
            action="test-draft",
            status="SUCCEEDED",
            provider_host=binding.provider_host,
            model=binding.model,
            duration_ms=int(result["duration_ms"]),
        )
        return result

    def configure(
        self,
        *,
        actor_id: str,
        code: str,
        expected_revision: int,
        credential_source: str,
        config: dict[str, Any],
        api_key: str = "",
        timeout_seconds: int = 15,
    ) -> dict[str, Any]:
        self._require_agent_editor(actor_id)
        self._require_secret_admin(actor_id)
        connection = self._require_expected_revision(code, expected_revision)
        normalized = self.normalize_config(config, validate_dns=True)
        credential = self._resolve_probe_credential(
            code=code,
            credential_source=credential_source,
            api_key=api_key,
        )
        started = time.monotonic()
        binding = self._temporary_binding(connection, normalized)
        try:
            models = self._discover_model_options(
                str(normalized["base_url"]),
                credential,
                timeout_seconds,
            )
            self._require_discovered_models(normalized, models)
            self._test_temporary_binding(binding, credential, timeout_seconds)
        except Exception as exc:
            self._record_probe_audit(
                actor_id=actor_id,
                code=code,
                action="configure",
                status="FAILED",
                provider_host=binding.provider_host,
                model=binding.model,
                duration_ms=int((time.monotonic() - started) * 1000),
                error_code=_stable_probe_error_code(exc),
            )
            raise _safe_probe_error(exc) from exc

        audit_attempted = False
        try:
            self._require_expected_revision(code, expected_revision)
            with self.repository.database.unit_of_work():
                connection = self._require_expected_revision(code, expected_revision)
                secret_id = self._configured_secret_id(
                    actor_id=actor_id,
                    connection=connection,
                    credential_source=credential_source,
                    api_key=api_key,
                )
                revision = self.repository.append_revision(
                    connection_id=str(connection["id"]),
                    expected_revision=expected_revision,
                    config=normalized,
                    config_hash=_hash(normalized),
                    api_key_secret_id=secret_id,
                    status="ready",
                    actor_id=actor_id,
                )
                audit_attempted = True
                self.audit_service.record(
                    "model.connection.configure_succeeded",
                    status="SUCCEEDED",
                    summary="Model connection configured",
                    actor_id=actor_id,
                    payload={
                        "connection_code": code,
                        "provider_host": binding.provider_host,
                        "model": binding.model,
                        "duration_ms": int((time.monotonic() - started) * 1000),
                        "result": "ready",
                        "credential_source": credential_source,
                        "revision": int(revision["revision"]),
                    },
                )
                public = self._public_revision(revision)
        except Exception as exc:
            if not audit_attempted:
                self._record_probe_audit(
                    actor_id=actor_id,
                    code=code,
                    action="configure",
                    status="FAILED",
                    provider_host=binding.provider_host,
                    model=binding.model,
                    duration_ms=int((time.monotonic() - started) * 1000),
                    error_code=_stable_probe_error_code(exc),
                )
            raise
        return public

    def save_revision(
        self,
        *,
        actor_id: str,
        code: str,
        expected_revision: int,
        config: dict[str, Any],
        api_key: str = "",
    ) -> dict[str, Any]:
        self._require_agent_editor(actor_id)
        normalized = self.normalize_config(config, validate_dns=True)
        return self._save_normalized_revision(
            actor_id=actor_id,
            code=code,
            expected_revision=expected_revision,
            normalized=normalized,
            api_key=api_key,
        )

    @operation_unit_of_work(lambda service: service.repository.database)
    def _save_normalized_revision(
        self,
        *,
        actor_id: str,
        code: str,
        expected_revision: int,
        normalized: dict[str, str | int],
        api_key: str,
    ) -> dict[str, Any]:
        connection = self.repository.get_connection(code)
        current_revision = (
            self.repository.get_revision(str(connection["current_revision_id"]))
            if connection.get("current_revision_id")
            else None
        )
        secret_id = str(current_revision.get("api_key_secret_id") or "") if current_revision else ""
        if api_key:
            self._require_secret_admin(actor_id)
            if secret_id:
                secret = self.platform_repository.get_platform_secret(secret_id)
                self.secret_provider.rotate_secret(
                    code=str(secret["code"]),
                    value=api_key,
                    actor_id=actor_id,
                )
            else:
                created = self.secret_provider.create_secret(
                    code=f"model-{code}-api-key",
                    value=api_key,
                    purpose=f"Anthropic-compatible credential for {code}",
                    actor_id=actor_id,
                    metadata={"kind": "model_connection"},
                )
                secret_id = str(created["id"])
        current_status = str(current_revision.get("status") or "") if current_revision else ""
        status = (
            "ready"
            if self._secret_ready(secret_id) and (bool(api_key) or current_status == "ready")
            else "rotation_required"
        )
        with self.repository.database.unit_of_work():
            revision = self.repository.append_revision(
                connection_id=str(connection["id"]),
                expected_revision=expected_revision,
                config=normalized,
                config_hash=_hash(normalized),
                api_key_secret_id=secret_id or None,
                status=status,
                actor_id=actor_id,
            )
        public = self._public_revision(revision)
        self.audit_service.record(
            "model.connection.revision_saved",
            status="SUCCEEDED",
            summary="Model connection revision saved",
            actor_id=actor_id,
            payload={
                "connection_code": code,
                "connection_revision_id": public["id"],
                "revision": public["revision"],
                "config_hash": public["config_hash"],
                "provider_host": public["provider_host"],
                "model": public["config"]["model"],
                "credential_updated": bool(api_key),
                "credential_configured": public["credential"]["configured"],
            },
        )
        return public

    @operation_unit_of_work(lambda service: service.repository.database)
    def rotate_credential(
        self,
        *,
        actor_id: str,
        code: str,
        expected_revision: int,
        api_key: str,
    ) -> dict[str, Any]:
        self._require_agent_editor(actor_id)
        self._require_secret_admin(actor_id)
        if not str(api_key or ""):
            raise _validation_error("api_key", "必须填写 API Key")
        connection = self.repository.get_connection(code)
        if int(connection["revision"]) != expected_revision:
            raise NonRetryableExecutionError(
                "Model connection revision conflict",
                safe_message="模型连接已发生变化，请刷新后重试",
                error_code="revision_conflict",
                diagnostics={"current_revision": int(connection["revision"])},
            )
        revision_id = str(connection.get("current_revision_id") or "")
        if not revision_id:
            raise NonRetryableExecutionError(
                "Model connection has no configuration revision",
                safe_message="设置凭据前请先保存模型连接配置",
                error_code="model_connection_revision_required",
            )
        current = self.repository.get_revision(revision_id)
        secret_id = str(current.get("api_key_secret_id") or "")
        with self.repository.database.unit_of_work():
            if secret_id:
                secret = self.platform_repository.get_platform_secret(secret_id)
                self.secret_provider.rotate_secret(
                    code=str(secret["code"]),
                    value=api_key,
                    actor_id=actor_id,
                )
            else:
                created = self.secret_provider.create_secret(
                    code=f"model-{code}-api-key",
                    value=api_key,
                    purpose=f"Anthropic-compatible credential for {code}",
                    actor_id=actor_id,
                    metadata={"kind": "model_connection"},
                )
                secret_id = str(created["id"])
            revision = self.repository.append_revision(
                connection_id=str(connection["id"]),
                expected_revision=expected_revision,
                config=dict(current["config"]),
                config_hash=str(current["config_hash"]),
                api_key_secret_id=secret_id,
                status="ready",
                actor_id=actor_id,
            )
        public = self._public_revision(revision)
        self.audit_service.record(
            "model.connection.credential_rotated",
            status="SUCCEEDED",
            summary="Model connection credential rotated",
            actor_id=actor_id,
            payload={
                "connection_code": code,
                "connection_revision_id": public["id"],
                "revision": public["revision"],
                "config_hash": public["config_hash"],
                "provider_host": public["provider_host"],
                "model": public["config"]["model"],
                "credential_version": public["credential"]["version"],
            },
        )
        return public

    @operation_unit_of_work(lambda service: service.repository.database)
    def set_enabled(
        self,
        *,
        actor_id: str,
        code: str,
        expected_revision: int,
        enabled: bool,
    ) -> dict[str, Any]:
        self._require_agent_editor(actor_id)
        connection = self.repository.get_connection(code)
        if enabled:
            revision_id = str(connection.get("current_revision_id") or "")
            if not revision_id:
                raise NonRetryableExecutionError(
                    "Model connection has no revision",
                    safe_message="模型连接没有已保存的版本",
                    error_code="model_connection_revision_required",
                )
            self.runtime_binding(revision_id, require_connection_enabled=False)
        updated = self.repository.set_connection_status(
            code=code,
            expected_revision=expected_revision,
            status="ready" if enabled else "disabled",
        )
        return self._public_connection(updated)

    def test_saved_revision(
        self,
        *,
        actor_id: str,
        revision_id: str,
        timeout_seconds: int = 15,
    ) -> dict[str, Any]:
        self._require_agent_editor(actor_id)
        self._require_secret_admin(actor_id)
        revision = self.repository.get_revision(revision_id)
        binding: ModelRuntimeBinding | None = None
        try:
            binding = self.runtime_binding(revision_id)
            self.validate_base_url(binding.base_url, validate_dns=True)
            self.redirect_checker(binding.base_url, max(3, min(timeout_seconds, 10)))
            if self.runtime_probe is None:
                raise NonRetryableExecutionError(
                    "TypeScript Runtime model probe is unavailable",
                    safe_message="模型连接测试运行时不可用",
                    error_code="model_connection_test_unavailable",
                )
            outcome = self.runtime_probe.probe(
                revision_id=revision_id,
                config_hash=binding.config_hash,
                timeout_seconds=max(3, min(timeout_seconds, 20)),
            )
            if str(outcome.get("connection_revision_id") or "") != revision_id:
                raise NonRetryableExecutionError(
                    "TypeScript Runtime model probe revision mismatch",
                    safe_message="模型连接测试响应无效",
                    error_code="model_connection_test_invalid_response",
                )
            if not bool(outcome.get("success")):
                failure = outcome.get("failure")
                safe_failure = failure if isinstance(failure, dict) else {}
                raise NonRetryableExecutionError(
                    "TypeScript Runtime model probe failed",
                    safe_message=str(safe_failure.get("safe_message") or "模型连接测试失败"),
                    error_code=str(
                        safe_failure.get("code") or "model_connection_test_failed"
                    ),
                )
        except Exception as exc:
            safe_message = getattr(exc, "safe_message", "模型连接测试失败")
            error_code = getattr(exc, "error_code", "model_connection_test_failed")
            config = dict(revision.get("config") or {})
            self.audit_service.record(
                "model.connection.test_failed",
                status="FAILED",
                summary="Model connection test failed",
                actor_id=actor_id,
                payload={
                    "connection_code": revision["connection_code"],
                    "connection_revision_id": revision_id,
                    "provider_host": (
                        binding.provider_host
                        if binding is not None
                        else (urlsplit(str(config.get("base_url") or "")).hostname or "")
                    ),
                    "model": (
                        binding.model if binding is not None else str(config.get("model") or "")
                    ),
                    "error_code": error_code,
                },
            )
            raise NonRetryableExecutionError(
                "Saved model connection test failed",
                safe_message=str(safe_message),
                error_code=str(error_code),
            ) from exc
        assert binding is not None
        result = {
            "success": True,
            "connection_revision_id": revision_id,
            "provider_host": str(outcome.get("provider_host") or binding.provider_host),
            "model": str(outcome.get("model") or binding.model),
            "duration_ms": int(outcome.get("duration_ms") or 0),
            "runtime": "typescript-v1",
            "runtime_version": str(outcome.get("runtime_version") or ""),
            "sdk_version": str(outcome.get("sdk_version") or ""),
        }
        self.audit_service.record(
            "model.connection.test_succeeded",
            status="SUCCEEDED",
            summary="Model connection test succeeded",
            actor_id=actor_id,
            payload=result,
        )
        return result

    def public_revision(self, revision_id: str) -> dict[str, Any]:
        revision = self.repository.get_revision(revision_id)
        if _hash(dict(revision["config"])) != str(revision["config_hash"]):
            raise NonRetryableExecutionError(
                "Model connection revision hash mismatch",
                safe_message="模型连接完整性校验失败",
                error_code="model_connection_integrity_failed",
            )
        return self._public_revision(revision)

    def runtime_binding(
        self,
        revision_id: str,
        *,
        require_connection_enabled: bool = True,
    ) -> ModelRuntimeBinding:
        revision = self.repository.get_revision(revision_id)
        if (
            require_connection_enabled
            and str(revision.get("connection_status") or "") == "disabled"
        ):
            raise NonRetryableExecutionError(
                "Model connection is disabled",
                safe_message="模型连接已停用",
                error_code="model_connection_disabled",
            )
        config = dict(revision["config"])
        if _hash(config) != str(revision["config_hash"]):
            raise NonRetryableExecutionError(
                "Model connection revision hash mismatch",
                safe_message="模型连接完整性校验失败",
                error_code="model_connection_integrity_failed",
            )
        normalized = self.normalize_config(config, validate_dns=True)
        if normalized != config:
            raise NonRetryableExecutionError(
                "Model connection revision is not canonical",
                safe_message="模型连接完整性校验失败",
                error_code="model_connection_integrity_failed",
            )
        if revision["status"] != "ready":
            raise NonRetryableExecutionError(
                "Model connection revision is not ready",
                safe_message="使用模型连接前必须先轮换凭据",
                error_code="model_connection_rotation_required",
            )
        secret_id = str(revision.get("api_key_secret_id") or "")
        if not self._secret_ready(secret_id):
            raise NonRetryableExecutionError(
                "Model connection credential is missing or disabled",
                safe_message="模型连接凭据缺失或已停用",
                error_code="model_connection_credential_unavailable",
            )
        secret = self.platform_repository.get_platform_secret(secret_id)
        return ModelRuntimeBinding(
            protocol=str(config["protocol"]),
            base_url=str(config["base_url"]),
            model=str(config["model"]),
            default_opus_model=str(config["default_opus_model"]),
            default_sonnet_model=str(config["default_sonnet_model"]),
            default_haiku_model=str(config["default_haiku_model"]),
            subagent_model=str(config["subagent_model"]),
            effort_level=str(config["effort_level"]),
            connection_id=str(revision["connection_id"]),
            connection_code=str(revision["connection_code"]),
            connection_revision_id=str(revision["id"]),
            connection_revision=int(revision["revision"]),
            config_hash=str(revision["config_hash"]),
            secret_ref=str(secret["ref"]),
        )

    def resolve_api_key(self, binding: ModelRuntimeBinding) -> str:
        if not binding.secret_ref:
            raise NonRetryableExecutionError(
                "Model runtime credential reference is missing",
                safe_message="尚未配置模型运行凭据",
                error_code="model_connection_credential_unavailable",
            )
        return self.secret_provider.resolve(binding.secret_ref)

    @operation_unit_of_work(lambda service: service.repository.database)
    def ensure_default_connection(
        self,
        *,
        config: dict[str, Any],
        actor_id: str = "system-bootstrap",
    ) -> dict[str, Any]:
        try:
            return self.get(DEFAULT_MODEL_CONNECTION_CODE)
        except NotFound:
            pass
        normalized = self.normalize_config(config, validate_dns=False)
        secret_id = self._runtime_anthropic_secret_id()
        with self.repository.database.unit_of_work():
            connection = self.repository.create_connection(
                code=DEFAULT_MODEL_CONNECTION_CODE,
                name="默认 DeepSeek Anthropic 连接",
                protocol=ANTHROPIC_COMPATIBLE_PROTOCOL,
                actor_id=actor_id,
            )
            if connection.get("current_revision_id"):
                return self.get(DEFAULT_MODEL_CONNECTION_CODE)
            self.repository.initialize_revision_if_missing(
                connection_id=str(connection["id"]),
                config=normalized,
                config_hash=_hash(normalized),
                api_key_secret_id=secret_id or None,
                actor_id=actor_id,
            )
        return self.get(DEFAULT_MODEL_CONNECTION_CODE)

    def normalize_config(
        self, config: dict[str, Any], *, validate_dns: bool
    ) -> dict[str, str | int]:
        unknown = sorted(set(config) - CONFIG_FIELDS)
        if unknown:
            raise _validation_error(unknown[0], "此协议不允许配置该字段")
        if "schema_version" in config:
            try:
                schema_version = int(config["schema_version"])
            except (TypeError, ValueError) as exc:
                raise _validation_error("schema_version", "结构版本必须为 1") from exc
            if schema_version != 1:
                raise _validation_error("schema_version", "仅支持结构版本 1")
        protocol = str(config.get("protocol") or ANTHROPIC_COMPATIBLE_PROTOCOL).strip()
        if protocol != ANTHROPIC_COMPATIBLE_PROTOCOL:
            raise _validation_error("protocol", "仅支持 anthropic_compatible")
        base_url = self.normalize_base_url(
            str(config.get("base_url") or ""),
            validate_dns=validate_dns,
        )
        model = _model_value(config.get("model"), "model")
        default_opus = _model_value(config.get("default_opus_model") or model, "default_opus_model")
        default_sonnet = _model_value(
            config.get("default_sonnet_model") or model, "default_sonnet_model"
        )
        default_haiku = _model_value(
            config.get("default_haiku_model") or model, "default_haiku_model"
        )
        subagent = _model_value(config.get("subagent_model") or model, "subagent_model")
        effort = str(config.get("effort_level") or "max").strip().lower()
        if effort not in EFFORT_LEVELS:
            raise _validation_error(
                "effort_level",
                f"必须是以下值之一：{', '.join(sorted(EFFORT_LEVELS))}",
            )
        return ModelConnectionConfig(
            protocol=protocol,
            base_url=base_url,
            model=model,
            default_opus_model=default_opus,
            default_sonnet_model=default_sonnet,
            default_haiku_model=default_haiku,
            subagent_model=subagent,
            effort_level=effort,
        ).as_dict()

    def normalize_base_url(self, value: str, *, validate_dns: bool) -> str:
        normalized = str(value or "").strip().rstrip("/")
        self.validate_base_url(normalized, validate_dns=validate_dns)
        return normalized

    def validate_base_url(self, value: str, *, validate_dns: bool) -> None:
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError as exc:
            raise _deepseek_url_error("模型提供方地址无效") from exc
        host = (parsed.hostname or "").lower()
        if (
            parsed.scheme != "https"
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or parsed.query
        ):
            raise _deepseek_url_error("必须是不包含凭据、查询参数或片段的 HTTPS 地址")
        if host not in self.allowed_hosts:
            raise _deepseek_url_error("仅允许 DeepSeek 官方模型提供方主机")
        if port not in {None, 443}:
            raise _deepseek_url_error("模型提供方地址只允许使用 443 端口")
        path = parsed.path or ""
        path_parts = path.split("/")
        if (
            not path.endswith("/anthropic")
            or "//" in path
            or any(part in {".", ".."} for part in path_parts)
        ):
            raise _deepseek_url_error("DeepSeek Base URL 必须以 /anthropic 结尾")
        if not validate_dns:
            return
        assert_external_io_allowed("model.dns")
        try:
            answers = self.dns_resolver(host, port or 443, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise _deepseek_url_error("无法解析模型提供方主机") from exc
        addresses = {str(item[4][0]) for item in answers if item and len(item) >= 5}
        if not addresses:
            raise _deepseek_url_error("无法解析模型提供方主机")
        for address in addresses:
            try:
                ip = ipaddress.ip_address(address)
            except ValueError as exc:
                raise _deepseek_url_error("模型提供方 DNS 结果无效") from exc
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_unspecified
                or ip.is_multicast
            ):
                raise _deepseek_url_error("模型提供方主机解析到了不允许的网络")

    def _discover_model_options(
        self,
        base_url: str,
        api_key: str,
        timeout_seconds: int,
    ) -> list[dict[str, str]]:
        models_url = _deepseek_models_url(base_url)
        try:
            raw_models = self.model_discoverer(
                models_url,
                api_key,
                max(3, min(int(timeout_seconds), 20)),
            )
        except Exception as exc:
            if _stable_probe_error_code(exc) in STABLE_PROBE_ERROR_CODES:
                raise
            raise NonRetryableExecutionError(
                "DeepSeek model discovery failed",
                safe_message="DeepSeek 模型发现失败",
                error_code="deepseek_model_discovery_failed",
            ) from exc
        if not isinstance(raw_models, list):
            raise _model_discovery_error()
        unique: dict[str, dict[str, str]] = {}
        for item in raw_models:
            if not isinstance(item, dict):
                raise _model_discovery_error()
            model_id = item.get("id")
            if (
                not isinstance(model_id, str)
                or not model_id
                or len(model_id) > MAX_MODEL_ID_LENGTH
                or any(ord(char) < 32 for char in model_id)
            ):
                raise _model_discovery_error()
            unique.setdefault(model_id, {"id": model_id, "display_name": model_id})
            if len(unique) > MAX_DISCOVERED_MODELS:
                raise NonRetryableExecutionError(
                    "DeepSeek model list exceeds limit",
                    safe_message="DeepSeek 返回的模型数量超过限制",
                    error_code="deepseek_model_discovery_failed",
                )
        if not unique:
            raise NonRetryableExecutionError(
                "DeepSeek model list is empty",
                safe_message="DeepSeek 没有返回可用模型",
                error_code="deepseek_model_list_empty",
            )
        return [unique[model_id] for model_id in sorted(unique)]

    def _resolve_probe_credential(
        self,
        *,
        code: str,
        credential_source: str,
        api_key: str,
    ) -> str:
        source = str(credential_source or "")
        submitted = str(api_key or "").strip()
        if source == "submitted":
            if not submitted:
                raise _validation_error("api_key", "必须填写新的 API Key")
            return submitted
        if source != "existing":
            raise _validation_error(
                "credential_source",
                "必须选择本次提交或沿用现有 Credential",
            )
        if submitted:
            raise _validation_error(
                "api_key",
                "沿用现有 Credential 时不能同时提交 API Key",
            )
        connection = self.repository.get_connection(code)
        revision_id = str(connection.get("current_revision_id") or "")
        if str(connection.get("status") or "") != "ready" or not revision_id:
            raise _credential_unavailable()
        revision = self.repository.get_revision(revision_id)
        secret_id = str(revision.get("api_key_secret_id") or "")
        if str(revision.get("status") or "") != "ready" or not self._secret_ready(secret_id):
            raise _credential_unavailable()
        try:
            secret = self.platform_repository.get_platform_secret(secret_id)
            return self.secret_provider.resolve(str(secret["ref"]))
        except Exception as exc:
            raise _credential_unavailable() from exc

    def _temporary_binding(
        self,
        connection: dict[str, Any],
        config: dict[str, str | int],
    ) -> ModelRuntimeBinding:
        return ModelRuntimeBinding(
            protocol=str(config["protocol"]),
            base_url=str(config["base_url"]),
            model=str(config["model"]),
            default_opus_model=str(config["default_opus_model"]),
            default_sonnet_model=str(config["default_sonnet_model"]),
            default_haiku_model=str(config["default_haiku_model"]),
            subagent_model=str(config["subagent_model"]),
            effort_level=str(config["effort_level"]),
            connection_id=str(connection["id"]),
            connection_code=str(connection["code"]),
            connection_revision=int(connection["revision"]),
            config_hash=_hash(config),
        )

    def _test_temporary_binding(
        self,
        binding: ModelRuntimeBinding,
        api_key: str,
        timeout_seconds: int,
    ) -> None:
        if self.tester is None:
            raise NonRetryableExecutionError(
                "Model connection tester is unavailable",
                safe_message="模型连接测试运行时不可用",
                error_code="model_connection_test_unavailable",
            )
        try:
            self.tester(binding, api_key, max(3, min(int(timeout_seconds), 30)))
        except Exception as exc:
            code = _stable_probe_error_code(exc)
            if code == "model_connection_test_timeout":
                raise NonRetryableExecutionError(
                    "Model connection test timed out",
                    safe_message="模型连接测试超时",
                    error_code=code,
                ) from exc
            raise NonRetryableExecutionError(
                "Model connection test failed",
                safe_message="模型连接测试失败，请检查模型和 Credential",
                error_code="model_connection_test_failed",
            ) from exc

    @staticmethod
    def _require_discovered_models(
        config: dict[str, str | int],
        models: list[dict[str, str]],
    ) -> None:
        available = {item["id"] for item in models}
        for field in (
            "model",
            "default_opus_model",
            "default_sonnet_model",
            "default_haiku_model",
            "subagent_model",
        ):
            if str(config[field]) not in available:
                raise NonRetryableExecutionError(
                    f"Configured model is unavailable: {field}",
                    safe_message="选择的模型不在 DeepSeek 当前可用列表中",
                    error_code="deepseek_model_unavailable",
                    field_errors=[{"field": field, "message": "请重新选择当前可用模型"}],
                )

    def _require_expected_revision(
        self,
        code: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        connection = self.repository.get_connection(code)
        if int(connection["revision"]) != expected_revision:
            raise NonRetryableExecutionError(
                "Model connection revision conflict",
                safe_message="模型连接已发生变化，请刷新后重新检测",
                error_code="revision_conflict",
                diagnostics={"current_revision": int(connection["revision"])},
            )
        return connection

    def _configured_secret_id(
        self,
        *,
        actor_id: str,
        connection: dict[str, Any],
        credential_source: str,
        api_key: str,
    ) -> str:
        revision_id = str(connection.get("current_revision_id") or "")
        current = self.repository.get_revision(revision_id) if revision_id else None
        bound_secret_id = str(current.get("api_key_secret_id") or "") if current else ""
        if credential_source == "existing":
            if (
                current is None
                or str(current.get("status") or "") != "ready"
                or not self._secret_ready(bound_secret_id)
            ):
                raise _credential_unavailable()
            return bound_secret_id

        value = str(api_key or "").strip()
        if not value:
            raise _validation_error("api_key", "必须填写新的 API Key")
        if bound_secret_id:
            try:
                bound = self.platform_repository.get_platform_secret(bound_secret_id)
            except NotFound:
                bound = None
            if bound is not None:
                self.secret_provider.rotate_secret(
                    code=str(bound["code"]),
                    value=value,
                    actor_id=actor_id,
                )
                return str(bound["id"])

        secret_code = f"model-{connection['code']}-api-key"
        orphan = self.platform_repository.get_platform_secret_by_code(secret_code)
        ownership: dict[str, object] = {
            "kind": "model_connection",
            "connection_code": str(connection["code"]),
            "connection_id": str(connection["id"]),
        }
        if orphan is not None:
            metadata = dict(orphan.get("metadata") or {})
            if any(metadata.get(key) != expected for key, expected in ownership.items()):
                raise NonRetryableExecutionError(
                    "Deterministic model credential is owned by another resource",
                    safe_message="模型 Credential 所有权冲突，请检查凭据中心",
                    error_code="credential_ownership_conflict",
                )
            self.secret_provider.rotate_secret(
                code=secret_code,
                value=value,
                actor_id=actor_id,
            )
            return str(orphan["id"])
        created = self.secret_provider.create_secret(
            code=secret_code,
            value=value,
            purpose=f"DeepSeek credential for {connection['code']}",
            actor_id=actor_id,
            metadata=ownership,
        )
        return str(created["id"])

    def _record_probe_audit(
        self,
        *,
        actor_id: str,
        code: str,
        action: str,
        status: str,
        provider_host: str,
        duration_ms: int,
        model: str = "",
        error_code: str = "",
    ) -> None:
        self.audit_service.record(
            f"model.connection.{action.replace('-', '_')}_{status.lower()}",
            status=status,
            summary=f"Model connection {action} {status.lower()}",
            actor_id=actor_id,
            payload={
                "actor_id": actor_id,
                "connection_code": code,
                "provider_host": provider_host,
                "model": model,
                "duration_ms": duration_ms,
                "result": status.lower(),
                "error_code": error_code,
            },
        )

    def _public_connection(self, connection: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(connection["id"]),
            "code": str(connection["code"]),
            "name": str(connection["name"]),
            "protocol": str(connection["protocol"]),
            "status": str(connection["status"]),
            "revision": int(connection["revision"]),
            "current_revision_id": str(connection.get("current_revision_id") or ""),
            "created_at": str(connection["created_at"]),
            "updated_at": str(connection["updated_at"]),
        }

    def _public_revision(self, revision: dict[str, Any] | None) -> dict[str, Any]:
        if revision is None:
            return {}
        if _hash(dict(revision["config"])) != str(revision["config_hash"]):
            raise NonRetryableExecutionError(
                "Model connection revision hash mismatch",
                safe_message="模型连接完整性校验失败",
                error_code="model_connection_integrity_failed",
            )
        secret_id = str(revision.get("api_key_secret_id") or "")
        credential = {
            "configured": False,
            "masked": "",
            "version": 0,
            "updated_at": "",
            "rotation_required": True,
        }
        if secret_id:
            try:
                secret = self.platform_repository.get_platform_secret(secret_id)
            except NotFound:
                secret = None
            if secret is not None:
                configured = bool(secret.get("configured"))
                credential = {
                    "configured": configured,
                    "masked": (str(secret.get("masked_summary") or "") if configured else ""),
                    "version": int(secret.get("active_version") or 0),
                    "updated_at": str(secret.get("updated_at") or ""),
                    "rotation_required": not configured or revision["status"] != "ready",
                }
        config = dict(revision["config"])
        return {
            "id": str(revision["id"]),
            "connection_id": str(revision["connection_id"]),
            "connection_code": str(revision["connection_code"]),
            "revision": int(revision["revision"]),
            "status": (
                "disabled"
                if str(revision.get("connection_status") or "") == "disabled"
                else str(revision["status"])
            ),
            "config": config,
            "config_hash": str(revision["config_hash"]),
            "provider_host": (urlsplit(str(config.get("base_url") or "")).hostname or ""),
            "credential": credential,
            "created_by": str(revision.get("created_by") or ""),
            "created_at": str(revision.get("created_at") or ""),
        }

    def _secret_ready(self, secret_id: str) -> bool:
        if not secret_id:
            return False
        try:
            secret = self.platform_repository.get_platform_secret(secret_id)
        except Exception:
            return False
        return bool(secret.get("configured")) and secret.get("status") == "enabled"

    def _runtime_anthropic_secret_id(self) -> str:
        candidates = [
            item
            for item in self.platform_repository.list_runtime_config_values(include_disabled=False)
            if item.get("key") in {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"}
            and item.get("secret_ref")
        ]
        candidates.sort(
            key=lambda item: (
                item.get("service_name") == "agent-worker",
                item.get("key") == "ANTHROPIC_API_KEY",
            ),
            reverse=True,
        )
        for item in candidates:
            secret = self.platform_repository.get_platform_secret_by_ref(str(item["secret_ref"]))
            if secret and secret.get("status") == "enabled":
                return str(secret["id"])
        return ""

    def _require_agent_editor(self, actor_id: str) -> None:
        self.authorization.require(
            user_id=actor_id,
            resource_type="agent",
            resource_code=DEFAULT_AGENT_CODE,
            action="edit",
        )

    def _require_secret_admin(self, actor_id: str) -> None:
        self.authorization.require(
            user_id=actor_id,
            resource_type="secret",
            resource_code="*",
            action="manage",
        )


def _hash(config: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _model_value(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 200 or any(ord(char) < 32 for char in text):
        raise _validation_error(field, "必须填写模型标识，且最多允许 200 个字符")
    return text


def _validation_error(field: str, message: str) -> NonRetryableExecutionError:
    return NonRetryableExecutionError(
        f"Invalid model connection field {field}: {message}",
        safe_message="模型连接配置无效",
        error_code="validation_failed",
        field_errors=[{"field": field, "message": message}],
    )


def _deepseek_url_error(message: str) -> NonRetryableExecutionError:
    return NonRetryableExecutionError(
        f"Invalid DeepSeek Base URL: {message}",
        safe_message="DeepSeek 模型地址无效",
        error_code="deepseek_url_invalid",
        field_errors=[{"field": "base_url", "message": message}],
    )


def _credential_unavailable() -> NonRetryableExecutionError:
    return NonRetryableExecutionError(
        "Current model credential is unavailable",
        safe_message="当前 Credential 不可用，请填写新的 API Key",
        error_code="model_connection_credential_unavailable",
        field_errors=[{"field": "api_key", "message": "请填写新的 API Key"}],
    )


def _model_discovery_error() -> NonRetryableExecutionError:
    return NonRetryableExecutionError(
        "DeepSeek model response has an invalid shape",
        safe_message="DeepSeek 返回的模型列表格式无效",
        error_code="deepseek_model_discovery_failed",
    )


def _stable_probe_error_code(exc: Exception) -> str:
    code = str(getattr(exc, "error_code", "") or "")
    if code in STABLE_PROBE_ERROR_CODES:
        return code
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "model_connection_test_timeout"
    return "deepseek_model_discovery_failed"


def _safe_probe_error(exc: Exception) -> NonRetryableExecutionError:
    code = _stable_probe_error_code(exc)
    messages = {
        "deepseek_url_invalid": "DeepSeek 模型地址无效",
        "deepseek_credential_rejected": "DeepSeek 拒绝了 Credential",
        "deepseek_model_discovery_failed": "DeepSeek 模型发现失败",
        "deepseek_model_list_empty": "DeepSeek 没有返回可用模型",
        "deepseek_model_unavailable": "选择的模型当前不可用",
        "model_connection_test_timeout": "模型连接测试超时",
        "model_connection_test_failed": "模型连接测试失败，请检查模型和 Credential",
        "model_connection_test_unavailable": "模型连接测试运行时不可用",
    }
    return NonRetryableExecutionError(
        "Model connection probe failed",
        safe_message=messages.get(code, "DeepSeek 模型发现失败"),
        error_code=code,
        field_errors=(
            [{"field": "model", "message": "请重新选择当前可用模型"}]
            if code == "deepseek_model_unavailable"
            else []
        ),
    )


def _deepseek_models_url(base_url: str) -> str:
    parsed = urlsplit(base_url)
    suffix = "/anthropic"
    if not parsed.path.endswith(suffix):
        raise _deepseek_url_error("DeepSeek Base URL 必须以 /anthropic 结尾")
    prefix = parsed.path[: -len(suffix)]
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            f"{prefix}/models",
            "",
            "",
        )
    )


def _fetch_deepseek_models(
    models_url: str,
    api_key: str,
    timeout_seconds: int,
) -> list[dict[str, str]]:
    assert_external_io_allowed("model.deepseek_discovery")
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(
        models_url,
        method="GET",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "enterprise-agent-model-discovery/1",
        },
    )
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            status = int(getattr(response, "status", 200) or 200)
            body = response.read(MAX_DISCOVERY_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if int(exc.code) in {401, 403}:
            raise NonRetryableExecutionError(
                "DeepSeek rejected the supplied credential",
                safe_message="DeepSeek 拒绝了 Credential",
                error_code="deepseek_credential_rejected",
            ) from exc
        if 300 <= int(exc.code) < 400:
            raise NonRetryableExecutionError(
                "DeepSeek model endpoint redirected",
                safe_message="DeepSeek 模型地址不能发生重定向",
                error_code="deepseek_url_invalid",
            ) from exc
        raise NonRetryableExecutionError(
            "DeepSeek model discovery returned an error",
            safe_message="DeepSeek 模型发现失败",
            error_code="deepseek_model_discovery_failed",
        ) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise NonRetryableExecutionError(
            "DeepSeek model discovery timed out",
            safe_message="DeepSeek 模型发现超时",
            error_code="deepseek_model_discovery_failed",
        ) from exc
    except (OSError, urllib.error.URLError) as exc:
        raise NonRetryableExecutionError(
            "DeepSeek model discovery failed",
            safe_message="DeepSeek 模型发现失败",
            error_code="deepseek_model_discovery_failed",
        ) from exc
    if 300 <= status < 400:
        raise _deepseek_url_error("DeepSeek 模型地址不能发生重定向")
    if status in {401, 403}:
        raise NonRetryableExecutionError(
            "DeepSeek rejected the supplied credential",
            safe_message="DeepSeek 拒绝了 Credential",
            error_code="deepseek_credential_rejected",
        )
    if status < 200 or status >= 300 or len(body) > MAX_DISCOVERY_BYTES:
        raise _model_discovery_error()
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _model_discovery_error() from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise _model_discovery_error()
    items: list[dict[str, str]] = []
    for item in payload["data"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise _model_discovery_error()
        items.append({"id": item["id"]})
    return items


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None


def _assert_provider_does_not_redirect(base_url: str, timeout_seconds: int) -> None:
    assert_external_io_allowed("model.redirect_probe")
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(
        base_url,
        method="HEAD",
        headers={"User-Agent": "enterprise-agent-connection-check/1"},
    )
    try:
        response = opener.open(request, timeout=timeout_seconds)
        status = int(getattr(response, "status", 200) or 200)
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
    except (OSError, urllib.error.URLError):
        # The SDK probe remains the authoritative availability test. This
        # preflight exists only to reject redirects before credentials are used.
        return
    if 300 <= status < 400:
        raise NonRetryableExecutionError(
            "Model provider Base URL redirects",
            safe_message="模型提供方 Base URL 不能发生重定向",
            error_code="model_connection_redirect_rejected",
        )
