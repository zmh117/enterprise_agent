from __future__ import annotations

import builtins
import re
from typing import Any

from app.modules.api_capability.application.connection_service import (
    AuthenticationProfileV1,
)
from app.modules.api_capability.domain import (
    CapabilityIdentifier,
    MappingCompiler,
    MappingInterpreter,
    validate_public_schema,
    validate_schema_instance,
)
from app.modules.api_capability.domain.contracts import content_hash
from app.modules.api_capability.domain.ones_work_item_search import (
    ones_work_item_search_template,
)
from app.modules.api_capability.infrastructure import (
    ApiCapabilityRepository,
    ApiConnectionRepository,
    RestrictedHttpJsonClient,
    validate_relative_path,
)
from app.modules.audit.application.audit_service import AuditService
from app.modules.identity.application.authorization import (
    AuthorizationEvaluator,
)
from app.modules.identity.infrastructure import (
    ExternalApiCredentialCipher,
    ExternalApiCredentialRepository,
    IdentityRepository,
)
from app.shared.exceptions import (
    AppError,
    NonRetryableExecutionError,
    NotFound,
)


CAPABILITY_FIELDS = frozenset(
    {
        "name",
        "description",
        "operation_semantics",
        "data_classification",
        "input_schema",
        "output_schema",
    }
)
HANDLER_FIELDS = frozenset({"method", "relative_path", "graphql_document"})


class ApiCapabilityService:
    def __init__(
        self,
        *,
        repository: ApiCapabilityRepository,
        connection_repository: ApiConnectionRepository,
        identity_repository: IdentityRepository,
        credential_repository: ExternalApiCredentialRepository,
        credential_cipher: ExternalApiCredentialCipher | None,
        authorization: AuthorizationEvaluator,
        audit_service: AuditService,
        http_client: RestrictedHttpJsonClient | None = None,
        mapping_compiler: MappingCompiler | None = None,
        mapping_interpreter: MappingInterpreter | None = None,
    ) -> None:
        self.repository = repository
        self.connection_repository = connection_repository
        self.identity_repository = identity_repository
        self.credential_repository = credential_repository
        self.credential_cipher = credential_cipher
        self.authorization = authorization
        self.audit_service = audit_service
        self.http_client = http_client or RestrictedHttpJsonClient()
        self.mapping_compiler = mapping_compiler or MappingCompiler()
        self.mapping_interpreter = mapping_interpreter or MappingInterpreter()

    def list(self, *, actor_id: str) -> list[dict[str, Any]]:
        self._require(actor_id, "read")
        rows = self.repository.database.execute("select id from api_capability order by identifier")
        return [self.repository.get(str(row["id"])) for row in rows]

    def get(
        self,
        capability_id: str,
        *,
        actor_id: str,
    ) -> dict[str, Any]:
        self._require(actor_id, "read")
        return self.repository.get(capability_id)

    def catalog(
        self,
        *,
        actor_id: str,
        selectable_only: bool = False,
    ) -> builtins.list[dict[str, Any]]:
        self._require(actor_id, "read")
        return self.repository.list_catalog(selectable_only=selectable_only)

    def create(
        self,
        *,
        actor_id: str,
        identifier: str,
        connection_revision_id: str,
        authentication_profile_revision_id: str,
        capability: dict[str, Any],
        handler: dict[str, Any],
        mapping_ast: dict[str, Any],
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self._require(actor_id, "manage")
        CapabilityIdentifier(identifier)
        normalized = self._normalize_draft(
            connection_revision_id=connection_revision_id,
            authentication_profile_revision_id=(authentication_profile_revision_id),
            capability=capability,
            handler=handler,
            mapping_ast=mapping_ast,
        )
        value = self.repository.create(
            identifier=identifier,
            name=str(normalized["capability"]["name"]),
            connection_revision_id=connection_revision_id,
            authentication_profile_revision_id=(authentication_profile_revision_id),
            capability=normalized["capability"],
            handler=normalized["handler"],
            mapping_ast=normalized["mapping_ast"],
            actor_id=actor_id,
        )
        self._audit(
            "api_capability.created",
            actor_id,
            value,
            correlation_id=correlation_id,
        )
        return value

    def initialize_ones_work_item_search(
        self,
        *,
        actor_id: str,
        connection_revision_id: str,
        authentication_profile_revision_id: str,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self._require(actor_id, "manage")
        template = ones_work_item_search_template()
        try:
            return self.repository.get_by_identifier(str(template["identifier"]))
        except NotFound:
            return self.create(
                actor_id=actor_id,
                identifier=str(template["identifier"]),
                connection_revision_id=connection_revision_id,
                authentication_profile_revision_id=(authentication_profile_revision_id),
                capability=dict(template["capability"]),
                handler=dict(template["handler"]),
                mapping_ast=dict(template["mapping_ast"]),
                correlation_id=correlation_id,
            )

    def save_draft(
        self,
        capability_id: str,
        *,
        actor_id: str,
        expected_revision: int,
        connection_revision_id: str,
        authentication_profile_revision_id: str,
        capability: dict[str, Any],
        handler: dict[str, Any],
        mapping_ast: dict[str, Any],
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self._require(actor_id, "manage")
        normalized = self._normalize_draft(
            connection_revision_id=connection_revision_id,
            authentication_profile_revision_id=(authentication_profile_revision_id),
            capability=capability,
            handler=handler,
            mapping_ast=mapping_ast,
        )
        value = self.repository.save_draft(
            capability_id,
            expected_revision=expected_revision,
            connection_revision_id=connection_revision_id,
            authentication_profile_revision_id=(authentication_profile_revision_id),
            capability=normalized["capability"],
            handler=normalized["handler"],
            mapping_ast=normalized["mapping_ast"],
            actor_id=actor_id,
        )
        self._audit(
            "api_capability.draft_saved",
            actor_id,
            value,
            correlation_id=correlation_id,
        )
        return value

    def test(
        self,
        capability_id: str,
        *,
        actor_id: str,
        draft_revision: int,
        draft_hash: str,
        agent_input: dict[str, Any],
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self._require(actor_id, "test")
        current, draft = self._matching_draft(
            capability_id,
            draft_revision=draft_revision,
            draft_hash=draft_hash,
        )
        result = self._execute_test(
            actor_id=actor_id,
            draft=draft,
            agent_input=agent_input,
        )
        self._audit(
            "api_capability.tested",
            actor_id,
            current,
            extra={"result_hash": content_hash(result["normalized_output"])},
            correlation_id=correlation_id,
        )
        return result

    def verify(
        self,
        capability_id: str,
        *,
        actor_id: str,
        draft_revision: int,
        draft_hash: str,
        agent_input: dict[str, Any],
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self._require(actor_id, "verify")
        current, draft = self._matching_draft(
            capability_id,
            draft_revision=draft_revision,
            draft_hash=draft_hash,
        )
        result = self._execute_test(
            actor_id=actor_id,
            draft=draft,
            agent_input=agent_input,
        )
        identity = self._current_identity(actor_id)
        evidence = self.repository.record_verification(
            capability_id,
            draft_revision=draft_revision,
            draft_hash=draft_hash,
            external_identity_id=str(identity["id"]),
            external_user_id=str(identity["external_subject_id"]),
            default_team_id=str(identity["metadata"]["default_team_id"]),
            actor_id=actor_id,
            status="PASSED",
            result_summary={
                "method": result["method"],
                "relative_path": result["relative_path"],
                "normalized_output_hash": content_hash(result["normalized_output"]),
            },
            result_hash=content_hash(result["normalized_output"]),
        )
        self._audit(
            "api_capability.verified",
            actor_id,
            current,
            correlation_id=correlation_id,
        )
        return {"verification": evidence, "preview": result}

    def publish(
        self,
        capability_id: str,
        *,
        actor_id: str,
        draft_revision: int,
        draft_hash: str,
        idempotency_key: str,
        release_note: str = "",
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self._require(actor_id, "publish")
        current, draft = self._matching_draft(
            capability_id,
            draft_revision=draft_revision,
            draft_hash=draft_hash,
        )
        compiled = self.mapping_compiler.compile(draft["mapping_ast"])
        release = self.repository.create_release(
            capability_id,
            draft_revision=draft_revision,
            draft_hash=draft_hash,
            idempotency_key=idempotency_key,
            compiled_plan=compiled,
            compiled_plan_hash=content_hash(compiled),
            actor_id=actor_id,
            release_note=release_note.strip(),
        )
        self._audit(
            "api_capability.published",
            actor_id,
            release,
            correlation_id=correlation_id,
        )
        return release

    def set_release_status(
        self,
        release_id: str,
        *,
        actor_id: str,
        status: str,
        reason: str = "",
        replacement_release_id: str = "",
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self._require(actor_id, "manage")
        release = self.repository.set_release_status(
            release_id,
            status=status,
            actor_id=actor_id,
            reason=reason,
            replacement_release_id=replacement_release_id,
        )
        self._audit(
            "api_capability.release_status_changed",
            actor_id,
            release,
            correlation_id=correlation_id,
        )
        return release

    def copy_release_to_draft(
        self,
        release_id: str,
        *,
        actor_id: str,
        expected_revision: int,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self._require(actor_id, "manage")
        value = self.repository.copy_release_to_draft(
            release_id,
            expected_revision=expected_revision,
            actor_id=actor_id,
        )
        self._audit(
            "api_capability.release_copied",
            actor_id,
            value,
            correlation_id=correlation_id,
        )
        return value

    @staticmethod
    def classify_change(
        before: dict[str, Any],
        after: dict[str, Any],
    ) -> str:
        before_capability = before["capability"]
        after_capability = after["capability"]
        if before_capability == after_capability:
            return "HANDLER_ONLY"
        public_fields = {"input_schema", "output_schema"}
        if any(
            before_capability.get(field) != after_capability.get(field) for field in public_fields
        ):
            return "PUBLIC_SCHEMA"
        return "BUSINESS_SEMANTICS"

    def _normalize_draft(
        self,
        *,
        connection_revision_id: str,
        authentication_profile_revision_id: str,
        capability: dict[str, Any],
        handler: dict[str, Any],
        mapping_ast: dict[str, Any],
    ) -> dict[str, Any]:
        if set(capability) != CAPABILITY_FIELDS:
            raise _draft_error("Capability definition fields are invalid")
        if set(handler) != HANDLER_FIELDS:
            raise _draft_error("Handler fields are invalid")
        if capability.get("operation_semantics") != "QUERY":
            raise _draft_error("operation_semantics must be QUERY")
        if capability.get("data_classification") != "INTERNAL":
            raise _draft_error("data_classification must be INTERNAL")
        name = str(capability.get("name") or "").strip()
        description = str(capability.get("description") or "").strip()
        if not name or len(name) > 120 or not description or len(description) > 2000:
            raise _draft_error("Capability name or description is invalid")
        input_schema = validate_public_schema(
            capability["input_schema"],
            label="input_schema",
        )
        output_schema = validate_public_schema(
            capability["output_schema"],
            label="output_schema",
        )
        normalized_handler = _normalize_handler(handler)
        compiled = self.mapping_compiler.compile(mapping_ast)
        normalized_mapping = {
            "schema_version": 1,
            "request": compiled["request_plan"],
            "response": compiled["response_plan"],
        }
        connection = self.connection_repository.get_revision(connection_revision_id)
        if str(connection["status"]) != "PUBLISHED":
            raise _draft_error("Connection Revision is not published")
        if (
            str(connection["authentication_profile_revision_id"])
            != authentication_profile_revision_id
            or str(connection["authentication_status"]) != "PUBLISHED"
        ):
            raise _draft_error("Authentication Profile Revision does not match Connection")
        return {
            "capability": {
                "name": name,
                "description": description,
                "operation_semantics": "QUERY",
                "data_classification": "INTERNAL",
                "input_schema": input_schema,
                "output_schema": output_schema,
            },
            "handler": normalized_handler,
            "mapping_ast": normalized_mapping,
        }

    def _execute_test(
        self,
        *,
        actor_id: str,
        draft: dict[str, Any],
        agent_input: dict[str, Any],
    ) -> dict[str, Any]:
        capability = draft["capability"]
        validate_schema_instance(
            capability["input_schema"],
            agent_input,
            label="input",
        )
        connection = self.connection_repository.get_revision(str(draft["connection_revision_id"]))
        if str(connection["status"]) != "PUBLISHED":
            raise _draft_error("Connection Revision is unavailable")
        identity = self._current_identity(actor_id)
        credential = self.credential_repository.get_current_public(user_id=actor_id)
        if str(credential["connection_revision_id"]) != str(connection["id"]) or str(
            credential["external_identity_id"]
        ) != str(identity["id"]):
            raise NonRetryableExecutionError(
                "Current ONES binding does not match Connection Revision",
                safe_message="请使用当前 Connection Revision 重新绑定 ONES",
                error_code="credential_connection_mismatch",
            )
        cipher = self._require_cipher()
        encrypted = self.credential_repository.get_current_encrypted(user_id=actor_id)
        token = cipher.decrypt(
            ciphertext=encrypted.ciphertext,
            key_id=encrypted.key_id,
        )
        system_context = {
            "external_user_id": identity["external_subject_id"],
            "default_team_id": identity["metadata"]["default_team_id"],
        }
        compiled = self.mapping_compiler.compile(draft["mapping_ast"])
        request_value = self.mapping_interpreter.execute(
            compiled["request_plan"],
            agent_input=agent_input,
            system_context=system_context,
        )
        query, body = _mapped_request(request_value)
        handler = draft["handler"]
        preview_body = body
        request_body = body
        graphql_document = str(handler.get("graphql_document") or "")
        if graphql_document:
            request_body = {
                "query": graphql_document,
                "variables": body,
            }
            preview_body = request_body
        profile = AuthenticationProfileV1(connection["authentication"])
        preview = {
            "method": handler["method"],
            "relative_path": handler["relative_path"],
            "query": query,
            "body": preview_body,
        }
        try:
            response = self.http_client.request(
                connection=connection,
                method=str(handler["method"]),
                relative_path=str(handler["relative_path"]),
                query=query,
                body=request_body if handler["method"] == "POST" else None,
                authentication_header=profile.authentication_header(token),
            )
        except AppError as exc:
            if exc.error_code == "external_api_unauthorized":
                self.credential_repository.set_status(
                    user_id=actor_id,
                    status="INVALID",
                    error_code=exc.error_code,
                )
            raise
        normalized_output = self.mapping_interpreter.execute(
            compiled["response_plan"],
            agent_input=agent_input,
            system_context=system_context,
            response=response.payload,
        )
        validate_schema_instance(
            capability["output_schema"],
            normalized_output,
            label="output",
        )
        return {**preview, "normalized_output": normalized_output}

    def _matching_draft(
        self,
        capability_id: str,
        *,
        draft_revision: int,
        draft_hash: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        current = self.repository.get(capability_id)
        draft = current["draft"]
        if (
            int(draft["draft_revision"]) != draft_revision
            or str(draft["content_hash"]) != draft_hash
        ):
            raise NonRetryableExecutionError(
                "Capability Draft revision conflict",
                safe_message="Capability 草稿已变化，请刷新后重试",
                error_code="revision_conflict",
            )
        return current, draft

    def _current_identity(self, user_id: str) -> dict[str, Any]:
        identities = [
            item
            for item in self.identity_repository.list_external_identities(user_id)
            if item["provider"] == "ones" and item["status"] == "enabled"
        ]
        if len(identities) != 1:
            raise NonRetryableExecutionError(
                "Current user has no unique active ONES identity",
                safe_message="请先完成本人 ONES 绑定",
                error_code="ones_binding_required",
            )
        identity = identities[0]
        metadata = identity["metadata"]
        if not metadata.get("default_team_id"):
            raise NonRetryableExecutionError(
                "Current ONES identity has no default Team",
                safe_message="请重新验证 ONES 并选择默认 Team",
                error_code="ones_default_team_required",
            )
        return identity

    def _require_cipher(self) -> ExternalApiCredentialCipher:
        if self.credential_cipher is None:
            raise NonRetryableExecutionError(
                "External credential cipher is unavailable",
                safe_message="ONES 凭据不可用，请重新绑定",
                error_code="external_credential_encryption_unavailable",
            )
        return self.credential_cipher

    def _require(self, actor_id: str, action: str) -> None:
        self.authorization.require(
            user_id=actor_id,
            resource_type="api_capability",
            resource_code="*",
            action=action,
        )

    def _audit(
        self,
        event_type: str,
        actor_id: str,
        value: dict[str, Any],
        *,
        extra: dict[str, Any] | None = None,
        correlation_id: str = "",
    ) -> None:
        self.audit_service.record(
            event_type,
            status="SUCCEEDED",
            summary=event_type,
            actor_id=actor_id,
            payload={
                "actor_id": actor_id,
                "capability_id": str(value.get("capability_id") or value.get("id") or ""),
                "revision": int(
                    value.get("release_revision")
                    or value.get("revision")
                    or (value.get("draft") or {}).get("draft_revision")
                    or 0
                ),
                "content_hash": str(
                    value.get("config_hash")
                    or value.get("content_hash")
                    or (value.get("draft") or {}).get("content_hash")
                    or ""
                ),
                "result": "succeeded",
                "correlation_id": correlation_id,
                **(extra or {}),
            },
        )


def _normalize_handler(value: dict[str, Any]) -> dict[str, Any]:
    method = str(value.get("method") or "").upper()
    if method not in {"GET", "POST"}:
        raise _draft_error("Handler method must be GET or POST")
    relative_path = validate_relative_path(str(value.get("relative_path") or ""))
    graphql_document = str(value.get("graphql_document") or "").strip()
    if graphql_document:
        if method != "POST":
            raise _draft_error("GraphQL Handler must use POST")
        compact = re.sub(r"#[^\n]*", "", graphql_document).strip()
        if re.search(r"\bmutation\b", compact, flags=re.IGNORECASE):
            raise _draft_error("GraphQL mutation is forbidden")
        operations = re.findall(
            r"\b(query|mutation|subscription)\b",
            compact,
            flags=re.IGNORECASE,
        )
        if len(operations) != 1 or operations[0].lower() != "query":
            raise _draft_error("GraphQL document must contain exactly one query operation")
    return {
        "method": method,
        "relative_path": relative_path,
        "graphql_document": graphql_document,
    }


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


def _draft_error(reason: str) -> NonRetryableExecutionError:
    return NonRetryableExecutionError(
        f"Invalid API Capability Draft: {reason}",
        safe_message="API Capability Draft 配置无效",
        error_code="capability_draft_invalid",
    )
