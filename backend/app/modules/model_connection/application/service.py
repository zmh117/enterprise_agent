from __future__ import annotations

import hashlib
import ipaddress
import json
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any, Protocol
from urllib.parse import urlsplit

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
from app.shared.exceptions import NonRetryableExecutionError, NotFound


DEFAULT_AGENT_CODE = "default-diagnostic-agent"
DEFAULT_ALLOWED_HOSTS = frozenset({"api.deepseek.com"})
EFFORT_LEVELS = frozenset({"low", "medium", "high", "max"})
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
    def _raise() -> None:
        raise NonRetryableExecutionError(
            "APP_CONFIG_MASTER_KEY is required for model credentials",
            safe_message="Model credential encryption is not configured",
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
        connection = self.repository.get_connection(code)
        normalized = self.normalize_config(config, validate_dns=True)
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
        with self.repository.database.transaction():
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
            raise _validation_error("api_key", "API Key is required")
        connection = self.repository.get_connection(code)
        if int(connection["revision"]) != expected_revision:
            raise NonRetryableExecutionError(
                "Model connection revision conflict",
                safe_message="Model connection changed; refresh and try again",
                error_code="revision_conflict",
                diagnostics={"current_revision": int(connection["revision"])},
            )
        revision_id = str(connection.get("current_revision_id") or "")
        if not revision_id:
            raise NonRetryableExecutionError(
                "Model connection has no configuration revision",
                safe_message="Save model connection configuration before setting a credential",
                error_code="model_connection_revision_required",
            )
        current = self.repository.get_revision(revision_id)
        secret_id = str(current.get("api_key_secret_id") or "")
        with self.repository.database.transaction():
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
                    safe_message="Model connection has no saved revision",
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
        started = time.monotonic()
        binding: ModelRuntimeBinding | None = None
        try:
            binding = self.runtime_binding(revision_id)
            if self.tester is None:
                raise NonRetryableExecutionError(
                    "Model connection tester is unavailable",
                    safe_message="Model connection test runtime is unavailable",
                    error_code="model_connection_test_unavailable",
                )
            self.validate_base_url(binding.base_url, validate_dns=True)
            self.redirect_checker(binding.base_url, max(3, min(timeout_seconds, 10)))
            api_key = self.resolve_api_key(binding)
            outcome = self.tester(binding, api_key, max(3, min(timeout_seconds, 30)))
        except Exception as exc:
            safe_message = getattr(exc, "safe_message", "Model connection test failed")
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
            "provider_host": binding.provider_host,
            "model": binding.model,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "runtime": "claude_agent_sdk",
            "detail": str(outcome.get("detail") or "Connection succeeded")[:200],
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
                safe_message="Model connection integrity check failed",
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
                safe_message="Model connection is disabled",
                error_code="model_connection_disabled",
            )
        config = dict(revision["config"])
        if _hash(config) != str(revision["config_hash"]):
            raise NonRetryableExecutionError(
                "Model connection revision hash mismatch",
                safe_message="Model connection integrity check failed",
                error_code="model_connection_integrity_failed",
            )
        normalized = self.normalize_config(config, validate_dns=True)
        if normalized != config:
            raise NonRetryableExecutionError(
                "Model connection revision is not canonical",
                safe_message="Model connection integrity check failed",
                error_code="model_connection_integrity_failed",
            )
        if revision["status"] != "ready":
            raise NonRetryableExecutionError(
                "Model connection revision is not ready",
                safe_message="Model connection credential must be rotated before use",
                error_code="model_connection_rotation_required",
            )
        secret_id = str(revision.get("api_key_secret_id") or "")
        if not self._secret_ready(secret_id):
            raise NonRetryableExecutionError(
                "Model connection credential is missing or disabled",
                safe_message="Model connection credential is missing or disabled",
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
                safe_message="Model runtime credential is not configured",
                error_code="model_connection_credential_unavailable",
            )
        return self.secret_provider.resolve(binding.secret_ref)

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
        with self.repository.database.transaction():
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
            raise _validation_error(unknown[0], "Field is not configurable for this protocol")
        if "schema_version" in config:
            try:
                schema_version = int(config["schema_version"])
            except (TypeError, ValueError) as exc:
                raise _validation_error("schema_version", "Schema version must be 1") from exc
            if schema_version != 1:
                raise _validation_error("schema_version", "Only schema version 1 is supported")
        protocol = str(config.get("protocol") or ANTHROPIC_COMPATIBLE_PROTOCOL).strip()
        if protocol != ANTHROPIC_COMPATIBLE_PROTOCOL:
            raise _validation_error("protocol", "Only anthropic_compatible is supported")
        base_url = str(config.get("base_url") or "").strip().rstrip("/")
        self.validate_base_url(base_url, validate_dns=validate_dns)
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
                "effort_level", f"Must be one of: {', '.join(sorted(EFFORT_LEVELS))}"
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

    def validate_base_url(self, value: str, *, validate_dns: bool) -> None:
        try:
            parsed = urlsplit(value)
        except ValueError as exc:
            raise _validation_error("base_url", "Invalid provider URL") from exc
        host = (parsed.hostname or "").lower()
        if (
            parsed.scheme != "https"
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or parsed.query
        ):
            raise _validation_error(
                "base_url",
                "Must be an HTTPS URL without credentials, query, or fragment",
            )
        if host not in self.allowed_hosts:
            raise _validation_error("base_url", "Provider host is not allowed")
        if not validate_dns:
            return
        try:
            answers = self.dns_resolver(host, parsed.port or 443, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise _validation_error("base_url", "Provider host cannot be resolved") from exc
        addresses = {str(item[4][0]) for item in answers if item and len(item) >= 5}
        if not addresses:
            raise _validation_error("base_url", "Provider host cannot be resolved")
        for address in addresses:
            try:
                ip = ipaddress.ip_address(address)
            except ValueError as exc:
                raise _validation_error("base_url", "Provider DNS result is invalid") from exc
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_unspecified
                or ip.is_multicast
            ):
                raise _validation_error(
                    "base_url", "Provider host resolves to a disallowed network"
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
                safe_message="Model connection integrity check failed",
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
            secret = self.platform_repository.get_platform_secret(secret_id)
            configured = bool(secret.get("configured"))
            credential = {
                "configured": configured,
                "masked": str(secret.get("masked_summary") or "") if configured else "",
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
        raise _validation_error(field, "Model identifier is required and must be at most 200 chars")
    return text


def _validation_error(field: str, message: str) -> NonRetryableExecutionError:
    return NonRetryableExecutionError(
        f"Invalid model connection field {field}: {message}",
        safe_message="Model connection configuration is invalid",
        error_code="validation_failed",
        field_errors=[{"field": field, "message": message}],
    )


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
            safe_message="Model provider Base URL must not redirect",
            error_code="model_connection_redirect_rejected",
        )
