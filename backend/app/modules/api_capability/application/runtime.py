from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, cast

from app.modules.api_capability.application.connection_service import (
    AuthenticationProfileV1,
)
from app.modules.api_capability.domain import (
    CompiledMappingPlanContract,
    MappingInterpreter,
    validate_schema_instance,
)
from app.modules.api_capability.domain.contracts import content_hash
from app.modules.api_capability.infrastructure import (
    ApiCapabilityRepository,
    ApiConnectionRepository,
    GovernedApiExecutionRepository,
    RestrictedHttpJsonClient,
)
from app.modules.identity.infrastructure import (
    ExternalApiCredentialCipher,
    ExternalApiCredentialRepository,
    IdentityRepository,
)
from app.shared.exceptions import (
    AppError,
    NonRetryableExecutionError,
    RetryableExecutionError,
)


@dataclass(frozen=True, slots=True)
class ResolvedCapabilityRelease:
    release: dict[str, Any]
    connection: dict[str, Any]
    authentication_profile: AuthenticationProfileV1
    mapping_plan: dict[str, Any]


class GovernedCapabilityReleaseResolver:
    def __init__(
        self,
        capability_repository: ApiCapabilityRepository,
        connection_repository: ApiConnectionRepository,
    ) -> None:
        self.capability_repository = capability_repository
        self.connection_repository = connection_repository

    def resolve(
        self,
        release_id: str,
        *,
        expected_identifier: str,
    ) -> ResolvedCapabilityRelease:
        release = self.capability_repository.get_release(release_id)
        if str(release["identifier"]) != expected_identifier:
            raise _runtime_configuration_error(
                "Capability Identifier does not match frozen Release"
            )
        if str(release["status"]) not in {"ACTIVE", "DEPRECATED"}:
            raise _runtime_configuration_error("Capability Release is disabled or archived")
        if str(release["executor_id"]) != "http-json-v1":
            raise _runtime_configuration_error("Capability executor is not http-json-v1")
        try:
            mapping = CompiledMappingPlanContract.parse(release["mapping_plan"]).to_dict()
        except ValueError:
            raise _runtime_configuration_error("Compiled Mapping Plan is invalid") from None
        connection = self.connection_repository.get_revision(str(release["connection_revision_id"]))
        if (
            str(connection["status"]) != "PUBLISHED"
            or str(connection["authentication_status"]) != "PUBLISHED"
            or str(connection["authentication_profile_revision_id"])
            != str(release["authentication_profile_revision_id"])
        ):
            raise _runtime_configuration_error(
                "Frozen Connection or Authentication Profile is unavailable"
            )
        return ResolvedCapabilityRelease(
            release=release,
            connection=connection,
            authentication_profile=AuthenticationProfileV1(connection["authentication"]),
            mapping_plan=mapping,
        )


class GovernedApiRuntimeExecutor:
    def __init__(
        self,
        *,
        resolver: GovernedCapabilityReleaseResolver,
        execution_repository: GovernedApiExecutionRepository,
        identity_repository: IdentityRepository,
        credential_repository: ExternalApiCredentialRepository,
        credential_cipher: ExternalApiCredentialCipher | None,
        http_client: RestrictedHttpJsonClient | None = None,
        mapping_interpreter: MappingInterpreter | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.resolver = resolver
        self.execution_repository = execution_repository
        self.identity_repository = identity_repository
        self.credential_repository = credential_repository
        self.credential_cipher = credential_cipher
        self.http_client = http_client or RestrictedHttpJsonClient()
        self.mapping_interpreter = mapping_interpreter or MappingInterpreter()
        self.sleeper = sleeper
        self.monotonic = monotonic

    def execute(
        self,
        *,
        job_id: str,
        tool_call_id: str,
        user_id: str,
        application_publication_id: str,
        agent_publication_id: str,
        capability_release_id: str,
        identifier: str,
        agent_input: dict[str, Any],
        correlation_id: str,
        timeout_seconds: float,
        attempt_budget: int = 3,
    ) -> dict[str, Any]:
        self._require_governance_intersection(
            job_id=job_id,
            user_id=user_id,
            application_publication_id=application_publication_id,
            agent_publication_id=agent_publication_id,
            release_id=capability_release_id,
            identifier=identifier,
        )
        resolved = self.resolver.resolve(
            capability_release_id,
            expected_identifier=identifier,
        )
        release = resolved.release
        validate_schema_instance(
            release["input_schema"],
            agent_input,
            label="input",
        )
        subject, token = self._current_subject_and_token(
            job_id=job_id,
            user_id=user_id,
            connection_revision_id=str(resolved.connection["id"]),
        )
        system_context = {
            "external_user_id": subject["external_user_id"],
            "default_team_id": subject["default_team_id"],
        }
        request_value = self.mapping_interpreter.execute(
            resolved.mapping_plan["request_plan"],
            agent_input=agent_input,
            system_context=system_context,
        )
        query, body = _mapped_request(request_value)
        graphql_document = str(release.get("graphql_document") or "")
        request_body = {"query": graphql_document, "variables": body} if graphql_document else body
        request_hash = content_hash(
            {
                "method": release["method"],
                "relative_path": release["relative_path"],
                "query": query,
                "body": request_body,
            }
        )
        maximum_attempts = max(1, min(int(attempt_budget), 3))
        deadline = self.monotonic() + max(0.1, timeout_seconds)
        last_error: AppError | None = None
        for attempt_no in range(1, maximum_attempts + 1):
            if self.monotonic() >= deadline:
                raise NonRetryableExecutionError(
                    "Governed API execution timeout budget exhausted",
                    safe_message="外部 API 调用超时",
                    error_code="external_api_timeout_budget_exhausted",
                )
            started = self.monotonic()
            http_status: int | None = None
            response_size = 0
            try:
                response = self.http_client.request(
                    connection=resolved.connection,
                    method=str(release["method"]),
                    relative_path=str(release["relative_path"]),
                    query=query,
                    body=(request_body if str(release["method"]) == "POST" else None),
                    authentication_header=(
                        resolved.authentication_profile.authentication_header(token)
                    ),
                )
                http_status = response.status
                response_size = response.response_size
                normalized = self.mapping_interpreter.execute(
                    resolved.mapping_plan["response_plan"],
                    agent_input=agent_input,
                    system_context=system_context,
                    response=response.payload,
                )
                validate_schema_instance(
                    release["output_schema"],
                    normalized,
                    label="output",
                )
                encoded = json.dumps(
                    normalized,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode()
                response_hash = content_hash(normalized)
                self.execution_repository.record_attempt(
                    tool_call_id=tool_call_id,
                    job_id=job_id,
                    capability_release_id=capability_release_id,
                    correlation_id=correlation_id,
                    attempt_no=attempt_no,
                    status_class="SUCCEEDED",
                    http_status=http_status,
                    duration_ms=max(
                        0,
                        int((self.monotonic() - started) * 1000),
                    ),
                    response_size=response_size,
                    request_hash=request_hash,
                    response_hash=response_hash,
                )
                self.execution_repository.record_provenance(
                    tool_call_id=tool_call_id,
                    user_id=user_id,
                    application_publication_id=application_publication_id,
                    agent_publication_id=agent_publication_id,
                    capability_release_id=capability_release_id,
                    normalized_result=encoded,
                )
                return cast(dict[str, Any], normalized)
            except AppError as exc:
                last_error = exc
                http_status = _http_status(exc)
                if exc.error_code == "external_api_unauthorized":
                    self.credential_repository.set_status(
                        user_id=user_id,
                        status="INVALID",
                        error_code=exc.error_code,
                    )
                self.execution_repository.record_attempt(
                    tool_call_id=tool_call_id,
                    job_id=job_id,
                    capability_release_id=capability_release_id,
                    correlation_id=correlation_id,
                    attempt_no=attempt_no,
                    status_class=_status_class(exc),
                    http_status=http_status,
                    duration_ms=max(
                        0,
                        int((self.monotonic() - started) * 1000),
                    ),
                    response_size=response_size,
                    request_hash=request_hash,
                    safe_error_code=exc.error_code,
                )
                retryable = isinstance(exc, RetryableExecutionError)
                if not retryable or attempt_no >= maximum_attempts:
                    raise
                delay = 0.1 * (2 ** (attempt_no - 1))
                if self.monotonic() + delay >= deadline:
                    raise NonRetryableExecutionError(
                        "Governed API retry would exceed timeout budget",
                        safe_message="外部 API 调用超时",
                        error_code="external_api_timeout_budget_exhausted",
                    ) from exc
                self.sleeper(delay)
        if last_error is not None:
            raise last_error
        raise RuntimeError("Governed API execution did not run")

    def assert_subject_available(
        self,
        *,
        job_id: str,
        user_id: str,
        connection_revision_id: str,
    ) -> None:
        snapshot = self.execution_repository.get_external_subject(job_id)
        identity = self.identity_repository.get_external_identity(
            str(snapshot["external_identity_id"])
        )
        metadata = identity["metadata"]
        credential = self.credential_repository.get_current_public(user_id=user_id)
        if (
            str(identity["user_id"]) != user_id
            or str(identity["status"]) != "enabled"
            or str(identity["external_subject_id"]) != str(snapshot["external_user_id"])
            or str(metadata.get("default_team_id") or "") != str(snapshot["default_team_id"])
            or str(snapshot["default_team_id"]) not in set(metadata.get("team_uuids") or [])
            or str(credential["status"]) != "ACTIVE"
            or str(credential["external_identity_id"]) != str(identity["id"])
            or str(credential["connection_revision_id"]) != connection_revision_id
        ):
            raise NonRetryableExecutionError(
                "Current ONES subject is unavailable for Tool catalog",
                safe_message="ONES 绑定不可用，请重新绑定",
                error_code="external_subject_unavailable",
            )

    def _current_subject_and_token(
        self,
        *,
        job_id: str,
        user_id: str,
        connection_revision_id: str,
    ) -> tuple[dict[str, Any], str]:
        snapshot = self.execution_repository.get_external_subject(job_id)
        identity = self.identity_repository.get_external_identity(
            str(snapshot["external_identity_id"])
        )
        metadata = identity["metadata"]
        if (
            str(identity["user_id"]) != user_id
            or str(identity["status"]) != "enabled"
            or str(identity["external_subject_id"]) != str(snapshot["external_user_id"])
            or str(metadata.get("default_team_id") or "") != str(snapshot["default_team_id"])
            or str(snapshot["default_team_id"]) not in set(metadata.get("team_uuids") or [])
        ):
            raise NonRetryableExecutionError(
                "Current ONES binding differs from Job snapshot",
                safe_message="ONES 绑定或默认 Team 已变化，请重新发起请求",
                error_code="external_subject_changed",
            )
        credential = self.credential_repository.get_current_public(user_id=user_id)
        if (
            str(credential["status"]) != "ACTIVE"
            or str(credential["external_identity_id"]) != str(identity["id"])
            or str(credential["connection_revision_id"]) != connection_revision_id
        ):
            raise NonRetryableExecutionError(
                "Current ONES credential does not match frozen execution",
                safe_message="ONES 凭据不可用，请重新绑定",
                error_code="external_credential_invalid",
            )
        if self.credential_cipher is None:
            raise NonRetryableExecutionError(
                "External credential cipher is unavailable",
                safe_message="ONES 凭据不可用，请重新绑定",
                error_code="external_credential_encryption_unavailable",
            )
        encrypted = self.credential_repository.get_current_encrypted(user_id=user_id)
        return snapshot, self.credential_cipher.decrypt(
            ciphertext=encrypted.ciphertext,
            key_id=encrypted.key_id,
        )

    def _require_governance_intersection(
        self,
        *,
        job_id: str,
        user_id: str,
        application_publication_id: str,
        agent_publication_id: str,
        release_id: str,
        identifier: str,
    ) -> None:
        database = self.execution_repository.database
        job = database.execute_one(
            """
            select internal_user_id, agent_publication_id,
                   business_application_publication_id
              from agent_job where id = ?
            """,
            (job_id,),
        )
        if (
            job is None
            or str(job.get("internal_user_id") or "") != user_id
            or str(job.get("agent_publication_id") or "") != agent_publication_id
            or str(job.get("business_application_publication_id") or "")
            != application_publication_id
        ):
            raise _runtime_configuration_error(
                "Tool execution does not match frozen Job publications"
            )
        allowed = database.execute_one(
            """
            select a.id
              from agent_publication_api_capability a
              join business_application_publication_api_capability p
                on p.agent_publication_id = a.agent_publication_id
               and p.capability_release_id = a.capability_release_id
               and p.identifier = a.identifier
             where a.agent_publication_id = ?
               and p.application_publication_id = ?
               and a.capability_release_id = ?
               and a.identifier = ?
            """,
            (
                agent_publication_id,
                application_publication_id,
                release_id,
                identifier,
            ),
        )
        if allowed is None:
            raise NonRetryableExecutionError(
                "Capability is outside Agent/Application governance intersection",
                safe_message="当前应用未启用此 Capability",
                error_code="capability_not_allowed",
            )


def _mapped_request(
    value: Any,
) -> tuple[dict[str, str | int | float | bool], dict[str, Any]]:
    if not isinstance(value, dict) or set(value) - {"query", "body"}:
        raise NonRetryableExecutionError(
            "Request Mapping must produce query/body object",
            safe_message="Handler Request Mapping 输出无效",
            error_code="mapping_execution_failed",
        )
    query = value.get("query", {})
    body = value.get("body", {})
    if not isinstance(query, dict) or not isinstance(body, dict):
        raise NonRetryableExecutionError(
            "Mapped query and body must be objects",
            safe_message="Handler Request Mapping 输出无效",
            error_code="mapping_execution_failed",
        )
    if any(isinstance(item, (dict, list)) or item is None for item in query.values()):
        raise NonRetryableExecutionError(
            "Mapped query values must be scalars",
            safe_message="Handler Query Mapping 输出无效",
            error_code="mapping_execution_failed",
        )
    return query, body


def _status_class(exc: AppError) -> str:
    if isinstance(exc, RetryableExecutionError):
        return "RETRYABLE_FAILURE"
    if exc.error_code == "external_api_unauthorized":
        return "CREDENTIAL_INVALID"
    if exc.error_code == "external_api_forbidden":
        return "FORBIDDEN"
    if exc.error_code.startswith("mapping_"):
        return "MAPPING_FAILED"
    if exc.error_code == "capability_schema_validation_failed":
        return "SCHEMA_FAILED"
    return "NON_RETRYABLE_FAILURE"


def _http_status(exc: AppError) -> int | None:
    value = exc.diagnostics.get("http_status")
    return int(value) if isinstance(value, int) else None


def _runtime_configuration_error(
    reason: str,
) -> NonRetryableExecutionError:
    return NonRetryableExecutionError(
        f"Governed API runtime configuration is invalid: {reason}",
        safe_message="Capability 运行配置不可用",
        error_code="capability_runtime_configuration_invalid",
    )
