from __future__ import annotations

import json
from typing import Any

import pytest

from app.modules.api_capability.application import (
    GovernedApiRuntimeExecutor,
    GovernedCapabilityReleaseResolver,
)
from app.modules.api_capability.domain import MappingCompiler
from app.modules.api_capability.domain.contracts import content_hash
from app.modules.api_capability.infrastructure import (
    ApiCapabilityRepository,
    ApiConnectionRepository,
    CapabilityPublicationRepository,
    GovernedApiExecutionRepository,
    HttpJsonResponse,
)
from app.modules.identity.infrastructure import (
    ExternalApiCredentialCipher,
    ExternalApiCredentialRepository,
    IdentityRepository,
)
from app.shared.database import Database, default_migrations_dir
from app.shared.exceptions import (
    NonRetryableExecutionError,
    RetryableExecutionError,
)
from app.shared.migrations import Migrator
from backend.tests.test_api_capability_service import (
    ACTOR_ID,
    NOW,
    _create_capability,
    _service,
)


@pytest.fixture
def database() -> Database:
    value = Database("sqlite:///:memory:")
    Migrator(
        value,
        default_migrations_dir(),
        migrator_build="governed-api-runtime-test",
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


class SequenceHttpClient:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    def request(self, **values: Any) -> HttpJsonResponse:
        self.calls.append(values)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _success_response(*, private: str = "raw-private-body") -> HttpJsonResponse:
    return HttpJsonResponse(
        payload={
            "data": {
                "search": {
                    "nodes": [
                        {
                            "number": "W-1",
                            "name": "Fix defect",
                            "type": "defect",
                            "private": private,
                        }
                    ],
                    "total": "1",
                }
            }
        },
        status=200,
        duration_ms=2,
        response_size=300,
    )


def _publication_parents(
    database: Any,
    release: dict[str, Any],
    *,
    include_in_application: bool = True,
) -> tuple[str, str]:
    database.execute(
        """
        insert into agent_definition
          (id, code, name, created_by, created_at, updated_at)
        values ('runtime-agent', 'runtime-agent', 'Runtime Agent', ?, ?, ?)
        """,
        (ACTOR_ID, NOW, NOW),
    )
    database.execute(
        """
        insert into agent_revision
          (id, agent_id, revision, status, config_json, config_hash,
           created_by, created_at, updated_at)
        values ('runtime-agent-revision', 'runtime-agent', 1, 'published',
                '{}', 'runtime-agent-hash', ?, ?, ?)
        """,
        (ACTOR_ID, NOW, NOW),
    )
    database.execute(
        """
        insert into agent_publication
          (id, agent_id, revision_id, revision, snapshot_json, config_hash,
           published_by, published_at)
        values ('runtime-agent-publication', 'runtime-agent',
                'runtime-agent-revision', 1, '{}', 'runtime-agent-hash', ?, ?)
        """,
        (ACTOR_ID, NOW),
    )
    database.execute(
        """
        insert into business_application
          (id, code, name, project_code, owner_user_id, created_by,
           created_at, updated_at)
        values ('runtime-application', 'runtime-application',
                'Runtime Application', 'default', ?, ?, ?, ?)
        """,
        (ACTOR_ID, ACTOR_ID, NOW, NOW),
    )
    database.execute(
        """
        insert into business_application_revision
          (id, application_id, revision, status, agent_publication_id,
           config_hash, created_by, created_at, updated_at)
        values ('runtime-application-revision', 'runtime-application',
                1, 'published', 'runtime-agent-publication',
                'runtime-application-hash', ?, ?, ?)
        """,
        (ACTOR_ID, NOW, NOW),
    )
    database.execute(
        """
        insert into business_application_publication
          (id, application_id, revision_id, revision, snapshot_json,
           config_hash, published_by, published_at)
        values ('runtime-application-publication', 'runtime-application',
                'runtime-application-revision', 1, '{}',
                'runtime-application-hash', ?, ?)
        """,
        (ACTOR_ID, NOW),
    )
    publication_repository = CapabilityPublicationRepository(database)
    publication_repository.freeze_agent_envelope(
        "runtime-agent-publication",
        release_ids=[str(release["id"])],
    )
    publication_repository.freeze_application_allowlist(
        "runtime-application-publication",
        agent_publication_id="runtime-agent-publication",
        release_ids=[str(release["id"])] if include_in_application else [],
    )
    return "runtime-agent-publication", "runtime-application-publication"


def _job_and_tool(
    database: Any,
    *,
    tool_call_id: str,
    agent_publication_id: str,
    application_publication_id: str,
) -> None:
    database.execute(
        """
        insert into agent_session
          (id, dingding_conversation_id, dingding_user_id, source,
           project_code, created_at, updated_at)
        values ('runtime-session', 'runtime-conversation', 'runtime-sender',
                'dingding', 'default', ?, ?)
        """,
        (NOW, NOW),
    )
    database.execute(
        """
        insert into agent_job
          (id, session_id, idempotency_key, user_id, project_code, source,
           user_message, status, internal_user_id, agent_publication_id,
           business_application_publication_id, created_at)
        values ('runtime-job', 'runtime-session', 'runtime-job-key', ?,
                'default', 'dingding', 'search', 'RUNNING', ?, ?, ?, ?)
        """,
        (
            ACTOR_ID,
            ACTOR_ID,
            agent_publication_id,
            application_publication_id,
            NOW,
        ),
    )
    database.execute(
        """
        insert into agent_tool_call
          (id, job_id, tool_name, request_payload, response_summary,
           status, created_at)
        values (?, 'runtime-job', 'cap__ones__work_item__search',
                '{}', '', 'RUNNING', ?)
        """,
        (tool_call_id, NOW),
    )
    identity = [
        item
        for item in IdentityRepository(database).list_external_identities(ACTOR_ID)
        if item["provider"] == "ones" and item["status"] == "enabled"
    ][0]
    GovernedApiExecutionRepository(database).freeze_external_subject(
        job_id="runtime-job",
        external_identity_id=str(identity["id"]),
        external_user_id=str(identity["external_subject_id"]),
        default_team_id=str(identity["metadata"]["default_team_id"]),
        binding_revision=int(identity["revision"]),
    )


def _runtime(
    database: Any,
    http: SequenceHttpClient,
    *,
    sleeps: list[float] | None = None,
) -> GovernedApiRuntimeExecutor:
    return GovernedApiRuntimeExecutor(
        resolver=GovernedCapabilityReleaseResolver(
            ApiCapabilityRepository(database),
            ApiConnectionRepository(database),
        ),
        execution_repository=GovernedApiExecutionRepository(database),
        identity_repository=IdentityRepository(database),
        credential_repository=ExternalApiCredentialRepository(database),
        credential_cipher=ExternalApiCredentialCipher("capability-service-test-key"),
        http_client=http,  # type: ignore[arg-type]
        sleeper=(sleeps.append if sleeps is not None else lambda _: None),
    )


def _released_runtime(
    database: Any,
    *,
    include_in_application: bool = True,
) -> tuple[dict[str, Any], str, str]:
    service, connection, _, _ = _service(database)
    capability = _create_capability(service, connection)
    draft = capability["draft"]
    service.verify(
        str(capability["id"]),
        actor_id=ACTOR_ID,
        draft_revision=int(draft["draft_revision"]),
        draft_hash=str(draft["content_hash"]),
        agent_input={"keyword": "defect"},
    )
    release = service.publish(
        str(capability["id"]),
        actor_id=ACTOR_ID,
        draft_revision=int(draft["draft_revision"]),
        draft_hash=str(draft["content_hash"]),
        idempotency_key="runtime-release-v1",
    )
    agent_publication_id, application_publication_id = _publication_parents(
        database,
        release,
        include_in_application=include_in_application,
    )
    _job_and_tool(
        database,
        tool_call_id="runtime-tool-call",
        agent_publication_id=agent_publication_id,
        application_publication_id=application_publication_id,
    )
    return release, agent_publication_id, application_publication_id


def _released_ones_template_runtime(
    database: Any,
) -> tuple[dict[str, Any], str, str]:
    service, connection, _, _ = _service(database)
    capability = service.initialize_ones_work_item_search(
        actor_id=ACTOR_ID,
        connection_revision_id=str(connection["id"]),
        authentication_profile_revision_id=str(connection["authentication_profile_revision_id"]),
    )
    draft = capability["draft"]
    repository = ApiCapabilityRepository(database)
    verification = repository.record_verification(
        str(capability["id"]),
        draft_revision=int(draft["draft_revision"]),
        draft_hash=str(draft["content_hash"]),
        external_identity_id=str(
            ExternalApiCredentialRepository(database).get_current_public(user_id=ACTOR_ID)[
                "external_identity_id"
            ]
        ),
        external_user_id="ones-capability-user",
        default_team_id="team-a",
        actor_id=ACTOR_ID,
        status="PASSED",
        result_summary={"contract": "ones-work-item-search-v1"},
    )
    compiled = MappingCompiler().compile(draft["mapping_ast"])
    release = repository.create_release(
        str(capability["id"]),
        draft_revision=int(draft["draft_revision"]),
        draft_hash=str(draft["content_hash"]),
        idempotency_key="ones-template-runtime-release-v1",
        compiled_plan=compiled,
        compiled_plan_hash=content_hash(compiled),
        actor_id=ACTOR_ID,
        release_note=str(verification["id"]),
    )
    agent_publication_id, application_publication_id = _publication_parents(database, release)
    _job_and_tool(
        database,
        tool_call_id="runtime-tool-call",
        agent_publication_id=agent_publication_id,
        application_publication_id=application_publication_id,
    )
    return release, agent_publication_id, application_publication_id


def _execute(
    runtime: GovernedApiRuntimeExecutor,
    release: dict[str, Any],
    agent_publication_id: str,
    application_publication_id: str,
) -> dict[str, Any]:
    return runtime.execute(
        job_id="runtime-job",
        tool_call_id="runtime-tool-call",
        user_id=ACTOR_ID,
        application_publication_id=application_publication_id,
        agent_publication_id=agent_publication_id,
        capability_release_id=str(release["id"]),
        identifier="cap__ones__work_item__search",
        agent_input={
            "keyword": "defect",
            "issue_type": "defect",
            "limit": 10,
        },
        correlation_id="runtime-correlation",
        timeout_seconds=10,
    )


def test_runtime_executes_exact_release_and_persists_only_safe_attempt_metadata(
    database: Any,
) -> None:
    release, agent_publication_id, application_publication_id = _released_runtime(database)
    http = SequenceHttpClient([_success_response()])
    result = _execute(
        _runtime(database, http),
        release,
        agent_publication_id,
        application_publication_id,
    )
    assert result == {
        "items": [{"name": "Fix defect", "number": "W-1", "type": "defect"}],
        "total": 1,
        "truncated": False,
    }
    assert http.calls[0]["body"]["variables"]["user_uuid"] == ("ones-capability-user")
    assert http.calls[0]["body"]["variables"]["team_uuid"] == "team-a"
    persisted = json.dumps(
        {
            "attempts": database.execute("select * from agent_tool_call_http_attempt"),
            "provenance": database.execute("select * from agent_tool_call_api_provenance"),
        }
    ).lower()
    assert "raw-private-body" not in persisted
    assert "actor-personal-token" not in persisted
    assert '\\"total\\":1' not in persisted


def test_ones_search_template_enforces_input_mapping_and_all_or_nothing_output(
    database: Any,
) -> None:
    release, agent_publication_id, application_publication_id = _released_ones_template_runtime(
        database
    )
    response = HttpJsonResponse(
        payload={
            "data": {
                "workItems": {
                    "items": [
                        {
                            "number": 900103,
                            "name": "Order status not refreshed",
                            "type": "defect",
                            "private": "must-not-pass",
                        }
                    ],
                    "total": 2,
                    "truncated": True,
                }
            }
        },
        status=200,
        duration_ms=2,
        response_size=300,
    )
    http = SequenceHttpClient([response])
    result = _execute(
        _runtime(database, http),
        release,
        agent_publication_id,
        application_publication_id,
    )
    assert result == {
        "items": [
            {
                "number": 900103,
                "name": "Order status not refreshed",
                "type": "defect",
            }
        ],
        "total": 2,
        "truncated": True,
    }
    assert http.calls[0]["relative_path"] == ("/project/api/project/items/graphql")
    assert http.calls[0]["body"]["variables"] == {
        "keyword": "defect",
        "issue_type": "defect",
        "limit": 10,
        "team_id": "team-a",
        "user_id": "ones-capability-user",
    }
    assert http.calls[0]["body"]["query"].startswith("query SearchWorkItems")

    with pytest.raises(NonRetryableExecutionError):
        _runtime(database, SequenceHttpClient([response])).execute(
            job_id="runtime-job",
            tool_call_id="runtime-tool-call",
            user_id=ACTOR_ID,
            application_publication_id=application_publication_id,
            agent_publication_id=agent_publication_id,
            capability_release_id=str(release["id"]),
            identifier="cap__ones__work_item__search",
            agent_input={
                "keyword": "defect",
                "issue_type": "defect",
                "limit": 51,
            },
            correlation_id="bad-input",
            timeout_seconds=10,
        )


def test_ones_search_template_rejects_partial_malformed_output(
    database: Any,
) -> None:
    release, agent_publication_id, application_publication_id = _released_ones_template_runtime(
        database
    )
    malformed = HttpJsonResponse(
        payload={
            "data": {
                "workItems": {
                    "items": [
                        {
                            "name": "Missing number",
                            "type": "defect",
                        }
                    ],
                    "total": 1,
                    "truncated": False,
                }
            }
        },
        status=200,
        duration_ms=2,
        response_size=200,
    )
    with pytest.raises(NonRetryableExecutionError) as captured:
        _execute(
            _runtime(database, SequenceHttpClient([malformed])),
            release,
            agent_publication_id,
            application_publication_id,
        )
    assert captured.value.error_code == "mapping_execution_failed"
    assert database.execute("select * from agent_tool_call_api_provenance") == []


def test_query_retries_at_most_twice_with_bounded_backoff(
    database: Any,
) -> None:
    release, agent_publication_id, application_publication_id = _released_runtime(database)
    retry = RetryableExecutionError(
        "temporary",
        safe_message="外部 API 暂时不可用",
        error_code="external_api_retryable_status",
        diagnostics={"http_status": 503},
    )
    http = SequenceHttpClient([retry, retry, _success_response()])
    sleeps: list[float] = []
    result = _execute(
        _runtime(database, http, sleeps=sleeps),
        release,
        agent_publication_id,
        application_publication_id,
    )
    assert result["total"] == 1
    assert sleeps == [0.1, 0.2]
    attempts = database.execute(
        """
        select attempt_no, status_class, http_status
          from agent_tool_call_http_attempt order by attempt_no
        """
    )
    assert attempts == [
        {
            "attempt_no": 1,
            "status_class": "RETRYABLE_FAILURE",
            "http_status": 503,
        },
        {
            "attempt_no": 2,
            "status_class": "RETRYABLE_FAILURE",
            "http_status": 503,
        },
        {
            "attempt_no": 3,
            "status_class": "SUCCEEDED",
            "http_status": 200,
        },
    ]


@pytest.mark.parametrize(
    ("status_code", "credential_status"),
    [(401, "INVALID"), (403, "ACTIVE")],
)
def test_401_invalidates_credential_while_403_preserves_it(
    database: Any,
    status_code: int,
    credential_status: str,
) -> None:
    release, agent_publication_id, application_publication_id = _released_runtime(database)
    error = NonRetryableExecutionError(
        "denied",
        safe_message="ONES 拒绝了当前操作",
        error_code=(
            "external_api_unauthorized" if status_code == 401 else "external_api_forbidden"
        ),
        diagnostics={"http_status": status_code},
    )
    with pytest.raises(NonRetryableExecutionError):
        _execute(
            _runtime(database, SequenceHttpClient([error])),
            release,
            agent_publication_id,
            application_publication_id,
        )
    credential = ExternalApiCredentialRepository(database).get_current_public(user_id=ACTOR_ID)
    assert credential["status"] == credential_status
    attempts = database.execute("select status_class from agent_tool_call_http_attempt")
    assert attempts == [
        {"status_class": ("CREDENTIAL_INVALID" if status_code == 401 else "FORBIDDEN")}
    ]


def test_runtime_fails_when_application_did_not_select_release(
    database: Any,
) -> None:
    release, agent_publication_id, application_publication_id = _released_runtime(
        database, include_in_application=False
    )
    http = SequenceHttpClient([_success_response()])
    with pytest.raises(NonRetryableExecutionError) as captured:
        _execute(
            _runtime(database, http),
            release,
            agent_publication_id,
            application_publication_id,
        )
    assert captured.value.error_code == "capability_not_allowed"
    assert http.calls == []


def test_runtime_fails_closed_after_default_team_change_but_allows_token_rotation(
    database: Any,
) -> None:
    release, agent_publication_id, application_publication_id = _released_runtime(database)
    credential_repository = ExternalApiCredentialRepository(database)
    credential = credential_repository.get_current_public(user_id=ACTOR_ID)
    identity = IdentityRepository(database).get_external_identity(
        str(credential["external_identity_id"])
    )
    cipher = ExternalApiCredentialCipher("capability-service-test-key")
    rotation = credential_repository.create_challenge(
        user_id=ACTOR_ID,
        connection_revision_id=str(credential["connection_revision_id"]),
        external_user_id=str(identity["external_subject_id"]),
        display_name=str(identity["display_name"]),
        teams=[{"id": "team-a", "name": "Team A"}],
        encrypted_token=cipher.encrypt("rotated-token"),
        expires_at="2099-01-01T00:00:00+00:00",
    )
    credential_repository.consume_challenge(
        str(rotation["id"]),
        user_id=ACTOR_ID,
        connection_revision_id=str(credential["connection_revision_id"]),
        default_team_id="team-a",
    )
    rotated_http = SequenceHttpClient([_success_response()])
    assert (
        _execute(
            _runtime(database, rotated_http),
            release,
            agent_publication_id,
            application_publication_id,
        )["total"]
        == 1
    )
    assert rotated_http.calls[0]["authentication_header"][1] == "rotated-token"

    metadata = {
        "verification_method": "credentials",
        "team_uuids": ["team-a", "team-b"],
        "default_team_id": "team-b",
    }
    database.execute(
        """
        update user_external_identity
           set metadata_json = ?, revision = revision + 1
         where id = ?
        """,
        (json.dumps(metadata), identity["id"]),
    )
    with pytest.raises(NonRetryableExecutionError) as changed:
        _execute(
            _runtime(database, SequenceHttpClient([_success_response()])),
            release,
            agent_publication_id,
            application_publication_id,
        )
    assert changed.value.error_code == "external_subject_changed"


def test_unknown_compiled_plan_version_and_disabled_release_fail_closed(
    database: Any,
) -> None:
    release, agent_publication_id, application_publication_id = _released_runtime(database)
    plan = database.execute_one(
        "select plan_json from api_compiled_mapping_plan where id = ?",
        (release["mapping_plan_id"],),
    )
    payload = json.loads(str(plan["plan_json"]))
    payload["schema_version"] = 2
    database.execute(
        "update api_compiled_mapping_plan set plan_json = ? where id = ?",
        (json.dumps(payload), release["mapping_plan_id"]),
    )
    with pytest.raises(NonRetryableExecutionError) as unknown:
        _execute(
            _runtime(database, SequenceHttpClient([_success_response()])),
            release,
            agent_publication_id,
            application_publication_id,
        )
    assert unknown.value.error_code == "capability_runtime_configuration_invalid"

    payload["schema_version"] = 1
    database.execute(
        "update api_compiled_mapping_plan set plan_json = ? where id = ?",
        (json.dumps(payload), release["mapping_plan_id"]),
    )
    ApiCapabilityRepository(database).set_release_status(
        str(release["id"]),
        status="DISABLED",
        actor_id=ACTOR_ID,
    )
    with pytest.raises(NonRetryableExecutionError) as disabled:
        _execute(
            _runtime(database, SequenceHttpClient([_success_response()])),
            release,
            agent_publication_id,
            application_publication_id,
        )
    assert disabled.value.error_code == "capability_runtime_configuration_invalid"
