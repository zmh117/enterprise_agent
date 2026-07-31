from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Any, Protocol

from app.modules.api_capability.infrastructure.connection_repository import (
    ApiConnectionRepository,
)
from app.modules.api_capability.infrastructure.http_json_client import (
    RestrictedHttpJsonClient,
    validate_authentication_header_name,
    validate_relative_path,
)
from app.modules.audit.application.audit_service import AuditService
from app.modules.identity.application.authorization import (
    AuthorizationEvaluator,
)
from app.shared.exceptions import NonRetryableExecutionError


PRODUCTION_ENVIRONMENTS = frozenset({"prod", "production"})
_PROFILE_KEYS = frozenset({"schema_version", "login", "extract", "inject"})
_LOGIN_KEYS = frozenset({"method", "relative_path", "email_field", "password_field"})
_EXTRACT_KEYS = frozenset(
    {
        "token_path",
        "user_id_path",
        "display_name_path",
        "teams_path",
        "team_id_field",
        "team_name_field",
    }
)
_INJECT_KEYS = frozenset({"header_name", "value_prefix"})


@dataclass(frozen=True, slots=True)
class AuthenticatedExternalSubject:
    external_user_id: str
    display_name: str
    teams: tuple[dict[str, str], ...]
    token: str
    authentication_header: tuple[str, str]

    def safe_summary(self) -> dict[str, Any]:
        return {
            "external_user_id": self.external_user_id,
            "display_name": self.display_name,
            "teams": [dict(team) for team in self.teams],
        }


class AuthenticationProfileV1:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = self.normalize(config)

    @classmethod
    def normalize(cls, config: dict[str, Any]) -> dict[str, Any]:
        _require_exact_keys(config, _PROFILE_KEYS, "Authentication Profile")
        if config.get("schema_version") != 1:
            raise _profile_error("schema_version must be 1")
        login = _require_object(config, "login")
        extract = _require_object(config, "extract")
        inject = _require_object(config, "inject")
        _require_exact_keys(login, _LOGIN_KEYS, "login")
        _require_exact_keys(extract, _EXTRACT_KEYS, "extract")
        _require_exact_keys(inject, _INJECT_KEYS, "inject")
        if str(login.get("method") or "").upper() != "POST":
            raise _profile_error("login.method must be POST")
        normalized_login = {
            "method": "POST",
            "relative_path": validate_relative_path(str(login.get("relative_path") or "")),
            "email_field": _field_name(login, "email_field"),
            "password_field": _field_name(login, "password_field"),
        }
        if normalized_login["email_field"] == normalized_login["password_field"]:
            raise _profile_error("login request fields must be distinct")
        normalized_extract = {
            key: _json_path(extract, key)
            for key in (
                "token_path",
                "user_id_path",
                "display_name_path",
                "teams_path",
            )
        }
        normalized_extract["team_id_field"] = _field_name(
            extract,
            "team_id_field",
        )
        normalized_extract["team_name_field"] = _field_name(
            extract,
            "team_name_field",
        )
        normalized_inject = {
            "header_name": validate_authentication_header_name(
                str(inject.get("header_name") or "")
            ),
            "value_prefix": str(inject.get("value_prefix") or ""),
        }
        if len(normalized_inject["value_prefix"]) > 64:
            raise _profile_error("inject.value_prefix is too long")
        return {
            "schema_version": 1,
            "login": normalized_login,
            "extract": normalized_extract,
            "inject": normalized_inject,
        }

    def authenticate(
        self,
        *,
        client: RestrictedHttpJsonClient,
        connection: dict[str, Any],
        email: str,
        password: str,
    ) -> AuthenticatedExternalSubject:
        login = self.config["login"]
        response = client.request(
            connection=connection,
            method="POST",
            relative_path=str(login["relative_path"]),
            body={
                str(login["email_field"]): email.strip(),
                str(login["password_field"]): password,
            },
        )
        payload = response.payload
        extract = self.config["extract"]
        token = _required_text_at(payload, str(extract["token_path"]), "Token")
        external_user_id = _required_text_at(
            payload,
            str(extract["user_id_path"]),
            "User ID",
        )
        display_name = _required_text_at(
            payload,
            str(extract["display_name_path"]),
            "User display name",
        )
        raw_teams = _value_at(payload, str(extract["teams_path"]))
        if not isinstance(raw_teams, list) or not raw_teams:
            raise _profile_response_error("Team collection is missing")
        teams: list[dict[str, str]] = []
        for item in raw_teams:
            if not isinstance(item, dict):
                raise _profile_response_error("Team entry is not an object")
            team_id = str(item.get(str(extract["team_id_field"])) or "").strip()
            team_name = str(item.get(str(extract["team_name_field"])) or "").strip()
            if not team_id:
                raise _profile_response_error("Team ID is missing")
            if team_id not in {team["id"] for team in teams}:
                teams.append({"id": team_id, "name": team_name})
        inject = self.config["inject"]
        return AuthenticatedExternalSubject(
            external_user_id=external_user_id,
            display_name=display_name,
            teams=tuple(teams),
            token=token,
            authentication_header=(
                str(inject["header_name"]),
                f"{inject['value_prefix']}{token}",
            ),
        )

    def authentication_header(self, token: str) -> tuple[str, str]:
        if not token:
            raise _profile_response_error("Token is empty")
        inject = self.config["inject"]
        return (
            str(inject["header_name"]),
            f"{inject['value_prefix']}{token}",
        )


class AuditPort(Protocol):
    def record(
        self,
        event_type: str,
        *,
        status: str,
        summary: str,
        job_id: str | None = None,
        actor_id: str | None = None,
        payload: Any | None = None,
    ) -> str: ...


class ApiConnectionService:
    def __init__(
        self,
        repository: ApiConnectionRepository,
        authorization: AuthorizationEvaluator,
        audit_service: AuditService | AuditPort,
        *,
        environment: str,
        http_client: RestrictedHttpJsonClient | None = None,
    ) -> None:
        self.repository = repository
        self.authorization = authorization
        self.audit_service = audit_service
        self.environment = environment.strip().lower()
        self.http_client = http_client or RestrictedHttpJsonClient()

    def list(self, *, actor_id: str) -> list[dict[str, Any]]:
        self._require(actor_id, "read")
        return self.repository.list()

    def get(self, connection_id: str, *, actor_id: str) -> dict[str, Any]:
        self._require(actor_id, "read")
        return self.repository.get(connection_id)

    def create(
        self,
        *,
        actor_id: str,
        code: str,
        name: str,
        origin: dict[str, Any],
        authentication: dict[str, Any],
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self._require(actor_id, "manage")
        normalized_origin = normalize_origin(
            origin,
            environment=self.environment,
        )
        normalized_profile = AuthenticationProfileV1.normalize(authentication)
        value = self.repository.create(
            code=code.strip(),
            name=name.strip(),
            provider="ones",
            origin=normalized_origin,
            authentication=normalized_profile,
            actor_id=actor_id,
        )
        self._audit(
            "api_connection.created",
            actor_id,
            value,
            status="SUCCEEDED",
            correlation_id=correlation_id,
        )
        return value

    def save_draft(
        self,
        connection_id: str,
        *,
        actor_id: str,
        expected_revision: int,
        origin: dict[str, Any],
        authentication: dict[str, Any],
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self._require(actor_id, "manage")
        value = self.repository.save_draft(
            connection_id,
            expected_revision=expected_revision,
            origin=normalize_origin(origin, environment=self.environment),
            authentication=AuthenticationProfileV1.normalize(authentication),
            actor_id=actor_id,
        )
        self._audit(
            "api_connection.draft_saved",
            actor_id,
            value,
            status="SUCCEEDED",
            correlation_id=correlation_id,
        )
        return value

    def verify_bootstrap(
        self,
        connection_id: str,
        *,
        actor_id: str,
        draft_revision: int,
        draft_hash: str,
        email: str,
        password: str,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self._require(actor_id, "verify")
        current = self.repository.get(connection_id)
        draft = current["draft"]
        if (
            int(draft["draft_revision"]) != draft_revision
            or str(draft["content_hash"]) != draft_hash
        ):
            raise NonRetryableExecutionError(
                "API Connection Draft revision conflict",
                safe_message="API Connection 草稿已变化，请刷新后重试",
                error_code="revision_conflict",
            )
        normalize_origin(
            {
                "origin_scheme": draft["origin_scheme"],
                "origin_host": draft["origin_host"],
                "origin_port": draft["origin_port"],
                "allow_insecure_local_http": draft["allow_insecure_local_http"],
                "connect_timeout_ms": draft["connect_timeout_ms"],
                "read_timeout_ms": draft["read_timeout_ms"],
                "max_response_bytes": draft["max_response_bytes"],
            },
            environment=self.environment,
        )
        profile = AuthenticationProfileV1(draft["authentication_profile"]["config"])
        try:
            authenticated = profile.authenticate(
                client=self.http_client,
                connection=draft,
                email=email,
                password=password,
            )
        except Exception as exc:
            error_code = str(getattr(exc, "error_code", "") or "verification_failed")
            self.repository.record_verification(
                connection_id,
                draft_revision=draft_revision,
                draft_hash=draft_hash,
                actor_id=actor_id,
                status="FAILED",
                checks={"login": "failed", "error_code": error_code},
                safe_error_summary=str(getattr(exc, "safe_message", "验证失败")),
            )
            self._audit(
                "api_connection.verified",
                actor_id,
                current,
                status="FAILED",
                error_code=error_code,
                correlation_id=correlation_id,
            )
            raise
        evidence = self.repository.record_verification(
            connection_id,
            draft_revision=draft_revision,
            draft_hash=draft_hash,
            actor_id=actor_id,
            status="PASSED",
            checks={
                "origin": "fixed",
                "login": "passed",
                "user_id": "extracted",
                "teams": len(authenticated.teams),
                "authentication_header": "validated",
            },
        )
        self._audit(
            "api_connection.verified",
            actor_id,
            current,
            status="SUCCEEDED",
            correlation_id=correlation_id,
        )
        return {
            "verification": evidence,
            "subject": authenticated.safe_summary(),
        }

    def publish(
        self,
        connection_id: str,
        *,
        actor_id: str,
        draft_revision: int,
        draft_hash: str,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self._require(actor_id, "publish")
        revision = self.repository.publish(
            connection_id,
            draft_revision=draft_revision,
            draft_hash=draft_hash,
            actor_id=actor_id,
        )
        self._audit(
            "api_connection.published",
            actor_id,
            revision,
            status="SUCCEEDED",
            correlation_id=correlation_id,
        )
        return revision

    def set_revision_status(
        self,
        revision_id: str,
        *,
        actor_id: str,
        status: str,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self._require(actor_id, "manage")
        revision = self.repository.set_revision_status(
            revision_id,
            status=status,
            actor_id=actor_id,
        )
        self._audit(
            "api_connection.revision_status_changed",
            actor_id,
            revision,
            status="SUCCEEDED",
            correlation_id=correlation_id,
        )
        return revision

    def _require(self, actor_id: str, action: str) -> None:
        self.authorization.require(
            user_id=actor_id,
            resource_type="api_connection",
            resource_code="*",
            action=action,
        )

    def _audit(
        self,
        event_type: str,
        actor_id: str,
        value: dict[str, Any],
        *,
        status: str,
        error_code: str = "",
        correlation_id: str = "",
    ) -> None:
        self.audit_service.record(
            event_type,
            status=status,
            summary=event_type,
            actor_id=actor_id,
            payload={
                "actor_id": actor_id,
                "connection_id": str(value.get("connection_id") or value.get("id") or ""),
                "revision": int(
                    value.get("revision") or (value.get("draft") or {}).get("draft_revision") or 0
                ),
                "content_hash": str(
                    value.get("content_hash")
                    or (value.get("draft") or {}).get("content_hash")
                    or ""
                ),
                "result": status.lower(),
                "error_code": error_code,
                "correlation_id": correlation_id,
            },
        )


def normalize_origin(
    value: dict[str, Any],
    *,
    environment: str,
) -> dict[str, Any]:
    allowed = {
        "scheme",
        "host",
        "port",
        "allow_insecure_local_http",
        "connect_timeout_ms",
        "read_timeout_ms",
        "max_response_bytes",
        "origin_scheme",
        "origin_host",
        "origin_port",
    }
    unknown = set(value) - allowed
    if unknown:
        raise _origin_error(f"unknown fields: {sorted(unknown)}")
    scheme = str(value.get("scheme") or value.get("origin_scheme") or "").lower()
    host = str(value.get("host") or value.get("origin_host") or "").strip().lower()
    port = int(value.get("port") or value.get("origin_port") or 0)
    allow_insecure = bool(value.get("allow_insecure_local_http", False))
    if scheme not in {"https", "http"}:
        raise _origin_error("scheme must be https or http")
    if (
        not host
        or any(character in host for character in "/@?#{}$*\\")
        or any(character.isspace() for character in host)
    ):
        raise _origin_error("host must be fixed and cannot contain userinfo")
    try:
        normalized_host = host.encode("idna").decode("ascii")
    except UnicodeError:
        raise _origin_error("host is invalid") from None
    if port < 1 or port > 65535:
        raise _origin_error("port is invalid")
    local_mock = _is_loopback_host(normalized_host)
    if scheme == "http" and (
        environment.strip().lower() in PRODUCTION_ENVIRONMENTS
        or not allow_insecure
        or not local_mock
    ):
        raise _origin_error("HTTP is allowed only for an explicit local Mock outside production")
    return {
        "scheme": scheme,
        "host": normalized_host,
        "port": port,
        "allow_insecure_local_http": allow_insecure,
        "connect_timeout_ms": _bounded_int(
            value.get("connect_timeout_ms", 3000),
            minimum=100,
            maximum=30000,
            field_name="connect_timeout_ms",
        ),
        "read_timeout_ms": _bounded_int(
            value.get("read_timeout_ms", 10000),
            minimum=100,
            maximum=60000,
            field_name="read_timeout_ms",
        ),
        "max_response_bytes": _bounded_int(
            value.get("max_response_bytes", 1048576),
            minimum=1024,
            maximum=5242880,
            field_name="max_response_bytes",
        ),
    }


def _value_at(payload: Any, path: str) -> Any:
    current = payload
    for segment in path.removeprefix("$.").split("."):
        if not isinstance(current, dict) or segment not in current:
            raise _profile_response_error(f"{path} is missing")
        current = current[segment]
    return current


def _required_text_at(payload: Any, path: str, label: str) -> str:
    value = _value_at(payload, path)
    if not isinstance(value, str) or not value.strip():
        raise _profile_response_error(f"{label} is not a non-empty string")
    return value.strip()


def _require_object(value: dict[str, Any], key: str) -> dict[str, Any]:
    result = value.get(key)
    if not isinstance(result, dict):
        raise _profile_error(f"{key} must be an object")
    return result


def _require_exact_keys(
    value: dict[str, Any],
    expected: frozenset[str],
    label: str,
) -> None:
    if set(value) != expected:
        raise _profile_error(f"{label} fields must be exactly {sorted(expected)}")


def _field_name(value: dict[str, Any], key: str) -> str:
    result = str(value.get(key) or "")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", result):
        raise _profile_error(f"{key} is invalid")
    return result


def _json_path(value: dict[str, Any], key: str) -> str:
    result = str(value.get(key) or "")
    if not re.fullmatch(r"\$\.[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)*", result):
        raise _profile_error(f"{key} must be a simple typed JSON path")
    return result


def _bounded_int(
    value: Any,
    *,
    minimum: int,
    maximum: int,
    field_name: str,
) -> int:
    if isinstance(value, bool):
        raise _origin_error(f"{field_name} is invalid")
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise _origin_error(f"{field_name} is invalid") from None
    if result < minimum or result > maximum:
        raise _origin_error(f"{field_name} is out of range")
    return result


def _is_loopback_host(host: str) -> bool:
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _origin_error(reason: str) -> NonRetryableExecutionError:
    return NonRetryableExecutionError(
        f"Invalid API Connection Origin: {reason}",
        safe_message="API Connection Origin 配置无效",
        error_code="connection_origin_invalid",
    )


def _profile_error(reason: str) -> NonRetryableExecutionError:
    return NonRetryableExecutionError(
        f"Invalid Authentication Profile: {reason}",
        safe_message="Authentication Profile 配置无效",
        error_code="authentication_profile_invalid",
    )


def _profile_response_error(reason: str) -> NonRetryableExecutionError:
    return NonRetryableExecutionError(
        f"Authentication response does not match Profile: {reason}",
        safe_message="ONES 登录响应与 Authentication Profile 不匹配",
        error_code="authentication_response_invalid",
    )
