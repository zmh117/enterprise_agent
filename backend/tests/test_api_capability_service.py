from __future__ import annotations

import json
from typing import Any

import pytest

from app.modules.api_capability.application import ApiCapabilityService
from app.modules.api_capability.domain import (
    MappingCompiler,
    MappingInterpreter,
    ONES_WORK_ITEM_SEARCH_GRAPHQL,
    ones_work_item_search_template,
    validate_public_schema,
    validate_schema_instance,
)
from app.modules.api_capability.infrastructure import (
    ApiCapabilityRepository,
    ApiConnectionRepository,
    HttpJsonResponse,
)
from app.modules.identity.infrastructure import (
    ExternalApiCredentialCipher,
    ExternalApiCredentialRepository,
    IdentityRepository,
)
from app.shared.database import Database, default_migrations_dir
from app.shared.exceptions import NonRetryableExecutionError
from app.shared.migrations import Migrator


ACTOR_ID = "api-capability-admin"
NOW = "2026-07-31T00:00:00+00:00"


def _authentication_profile() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "login": {
            "method": "POST",
            "relative_path": "/project/api/project/auth/login",
            "email_field": "email",
            "password_field": "password",
        },
        "extract": {
            "token_path": "$.user.token",
            "user_id_path": "$.user.uuid",
            "display_name_path": "$.user.name",
            "teams_path": "$.teams",
            "team_id_field": "uuid",
            "team_name_field": "name",
        },
        "inject": {
            "header_name": "Ones-Auth-Token",
            "value_prefix": "",
        },
    }


def _input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "keyword": {
                "type": "string",
                "minLength": 1,
                "maxLength": 200,
            },
            "issue_type": {
                "type": "string",
                "enum": ["demand", "task", "defect"],
                "default": "task",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 50,
                "default": 20,
            },
        },
        "required": ["keyword"],
        "additionalProperties": False,
    }


def _output_schema() -> dict[str, Any]:
    item = {
        "type": "object",
        "properties": {
            "number": {"type": "string", "maxLength": 100},
            "name": {"type": "string", "maxLength": 500},
            "type": {"type": "string", "maxLength": 50},
        },
        "required": ["number", "name", "type"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": item,
                "maxItems": 50,
            },
            "total": {"type": "integer", "minimum": 0},
            "truncated": {"type": "boolean"},
        },
        "required": ["items", "total", "truncated"],
        "additionalProperties": False,
    }


def _mapping_ast() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "request": {
            "op": "object",
            "fields": {
                "body": {
                    "op": "object",
                    "fields": {
                        "keyword": {
                            "op": "source",
                            "source": "AGENT_INPUT",
                            "path": "$.keyword",
                        },
                        "issue_type": {
                            "op": "default",
                            "value": {
                                "op": "source",
                                "source": "AGENT_INPUT",
                                "path": "$.issue_type",
                            },
                            "default": "task",
                        },
                        "limit": {
                            "op": "default",
                            "value": {
                                "op": "source",
                                "source": "AGENT_INPUT",
                                "path": "$.limit",
                            },
                            "default": 20,
                        },
                        "user_uuid": {
                            "op": "source",
                            "source": "SYSTEM_CONTEXT",
                            "path": "$.external_user_id",
                        },
                        "team_uuid": {
                            "op": "source",
                            "source": "SYSTEM_CONTEXT",
                            "path": "$.default_team_id",
                        },
                    },
                },
                "query": {"op": "object", "fields": {}},
            },
        },
        "response": {
            "op": "object",
            "fields": {
                "items": {
                    "op": "array_map",
                    "source": {
                        "op": "source",
                        "source": "RESPONSE",
                        "path": "$.data.search.nodes",
                    },
                    "item": {
                        "op": "object",
                        "fields": {
                            "name": {
                                "op": "source",
                                "source": "RESPONSE",
                                "path": "$.name",
                            },
                            "number": {
                                "op": "source",
                                "source": "RESPONSE",
                                "path": "$.number",
                            },
                            "type": {
                                "op": "source",
                                "source": "RESPONSE",
                                "path": "$.type",
                            },
                        },
                    },
                },
                "total": {
                    "op": "convert",
                    "value": {
                        "op": "source",
                        "source": "RESPONSE",
                        "path": "$.data.search.total",
                    },
                    "to": "integer",
                },
                "truncated": {
                    "op": "source",
                    "source": "CONSTANT",
                    "value": False,
                },
            },
        },
    }


class AllowAuthorization:
    def require(self, **_: Any) -> None:
        return None


class RecordingAudit:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def record(self, event_type: str, **values: Any) -> str:
        self.events.append({"event_type": event_type, **values})
        return f"audit-{len(self.events)}"


class CapabilityHttpClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def request(self, **values: Any) -> HttpJsonResponse:
        self.calls.append(values)
        return HttpJsonResponse(
            payload={
                "data": {
                    "search": {
                        "nodes": [
                            {
                                "number": "W-1",
                                "name": "Fix defect",
                                "type": "defect",
                                "private": "must-not-pass-mapping",
                            }
                        ],
                        "total": "1",
                    }
                }
            },
            status=200,
            duration_ms=1,
            response_size=256,
        )


@pytest.fixture
def database() -> Database:
    value = Database("sqlite:///:memory:")
    Migrator(
        value,
        default_migrations_dir(),
        migrator_build="api-capability-service-test",
    ).run()
    value.execute(
        """
        insert into app_user
          (id, username, display_name, status, created_at, updated_at)
        values (?, 'api-capability-admin', 'Capability Admin',
                'enabled', ?, ?)
        """,
        (ACTOR_ID, NOW, NOW),
    )
    try:
        yield value
    finally:
        value.close()


def _published_connection(database: Database) -> dict[str, Any]:
    repository = ApiConnectionRepository(database)
    connection = repository.create(
        code="ones-capability",
        name="ONES Capability",
        provider="ones",
        origin={
            "scheme": "https",
            "host": "ones.example.test",
            "port": 443,
        },
        authentication=_authentication_profile(),
        actor_id=ACTOR_ID,
    )
    draft = connection["draft"]
    repository.record_verification(
        str(connection["id"]),
        draft_revision=int(draft["draft_revision"]),
        draft_hash=str(draft["content_hash"]),
        actor_id=ACTOR_ID,
        status="PASSED",
        checks={"login": "passed"},
    )
    return repository.publish(
        str(connection["id"]),
        draft_revision=int(draft["draft_revision"]),
        draft_hash=str(draft["content_hash"]),
        actor_id=ACTOR_ID,
    )


def _bind_actor(
    database: Database,
    connection_revision_id: str,
    cipher: ExternalApiCredentialCipher,
) -> None:
    repository = ExternalApiCredentialRepository(database)
    challenge = repository.create_challenge(
        user_id=ACTOR_ID,
        connection_revision_id=connection_revision_id,
        external_user_id="ones-capability-user",
        display_name="Capability User",
        teams=[{"id": "team-a", "name": "Team A"}],
        encrypted_token=cipher.encrypt("actor-personal-token"),
        expires_at="2099-01-01T00:00:00+00:00",
    )
    repository.consume_challenge(
        str(challenge["id"]),
        user_id=ACTOR_ID,
        connection_revision_id=connection_revision_id,
        default_team_id="team-a",
    )


def _service(
    database: Database,
) -> tuple[ApiCapabilityService, dict[str, Any], CapabilityHttpClient, RecordingAudit]:
    connection = _published_connection(database)
    cipher = ExternalApiCredentialCipher("capability-service-test-key")
    _bind_actor(database, str(connection["id"]), cipher)
    http = CapabilityHttpClient()
    audit = RecordingAudit()
    return (
        ApiCapabilityService(
            repository=ApiCapabilityRepository(database),
            connection_repository=ApiConnectionRepository(database),
            identity_repository=IdentityRepository(database),
            credential_repository=ExternalApiCredentialRepository(database),
            credential_cipher=cipher,
            authorization=AllowAuthorization(),  # type: ignore[arg-type]
            audit_service=audit,  # type: ignore[arg-type]
            http_client=http,  # type: ignore[arg-type]
        ),
        connection,
        http,
        audit,
    )


def _create_capability(
    service: ApiCapabilityService,
    connection: dict[str, Any],
) -> dict[str, Any]:
    return service.create(
        actor_id=ACTOR_ID,
        identifier="cap__ones__work_item__search",
        connection_revision_id=str(connection["id"]),
        authentication_profile_revision_id=str(connection["authentication_profile_revision_id"]),
        capability={
            "name": "Search ONES work items",
            "description": "Search work items visible to the current ONES user.",
            "operation_semantics": "QUERY",
            "data_classification": "INTERNAL",
            "input_schema": _input_schema(),
            "output_schema": _output_schema(),
        },
        handler={
            "method": "POST",
            "relative_path": "/project/api/project/graphql",
            "graphql_document": (
                "query Search($keyword: String!) "
                "{ search(keyword: $keyword) { total nodes { number name type } } }"
            ),
        },
        mapping_ast=_mapping_ast(),
    )


def test_public_schema_rejects_system_fields_unknown_keys_and_invalid_defaults() -> None:
    invalid_system = _input_schema()
    invalid_system["properties"]["team_id"] = {"type": "string"}
    with pytest.raises(NonRetryableExecutionError) as system:
        validate_public_schema(invalid_system, label="input_schema")
    assert system.value.error_code == "capability_schema_invalid"

    unknown = _input_schema()
    unknown["properties"]["keyword"]["pattern"] = ".*"
    with pytest.raises(NonRetryableExecutionError):
        validate_public_schema(unknown, label="input_schema")

    invalid_default = _input_schema()
    invalid_default["properties"]["limit"]["default"] = 100
    with pytest.raises(NonRetryableExecutionError):
        validate_public_schema(invalid_default, label="input_schema")


def test_ones_search_template_has_fixed_public_and_system_boundaries(
    database: Database,
) -> None:
    service, connection, _, _ = _service(database)
    initialized = service.initialize_ones_work_item_search(
        actor_id=ACTOR_ID,
        connection_revision_id=str(connection["id"]),
        authentication_profile_revision_id=str(connection["authentication_profile_revision_id"]),
    )
    repeated = service.initialize_ones_work_item_search(
        actor_id=ACTOR_ID,
        connection_revision_id=str(connection["id"]),
        authentication_profile_revision_id=str(connection["authentication_profile_revision_id"]),
    )
    assert repeated["id"] == initialized["id"]
    draft = initialized["draft"]
    template = ones_work_item_search_template()
    assert initialized["identifier"] == "cap__ones__work_item__search"
    assert set(draft["capability"]["input_schema"]["properties"]) == {
        "keyword",
        "issue_type",
        "limit",
    }
    assert draft["capability"]["operation_semantics"] == "QUERY"
    assert draft["capability"]["data_classification"] == "INTERNAL"
    assert draft["handler"]["graphql_document"] == (ONES_WORK_ITEM_SEARCH_GRAPHQL)
    serialized_input = json.dumps(draft["capability"]["input_schema"]).lower()
    for system_field in (
        "team_id",
        "user_id",
        "token",
        "origin",
        "path",
        "query",
        "document",
    ):
        assert system_field not in serialized_input
    compiled = MappingCompiler().compile(template["mapping_ast"])
    request = MappingInterpreter().execute(
        compiled["request_plan"],
        agent_input={
            "keyword": "defect",
            "issue_type": "defect",
            "limit": 10,
        },
        system_context={
            "external_user_id": "user-a",
            "default_team_id": "team-a",
        },
    )
    assert request["body"]["user_id"] == "user-a"
    assert request["body"]["team_id"] == "team-a"

    invalid = ones_work_item_search_template()
    invalid["handler"]["graphql_document"] = 'mutation DeleteWorkItem { deleteWorkItem(id: "1") }'
    with pytest.raises(NonRetryableExecutionError):
        service.create(
            actor_id=ACTOR_ID,
            identifier="cap__ones__work_item__delete",
            connection_revision_id=str(connection["id"]),
            authentication_profile_revision_id=str(
                connection["authentication_profile_revision_id"]
            ),
            capability=invalid["capability"],
            handler=invalid["handler"],
            mapping_ast=invalid["mapping_ast"],
        )


@pytest.mark.parametrize(
    "operation",
    ["condition", "filter", "concat", "date", "regex", "function", "script"],
)
def test_mapping_compiler_rejects_non_whitelisted_operations(
    operation: str,
) -> None:
    mapping = _mapping_ast()
    mapping["request"] = {"op": operation}
    with pytest.raises(NonRetryableExecutionError) as captured:
        MappingCompiler().compile(mapping)
    assert captured.value.error_code == "mapping_ast_invalid"


def test_mapping_interpreter_projects_arrays_defaults_and_scalar_conversion() -> None:
    compiled = MappingCompiler().compile(_mapping_ast())
    request = MappingInterpreter().execute(
        compiled["request_plan"],
        agent_input={"keyword": "defect"},
        system_context={
            "external_user_id": "user-a",
            "default_team_id": "team-a",
        },
    )
    assert request["body"] == {
        "issue_type": "task",
        "keyword": "defect",
        "limit": 20,
        "team_uuid": "team-a",
        "user_uuid": "user-a",
    }
    response = MappingInterpreter().execute(
        compiled["response_plan"],
        agent_input={},
        system_context={},
        response={
            "data": {
                "search": {
                    "nodes": [{"number": "1", "name": "A", "type": "task"}],
                    "total": "1",
                }
            }
        },
    )
    assert response == {
        "items": [{"name": "A", "number": "1", "type": "task"}],
        "total": 1,
        "truncated": False,
    }
    with pytest.raises(NonRetryableExecutionError) as conversion:
        MappingInterpreter().execute(
            {
                "op": "convert",
                "value": {
                    "op": "source",
                    "source": "AGENT_INPUT",
                    "path": "$.value",
                },
                "to": "integer",
            },
            agent_input={"value": "not-an-integer"},
            system_context={},
        )
    assert conversion.value.error_code == "mapping_execution_failed"
    with pytest.raises(NonRetryableExecutionError) as array:
        MappingInterpreter().execute(
            {
                "op": "array_map",
                "source": {
                    "op": "source",
                    "source": "AGENT_INPUT",
                    "path": "$.value",
                },
                "item": {
                    "op": "source",
                    "source": "AGENT_INPUT",
                    "path": "$",
                },
            },
            agent_input={"value": "not-an-array"},
            system_context={},
        )
    assert array.value.error_code == "mapping_execution_failed"


def test_capability_test_verify_publish_and_preview_exclude_authentication(
    database: Database,
) -> None:
    service, connection, http, audit = _service(database)
    capability = _create_capability(service, connection)
    draft = capability["draft"]
    preview = service.test(
        str(capability["id"]),
        actor_id=ACTOR_ID,
        draft_revision=int(draft["draft_revision"]),
        draft_hash=str(draft["content_hash"]),
        agent_input={"keyword": "defect", "issue_type": "defect", "limit": 10},
    )
    assert preview["method"] == "POST"
    assert preview["relative_path"] == "/project/api/project/graphql"
    assert preview["body"]["variables"]["team_uuid"] == "team-a"
    assert preview["normalized_output"] == {
        "items": [{"name": "Fix defect", "number": "W-1", "type": "defect"}],
        "total": 1,
        "truncated": False,
    }
    serialized_preview = json.dumps(preview).lower()
    assert "actor-personal-token" not in serialized_preview
    assert "ones-auth-token" not in serialized_preview
    assert "private" not in serialized_preview
    assert http.calls[0]["authentication_header"] == (
        "Ones-Auth-Token",
        "actor-personal-token",
    )
    verified = service.verify(
        str(capability["id"]),
        actor_id=ACTOR_ID,
        draft_revision=int(draft["draft_revision"]),
        draft_hash=str(draft["content_hash"]),
        agent_input={"keyword": "defect"},
    )
    assert "result_summary_json" in verified["verification"]
    release = service.publish(
        str(capability["id"]),
        actor_id=ACTOR_ID,
        draft_revision=int(draft["draft_revision"]),
        draft_hash=str(draft["content_hash"]),
        idempotency_key="capability-publish-v1",
        release_note="Internal ONES search",
        correlation_id="capability-correlation-1",
    )
    repeated = service.publish(
        str(capability["id"]),
        actor_id=ACTOR_ID,
        draft_revision=int(draft["draft_revision"]),
        draft_hash=str(draft["content_hash"]),
        idempotency_key="capability-publish-v1",
    )
    assert repeated["id"] == release["id"]
    audit_text = json.dumps(audit.events).lower()
    assert "actor-personal-token" not in audit_text
    assert "private" not in audit_text
    published_audit = next(
        item for item in audit.events if item["event_type"] == "api_capability.published"
    )
    assert published_audit["payload"]["correlation_id"] == ("capability-correlation-1")
    assert "capability" not in published_audit["payload"]
    assert "handler" not in published_audit["payload"]
    assert "mapping_ast" not in published_audit["payload"]


def test_unverified_or_drifted_draft_cannot_publish_and_copy_is_new_draft(
    database: Database,
) -> None:
    service, connection, _, _ = _service(database)
    capability = _create_capability(service, connection)
    draft = capability["draft"]
    with pytest.raises(NonRetryableExecutionError) as unverified:
        service.publish(
            str(capability["id"]),
            actor_id=ACTOR_ID,
            draft_revision=int(draft["draft_revision"]),
            draft_hash=str(draft["content_hash"]),
            idempotency_key="must-not-publish",
        )
    assert unverified.value.error_code == "capability_not_verified"
    service.verify(
        str(capability["id"]),
        actor_id=ACTOR_ID,
        draft_revision=int(draft["draft_revision"]),
        draft_hash=str(draft["content_hash"]),
        agent_input={"keyword": "issue"},
    )
    release = service.publish(
        str(capability["id"]),
        actor_id=ACTOR_ID,
        draft_revision=int(draft["draft_revision"]),
        draft_hash=str(draft["content_hash"]),
        idempotency_key="copy-source-v1",
    )
    saved = service.save_draft(
        str(capability["id"]),
        actor_id=ACTOR_ID,
        expected_revision=int(draft["draft_revision"]),
        connection_revision_id=str(draft["connection_revision_id"]),
        authentication_profile_revision_id=str(draft["authentication_profile_revision_id"]),
        capability={
            **draft["capability"],
            "description": "Changed business meaning.",
        },
        handler=draft["handler"],
        mapping_ast=draft["mapping_ast"],
    )
    with pytest.raises(NonRetryableExecutionError) as drift:
        service.publish(
            str(capability["id"]),
            actor_id=ACTOR_ID,
            draft_revision=int(draft["draft_revision"]),
            draft_hash=str(draft["content_hash"]),
            idempotency_key="stale-publish",
        )
    assert drift.value.error_code == "revision_conflict"
    copied = service.copy_release_to_draft(
        str(release["id"]),
        actor_id=ACTOR_ID,
        expected_revision=int(saved["draft"]["draft_revision"]),
    )
    assert copied["draft"]["capability"]["description"] == (draft["capability"]["description"])
    assert (
        ApiCapabilityService.classify_change(
            {"capability": draft["capability"]},
            {"capability": draft["capability"]},
        )
        == "HANDLER_ONLY"
    )
    assert (
        ApiCapabilityService.classify_change(
            {"capability": draft["capability"]},
            {
                "capability": {
                    **draft["capability"],
                    "input_schema": {
                        **draft["capability"]["input_schema"],
                        "title": "Changed",
                    },
                }
            },
        )
        == "PUBLIC_SCHEMA"
    )


def test_schema_validation_is_all_or_nothing() -> None:
    schema = validate_public_schema(_output_schema(), label="output_schema")
    with pytest.raises(NonRetryableExecutionError) as captured:
        validate_schema_instance(
            schema,
            {
                "items": [{"number": "1", "name": "A"}],
                "total": 1,
                "truncated": False,
            },
            label="output",
        )
    assert captured.value.error_code == "capability_schema_validation_failed"


def test_release_lifecycle_requires_reason_and_protects_publication_dependency(
    database: Database,
) -> None:
    service, connection, _, _ = _service(database)
    capability = _create_capability(service, connection)
    draft = capability["draft"]
    service.verify(
        str(capability["id"]),
        actor_id=ACTOR_ID,
        draft_revision=int(draft["draft_revision"]),
        draft_hash=str(draft["content_hash"]),
        agent_input={"keyword": "issue"},
    )
    release = service.publish(
        str(capability["id"]),
        actor_id=ACTOR_ID,
        draft_revision=int(draft["draft_revision"]),
        draft_hash=str(draft["content_hash"]),
        idempotency_key="release-lifecycle-v1",
    )
    with pytest.raises(NonRetryableExecutionError):
        service.set_release_status(
            str(release["id"]),
            actor_id=ACTOR_ID,
            status="DEPRECATED",
        )
    deprecated = service.set_release_status(
        str(release["id"]),
        actor_id=ACTOR_ID,
        status="DEPRECATED",
        reason="Use a newer release",
    )
    assert deprecated["status"] == "DEPRECATED"
    active = service.set_release_status(
        str(release["id"]),
        actor_id=ACTOR_ID,
        status="ACTIVE",
    )
    assert active["status"] == "ACTIVE"
