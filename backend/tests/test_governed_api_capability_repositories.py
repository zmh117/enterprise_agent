from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.api_capability.domain.contracts import content_hash
from app.modules.api_capability.infrastructure import (
    ApiCapabilityRepository,
    ApiConnectionRepository,
    CapabilityPublicationRepository,
    GovernedApiExecutionRepository,
)
from app.modules.identity.infrastructure import (
    ExternalApiCredentialCipher,
    ExternalApiCredentialRepository,
    IdentityRepository,
)
from app.shared.database import Database, default_migrations_dir
from app.shared.exceptions import NonRetryableExecutionError
from app.shared.migrations import Migrator


ACTOR_ID = "user-governed-api-admin"
NOW = "2026-07-31T00:00:00+00:00"


@pytest.fixture
def database() -> Database:
    value = Database("sqlite:///:memory:")
    result = Migrator(
        value,
        default_migrations_dir(),
        migrator_build="governed-api-repository-test",
    ).run()
    assert result.head == "027"
    value.execute(
        """
        insert into app_user
          (id, username, display_name, status, created_at, updated_at)
        values (?, 'governed-api-admin', 'API Admin', 'enabled', ?, ?)
        """,
        (ACTOR_ID, NOW, NOW),
    )
    try:
        yield value
    finally:
        value.close()


def _published_connection(
    database: Database,
) -> tuple[ApiConnectionRepository, dict[str, object]]:
    repository = ApiConnectionRepository(database)
    connection = repository.create(
        code="ones-primary",
        name="ONES Primary",
        provider="ones",
        origin={
            "scheme": "https",
            "host": "ones.example.test",
            "port": 443,
            "connect_timeout_ms": 3000,
            "read_timeout_ms": 10000,
            "max_response_bytes": 1048576,
        },
        authentication={
            "schema_version": 1,
            "login_path": "/project/api/project/auth/login",
            "token_path": "$.token",
            "header_name": "Ones-Auth-Token",
        },
        actor_id=ACTOR_ID,
    )
    draft = connection["draft"]
    repository.record_verification(
        str(connection["id"]),
        draft_revision=int(draft["draft_revision"]),
        draft_hash=str(draft["content_hash"]),
        actor_id=ACTOR_ID,
        status="PASSED",
        checks={"origin": "ok", "authentication": "ok"},
    )
    revision = repository.publish(
        str(connection["id"]),
        draft_revision=int(draft["draft_revision"]),
        draft_hash=str(draft["content_hash"]),
        actor_id=ACTOR_ID,
    )
    return repository, revision


def _bound_identity(
    database: Database,
    connection_revision_id: str,
) -> tuple[ExternalApiCredentialRepository, dict[str, object]]:
    repository = ExternalApiCredentialRepository(database)
    cipher = ExternalApiCredentialCipher("repository-test-master-key")
    encrypted = cipher.encrypt("personal-ones-token")
    challenge = repository.create_challenge(
        user_id=ACTOR_ID,
        connection_revision_id=connection_revision_id,
        external_user_id="ones-user-admin",
        display_name="ONES Admin",
        team_ids=["team-a", "team-b"],
        encrypted_token=encrypted,
        expires_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
    )
    credential = repository.consume_challenge(
        str(challenge["id"]),
        user_id=ACTOR_ID,
        connection_revision_id=connection_revision_id,
        default_team_id="team-b",
    )
    assert (
        cipher.decrypt(
            ciphertext=repository.get_current_encrypted(user_id=ACTOR_ID).ciphertext,
            key_id=repository.get_current_encrypted(user_id=ACTOR_ID).key_id,
        )
        == "personal-ones-token"
    )
    return repository, credential


def _published_capability(
    database: Database,
    connection_revision: dict[str, object],
    external_identity_id: str,
) -> tuple[ApiCapabilityRepository, dict[str, object]]:
    repository = ApiCapabilityRepository(database)
    capability_config = {
        "name": "Search ONES work items",
        "description": "Search ONES work items for the current user.",
        "operation_semantics": "QUERY",
        "data_classification": "INTERNAL",
        "input_schema": {
            "type": "object",
            "properties": {"keyword": {"type": "string"}},
            "required": ["keyword"],
            "additionalProperties": False,
        },
        "output_schema": {
            "type": "object",
            "properties": {"total": {"type": "integer"}},
            "required": ["total"],
            "additionalProperties": False,
        },
    }
    handler = {
        "method": "POST",
        "relative_path": "/project/api/project/graphql",
        "graphql_document": "query Search($keyword: String!) { search(keyword: $keyword) { total } }",
    }
    mapping_ast = {
        "schema_version": 1,
        "request": {"type": "object", "fields": {}},
        "response": {"type": "object", "fields": {}},
    }
    capability = repository.create(
        identifier="cap__ones__work_item__search",
        name="Search ONES work items",
        connection_revision_id=str(connection_revision["id"]),
        authentication_profile_revision_id=str(
            connection_revision["authentication_profile_revision_id"]
        ),
        capability=capability_config,
        handler=handler,
        mapping_ast=mapping_ast,
        actor_id=ACTOR_ID,
    )
    draft = capability["draft"]
    repository.record_verification(
        str(capability["id"]),
        draft_revision=int(draft["draft_revision"]),
        draft_hash=str(draft["content_hash"]),
        external_identity_id=external_identity_id,
        external_user_id="ones-user-admin",
        default_team_id="team-b",
        actor_id=ACTOR_ID,
        status="PASSED",
        result_summary={"output_shape": ["total"]},
        result_hash=content_hash({"total": 0}),
    )
    compiled_plan = {
        "schema_version": 1,
        "ast_hash": content_hash(mapping_ast),
        "request_plan": {"type": "object", "fields": {}},
        "response_plan": {"type": "object", "fields": {}},
    }
    release = repository.create_release(
        str(capability["id"]),
        draft_revision=int(draft["draft_revision"]),
        draft_hash=str(draft["content_hash"]),
        idempotency_key="publish-search-v1",
        compiled_plan=compiled_plan,
        compiled_plan_hash=content_hash(compiled_plan),
        actor_id=ACTOR_ID,
        release_note="Initial internal release",
    )
    return repository, release


def _publication_parents(
    database: Database,
) -> tuple[str, str]:
    database.execute(
        """
        insert into agent_definition
          (id, code, name, created_by, created_at, updated_at)
        values ('agent-capability', 'agent-capability', 'Agent', ?, ?, ?)
        """,
        (ACTOR_ID, NOW, NOW),
    )
    database.execute(
        """
        insert into agent_revision
          (id, agent_id, revision, status, config_json, config_hash,
           created_by, created_at, updated_at)
        values ('agent-revision-capability', 'agent-capability', 1,
                'published', '{}', 'agent-hash', ?, ?, ?)
        """,
        (ACTOR_ID, NOW, NOW),
    )
    database.execute(
        """
        insert into agent_publication
          (id, agent_id, revision_id, revision, snapshot_json, config_hash,
           published_by, published_at)
        values ('agent-publication-capability', 'agent-capability',
                'agent-revision-capability', 1, '{}', 'agent-hash', ?, ?)
        """,
        (ACTOR_ID, NOW),
    )
    database.execute(
        """
        insert into business_application
          (id, code, name, project_code, owner_user_id, created_by,
           created_at, updated_at)
        values ('application-capability', 'application-capability',
                'Application', 'default', ?, ?, ?, ?)
        """,
        (ACTOR_ID, ACTOR_ID, NOW, NOW),
    )
    database.execute(
        """
        insert into business_application_revision
          (id, application_id, revision, status, agent_publication_id,
           config_hash, created_by, created_at, updated_at)
        values ('application-revision-capability', 'application-capability',
                1, 'published', 'agent-publication-capability',
                'application-hash', ?, ?, ?)
        """,
        (ACTOR_ID, NOW, NOW),
    )
    database.execute(
        """
        insert into business_application_publication
          (id, application_id, revision_id, revision, snapshot_json,
           config_hash, published_by, published_at)
        values ('application-publication-capability',
                'application-capability',
                'application-revision-capability', 1, '{}',
                'application-hash', ?, ?)
        """,
        (ACTOR_ID, NOW),
    )
    return (
        "agent-publication-capability",
        "application-publication-capability",
    )


def test_connection_draft_uses_optimistic_lock_and_published_revision_is_stable(
    database: Database,
) -> None:
    repository, revision = _published_connection(database)
    connection = repository.get(str(revision["connection_id"]))
    with pytest.raises(
        NonRetryableExecutionError,
        match="revision conflict",
    ):
        repository.save_draft(
            str(connection["id"]),
            expected_revision=0,
            origin={
                "scheme": "https",
                "host": "changed.example.test",
                "port": 443,
            },
            authentication={"schema_version": 1},
            actor_id=ACTOR_ID,
        )
    before = repository.get_revision(str(revision["id"]))
    repository.save_draft(
        str(connection["id"]),
        expected_revision=int(connection["draft"]["draft_revision"]),
        origin={
            "scheme": "https",
            "host": "new.example.test",
            "port": 443,
        },
        authentication={"schema_version": 1},
        actor_id=ACTOR_ID,
    )
    after = repository.get_revision(str(revision["id"]))
    assert after["content_hash"] == before["content_hash"]
    assert after["origin_host"] == "ones.example.test"


def test_challenge_is_single_use_and_identity_only_rows_project_missing(
    database: Database,
) -> None:
    _, revision = _published_connection(database)
    credential_repository, credential = _bound_identity(
        database,
        str(revision["id"]),
    )
    identity = IdentityRepository(database).get_external_identity(
        str(credential["external_identity_id"])
    )
    assert identity["metadata"]["default_team_id"] == "team-b"
    assert "token" not in json.dumps(identity).lower()

    challenge = credential_repository.create_challenge(
        user_id=ACTOR_ID,
        connection_revision_id=str(revision["id"]),
        external_user_id="ones-user-admin",
        display_name="ONES Admin",
        team_ids=["team-a"],
        encrypted_token=ExternalApiCredentialCipher("repository-test-master-key").encrypt(
            "rotated-token"
        ),
        expires_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
    )
    credential_repository.consume_challenge(
        str(challenge["id"]),
        user_id=ACTOR_ID,
        connection_revision_id=str(revision["id"]),
        default_team_id="team-a",
    )
    with pytest.raises(NonRetryableExecutionError):
        credential_repository.consume_challenge(
            str(challenge["id"]),
            user_id=ACTOR_ID,
            connection_revision_id=str(revision["id"]),
            default_team_id="team-a",
        )

    database.execute(
        """
        insert into app_user
          (id, username, display_name, status, created_at, updated_at)
        values ('legacy-user', 'legacy-user', 'Legacy', 'enabled', ?, ?)
        """,
        (NOW, NOW),
    )
    database.execute(
        """
        insert into user_external_identity
          (id, user_id, provider, tenant_code, external_subject_id,
           display_name, status, metadata_json, created_at, updated_at)
        values ('legacy-ones', 'legacy-user', 'ones', 'ones',
                'legacy-ones-user', 'Legacy ONES', 'enabled', '{}', ?, ?)
        """,
        (NOW, NOW),
    )
    legacy = IdentityRepository(database).get_external_identity("legacy-ones")
    assert legacy["credential_status"] == "missing"


def test_capability_publish_is_idempotent_and_handler_only_release_reuses_contract(
    database: Database,
) -> None:
    _, connection_revision = _published_connection(database)
    _, credential = _bound_identity(database, str(connection_revision["id"]))
    repository, release_v1 = _published_capability(
        database,
        connection_revision,
        str(credential["external_identity_id"]),
    )
    capability = repository.get(str(release_v1["capability_id"]))
    draft = capability["draft"]
    repeated = repository.create_release(
        str(capability["id"]),
        draft_revision=int(draft["draft_revision"]),
        draft_hash=str(draft["content_hash"]),
        idempotency_key="publish-search-v1",
        compiled_plan=draft["mapping_ast"],
        compiled_plan_hash=content_hash(draft["mapping_ast"]),
        actor_id=ACTOR_ID,
    )
    assert repeated["id"] == release_v1["id"]

    changed_handler = {
        **draft["handler"],
        "relative_path": "/project/api/project/graphql/v2",
    }
    saved = repository.save_draft(
        str(capability["id"]),
        expected_revision=int(draft["draft_revision"]),
        connection_revision_id=str(draft["connection_revision_id"]),
        authentication_profile_revision_id=str(draft["authentication_profile_revision_id"]),
        capability=draft["capability"],
        handler=changed_handler,
        mapping_ast=draft["mapping_ast"],
        actor_id=ACTOR_ID,
    )
    changed = saved["draft"]
    repository.record_verification(
        str(capability["id"]),
        draft_revision=int(changed["draft_revision"]),
        draft_hash=str(changed["content_hash"]),
        external_identity_id=str(credential["external_identity_id"]),
        external_user_id="ones-user-admin",
        default_team_id="team-b",
        actor_id=ACTOR_ID,
        status="PASSED",
        result_summary={},
    )
    plan = {
        "schema_version": 1,
        "ast_hash": content_hash(changed["mapping_ast"]),
        "request_plan": {},
        "response_plan": {},
    }
    release_v2 = repository.create_release(
        str(capability["id"]),
        draft_revision=int(changed["draft_revision"]),
        draft_hash=str(changed["content_hash"]),
        idempotency_key="publish-search-v2",
        compiled_plan=plan,
        compiled_plan_hash=content_hash(plan),
        actor_id=ACTOR_ID,
    )
    assert release_v2["release_revision"] == 2
    assert release_v2["capability_revision_id"] == release_v1["capability_revision_id"]
    assert release_v2["handler_revision_id"] != release_v1["handler_revision_id"]


def test_publication_snapshots_freeze_exact_release_and_application_subset(
    database: Database,
) -> None:
    _, connection_revision = _published_connection(database)
    _, credential = _bound_identity(database, str(connection_revision["id"]))
    capability_repository, release = _published_capability(
        database,
        connection_revision,
        str(credential["external_identity_id"]),
    )
    agent_publication_id, application_publication_id = _publication_parents(database)
    repository = CapabilityPublicationRepository(database)
    envelope = repository.freeze_agent_envelope(
        agent_publication_id,
        release_ids=[str(release["id"])],
    )
    assert envelope[0].release_id == release["id"]
    assert str(envelope[0].identifier) == "cap__ones__work_item__search"
    allowlist = repository.freeze_application_allowlist(
        application_publication_id,
        agent_publication_id=agent_publication_id,
        release_ids=[str(release["id"])],
    )
    assert allowlist[0].release_id == release["id"]
    with pytest.raises(
        NonRetryableExecutionError,
        match="already frozen",
    ):
        repository.freeze_agent_envelope(
            agent_publication_id,
            release_ids=[str(release["id"])],
        )
    with pytest.raises(NonRetryableExecutionError) as in_use:
        capability_repository.set_release_status(
            str(release["id"]),
            status="ARCHIVED",
            actor_id=ACTOR_ID,
            reason="No longer supported",
        )
    assert in_use.value.error_code == "capability_release_in_use"


def test_execution_repository_never_persists_token_or_business_body(
    database: Database,
) -> None:
    _, connection_revision = _published_connection(database)
    _, credential = _bound_identity(database, str(connection_revision["id"]))
    _, release = _published_capability(
        database,
        connection_revision,
        str(credential["external_identity_id"]),
    )
    agent_publication_id, application_publication_id = _publication_parents(database)
    database.execute(
        """
        insert into agent_session
          (id, dingding_conversation_id, dingding_user_id,
           source, project_code, created_at, updated_at)
        values ('session-api', 'conversation-api', 'sender-api',
                'dingding', 'default', ?, ?)
        """,
        (NOW, NOW),
    )
    database.execute(
        """
        insert into agent_job
          (id, session_id, idempotency_key, user_id, project_code,
           source, user_message, status, internal_user_id,
           agent_publication_id, created_at)
        values ('job-api', 'session-api', 'job-api-key', ?, 'default',
                'dingding', 'search', 'RUNNING', ?,
                'agent-publication-capability', ?)
        """,
        (ACTOR_ID, ACTOR_ID, NOW),
    )
    database.execute(
        """
        insert into agent_tool_call
          (id, job_id, tool_name, request_payload, response_summary,
           status, created_at)
        values ('tool-call-api', 'job-api',
                'cap__ones__work_item__search', '{}', '',
                'SUCCEEDED', ?)
        """,
        (NOW,),
    )
    repository = GovernedApiExecutionRepository(database)
    subject = repository.freeze_external_subject(
        job_id="job-api",
        external_identity_id=str(credential["external_identity_id"]),
        external_user_id="ones-user-admin",
        default_team_id="team-b",
        binding_revision=1,
    )
    assert len(str(subject["snapshot_hash"])) == 64
    attempt = repository.record_attempt(
        tool_call_id="tool-call-api",
        job_id="job-api",
        capability_release_id=str(release["id"]),
        correlation_id="correlation-api",
        attempt_no=1,
        status_class="SUCCEEDED",
        http_status=200,
        duration_ms=12,
        response_size=42,
        request_hash=content_hash({"keyword": "issue"}),
        response_hash=content_hash({"total": 1}),
    )
    provenance = repository.record_provenance(
        tool_call_id="tool-call-api",
        user_id=ACTOR_ID,
        application_publication_id=application_publication_id,
        agent_publication_id=agent_publication_id,
        capability_release_id=str(release["id"]),
        normalized_result=b'{"total":1}',
    )
    serialized = json.dumps(
        {"subject": subject, "attempt": attempt, "provenance": provenance}
    ).lower()
    assert "personal-ones-token" not in serialized
    assert "token_ciphertext" not in serialized
    assert '\\"total\\":1' not in serialized
