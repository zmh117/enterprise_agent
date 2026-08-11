from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.bootstrap import build_test_container
from app.modules.job.domain.job_status import JobStatus
from app.modules.mcp_tool_runtime.contracts import FakeReadOnlyToolExecutor
from app.modules.mcp_tool_runtime.direct_executor import DirectReadOnlyToolExecutor
from app.modules.mcp_tool_runtime.job_snapshot import JobMcpToolSnapshotService
from app.modules.mcp_tool_runtime.manifest import (
    MCP_TOOL_MANIFEST,
    mcp_tool_schema_hash,
    require_mcp_tool,
)
from app.modules.mcp_tool_runtime.policies import assert_readonly_sql
from app.modules.mcp_tool_runtime.resource_resolver import DirectResourceResolver
from app.modules.mcp_tool_runtime.service import ReadOnlyToolService
from app.modules.platform_config.application.governed_resources import (
    ResourceVerificationOutcome,
)
from app.modules.agent.application.agent_context_builder import (
    AgentContextBuilder,
    _tool_restrictions,
)
from app.shared.config import ExecutionSettings
from app.shared.exceptions import ToolPolicyError
from backend.tests.helpers import container, test_settings as _test_settings


_EXECUTION_POLICY = {
    "schema_version": 1,
    "requested": {"max_turns": 12, "timeout_seconds": 300, "max_tool_calls": 30},
    "effective": {"max_turns": 12, "timeout_seconds": 300, "max_tool_calls": 30},
    "sources": {"source_kind": "runtime_default"},
}


class _RowsDatabase:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> list[dict[str, Any]]:
        assert "from platform_resource resource" in sql
        resource_kind = str(parameters[0])
        return [row for row in self.rows if row["resource_kind"] == resource_kind]


class _SecretProvider:
    def resolve(self, ref: str) -> str:
        assert ref == "secret://platform/mysql-test-password"
        return "resolved-only-at-invocation"


class _PassingMysqlVerifier:
    def verify(
        self,
        *,
        resource: dict[str, object],
        draft: dict[str, object],
    ) -> ResourceVerificationOutcome:
        del resource, draft
        return ResourceVerificationOutcome(
            status="PASSED",
            provider_contract_version="mysql_v1",
            checks={"connection": "passed", "readonly": True},
        )


class _ServiceRepository:
    def __init__(self) -> None:
        self.job = SimpleNamespace(
            id="job-dynamic-target",
            user_id="user-1",
            internal_user_id="user-1",
            project_code="default",
            business_application_id="application-1",
        )

    def get_job(self, job_id: str) -> Any:
        assert job_id == self.job.id
        return self.job

    def add_tool_call(self, **_: Any) -> str:
        return "tool-call-1"

    def complete_tool_call(self, *_: Any, **__: Any) -> None:
        return None


class _AuditService:
    def record(self, *_: Any, **__: Any) -> str:
        return "audit-1"


class _PermissionService:
    def assert_builtin_tool_use_grant(self, **_: Any) -> None:
        return None


class _OldTargetSnapshot:
    def tool_binding(self, **_: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        return (
            {
                "environment_code": "",
                "base_code": "",
                "workshop_code": "",
            },
            [
                {
                    "resource_slot": "",
                    "candidates": [],
                    "schema_hash": MCP_TOOL_MANIFEST["get_schema_directory"].schema_hash,
                }
            ],
        )


class _BusinessAuthorization:
    def __init__(self) -> None:
        self.decisions: list[dict[str, Any]] = []
        self.requirements: list[dict[str, Any]] = []

    def decide(self, **kwargs: Any) -> dict[str, Any]:
        self.decisions.append(kwargs)
        return {"allowed": True}

    def require(self, **kwargs: Any) -> dict[str, Any]:
        self.requirements.append(kwargs)
        return {"allowed": True, "scope": kwargs}


class _NoPrefetchToolRegistry:
    def __init__(self) -> None:
        self.tool_service = self
        self.calls: list[dict[str, Any]] = []

    def available_tools(self) -> list[str]:
        return ["get_schema_directory"]

    def is_tool_visible_for_job(self, **_: Any) -> bool:
        return True

    def call(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        raise AssertionError("Agent context construction must not pre-call a Tool")


class _SkillLoader:
    def load(self, *_: Any) -> dict[str, str]:
        return {}


class _AgentConfigService:
    def __init__(self, runtime_kind: str) -> None:
        self.runtime_kind = runtime_kind

    def publication(self, publication_id: str) -> dict[str, Any]:
        assert publication_id == "agent-publication-1"
        return {
            "id": publication_id,
            "revision": 1,
            "config_hash": "agent-config-hash",
            "runtime_kind": self.runtime_kind,
            "snapshot": {"skills": [], "model_policy": {}},
        }


def _database_resource(*, code: str, placement: str) -> dict[str, Any]:
    return {
        "resource_id": f"resource-{code}",
        "code": code,
        "resource_kind": "database",
        "scope_type": "environment",
        "placement": placement,
        "environment_code": "test",
        "base_code": "",
        "workshop_code": "",
        "resource_revision_id": f"revision-{code}-1",
        "revision": 1,
        "provider_type": "mysql",
        "provider_contract_version": "mysql_v1",
        "config_json": json.dumps(
            {
                "host": "mysql.test.internal",
                "port": 3306,
                "database": "diagnostics",
                "username": "readonly",
            }
        ),
        "secret_refs_json": json.dumps(
            {"password_ref": "secret://platform/mysql-test-password"}
        ),
        "content_hash": "a" * 64,
    }


def test_code_owned_mcp_manifest_has_stable_unique_tool_contracts() -> None:
    assert MCP_TOOL_MANIFEST
    assert len(MCP_TOOL_MANIFEST) == len(set(MCP_TOOL_MANIFEST))
    for identifier, definition in MCP_TOOL_MANIFEST.items():
        assert definition.identifier == identifier
        assert definition.schema_hash == mcp_tool_schema_hash(definition.input_schema)
        assert len(definition.schema_hash) == 64
        assert definition.read_only is True
        assert require_mcp_tool(identifier) is definition


def test_direct_resource_resolution_requires_exact_target_or_placement() -> None:
    resolver = DirectResourceResolver(
        _RowsDatabase(
            [
                _database_resource(code="mysql-test-cloud", placement="cloud"),
                _database_resource(code="mysql-test-edge", placement="edge"),
            ]
        ),
        secret_provider=_SecretProvider(),
    )

    with pytest.raises(ToolPolicyError) as ambiguous:
        resolver.resolve(resource_kind="database", environment="test")
    assert ambiguous.value.error_code == "mcp_resource_ambiguous"

    resolved = resolver.resolve(
        resource_kind="database",
        environment="test",
        placement="edge",
    )
    assert resolved.resource_code == "mysql-test-edge"
    assert resolved.placement == "edge"
    assert resolved.binding.database is not None
    assert resolved.binding.database.password == "resolved-only-at-invocation"

    with pytest.raises(ToolPolicyError) as missing:
        resolver.resolve(resource_kind="database", environment="production")
    assert missing.value.error_code == "mcp_resource_not_resolved"


def test_tool_mcp_bootstrap_resolves_published_resource_secret() -> None:
    runtime = build_test_container(
        _test_settings(),
        migrate=True,
        seed=True,
        service_name="tool-mcp",
    )
    actor_id = "user_local_admin"
    runtime.database.execute(
        """
        insert into permission_policy
          (id, subject_type, subject_code, resource_type, resource_code,
           action, effect, priority, status, revision, created_at, updated_at)
        values
          ('test-tool-mcp-platform-config', 'user', ?, 'platform_config', '*',
           'manage', 'allow', 1, 'enabled', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
          ('test-tool-mcp-secret', 'user', ?, 'secret', '*',
           'manage', 'allow', 1, 'enabled', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        on conflict(id) do nothing
        """,
        (actor_id, actor_id),
    )
    try:
        runtime.platform_config_service.upsert_environment(
            {"code": "tool_mcp_test"},
            actor_id=actor_id,
        )
        runtime.platform_config_service.create_platform_secret(
            {
                "code": "tool_mcp_mysql_password",
                "value": "resolved-through-platform-secret-repository",
            },
            actor_id=actor_id,
        )
        resource_service = runtime.platform_config_service.governed_resources
        resource_service.create_resource(
            {
                "code": "tool_mcp_mysql",
                "name": "Tool MCP MySQL",
                "resource_kind": "database",
                "scope_type": "environment",
                "environment_code": "tool_mcp_test",
                "provider_type": "mysql",
                "config": {
                    "host": "mysql.internal",
                    "port": 3306,
                    "database": "diagnostics",
                    "username": "readonly",
                },
                "secret_refs": {
                    "password_ref": "secret://platform/tool_mcp_mysql_password"
                },
            },
            actor_id=actor_id,
        )
        resource_service.verify_draft(
            "tool_mcp_mysql",
            actor_id=actor_id,
            verifier=_PassingMysqlVerifier(),
        )
        resource_service.publish_draft(
            "tool_mcp_mysql",
            actor_id=actor_id,
        )

        executor = runtime.tool_service.tool_executor
        assert isinstance(executor, DirectReadOnlyToolExecutor)
        resolved = executor.resolver.resolve(
            resource_kind="database",
            environment="tool_mcp_test",
        )

        assert resolved.resource_code == "tool_mcp_mysql"
        assert resolved.binding.database is not None
        assert (
            resolved.binding.database.password
            == "resolved-through-platform-secret-repository"
        )
    finally:
        runtime.database.close()


def test_direct_mcp_sql_policy_rejects_mutation() -> None:
    assert_readonly_sql("select id from orders")
    with pytest.raises(ToolPolicyError):
        assert_readonly_sql("delete from orders")
    with pytest.raises(ToolPolicyError):
        assert_readonly_sql("with changed as (update orders set state='x') select 1")


def test_tool_call_uses_agent_target_even_for_an_old_empty_target_snapshot() -> None:
    executor = FakeReadOnlyToolExecutor()
    authorization = _BusinessAuthorization()
    service = ReadOnlyToolService(
        tool_executor=executor,
        permission_service=_PermissionService(),  # type: ignore[arg-type]
        audit_service=_AuditService(),  # type: ignore[arg-type]
        repository=_ServiceRepository(),  # type: ignore[arg-type]
        limits=ExecutionSettings(),
        business_authorization_service=authorization,  # type: ignore[arg-type]
        mcp_tool_snapshot_service=_OldTargetSnapshot(),  # type: ignore[arg-type]
    )

    assert service.is_tool_visible_for_job(
        job_id="job-dynamic-target",
        tool_name="get_schema_directory",
    )
    assert "environment" not in authorization.decisions[-1]

    result = service.call_tool(
        job_id="job-dynamic-target",
        user_id="user-1",
        project_code="default",
        tool_name="get_schema_directory",
        arguments={"environment": "test", "limit": 10},
    )

    assert authorization.requirements[-1]["environment"] == "test"
    assert authorization.requirements[-1]["base"] == ""
    assert authorization.requirements[-1]["workshop"] == ""
    assert result.summary["environment"] == "test"
    assert executor.calls[-1][1]["environment"] == "test"


def test_tool_restrictions_do_not_disclose_unassigned_tool_identifiers() -> None:
    unassigned_text = " ".join(_tool_restrictions([]))
    assert "get_schema_directory" not in unassigned_text
    assert "query_database" not in unassigned_text

    database_only_text = " ".join(_tool_restrictions(["query_database"]))
    assert "query_database" not in database_only_text
    assert "get_schema_directory" not in database_only_text


@pytest.mark.parametrize("runtime_kind", ["python-v1", "typescript-v1"])
def test_greeting_context_does_not_prefetch_resources_or_disclose_unassigned_tools(
    runtime_kind: str,
) -> None:
    registry = _NoPrefetchToolRegistry()
    builder = AgentContextBuilder(
        tool_registry=registry,  # type: ignore[arg-type]
        skill_loader=_SkillLoader(),  # type: ignore[arg-type]
        agent_config_service=_AgentConfigService(runtime_kind),  # type: ignore[arg-type]
    )
    job = SimpleNamespace(
        id="job-greeting",
        execution_policy=_EXECUTION_POLICY,
        user_message="你好",
        project_code="default",
        agent_publication_id="agent-publication-1",
        agent_revision=1,
        agent_config_hash="agent-config-hash",
        agent_runtime_kind=runtime_kind,
        agent_runtime_protocol_version="1.0",
        business_application_publication_id="application-publication-1",
    )

    context = builder.build(job)  # type: ignore[arg-type]

    assert registry.calls == []
    assert context.allowed_tools == ["get_schema_directory"]
    assert context.retrieved_context == {"conversation": {}}
    serialized = json.dumps(context.retrieved_context, ensure_ascii=False)
    assert "tool_not_assigned" not in serialized
    assert "get_er_context" not in serialized
    assert "get_business_flow_context" not in serialized


def test_job_snapshot_does_not_freeze_routing_target_or_resolve_a_resource() -> None:
    runtime = container()
    try:
        session = runtime.agent_repository.create_session(
            dingding_conversation_id="mcp-snapshot-conversation",
            dingding_user_id="local-user",
            source="debug",
            project_code="default",
            routing_context={"environment": "test", "placement": "edge"},
        )
        job = runtime.agent_repository.create_job(
            session_id=session.id,
            idempotency_key="mcp-snapshot-job",
            user_id="local-user",
            project_code="default",
            source="debug",
            user_message="hello",
            max_retry_count=0,
            initial_status=JobStatus.PENDING,
            routing_context={"environment": "test", "placement": "edge"},
            agent_publication_id="agent_publication_default_v1",
            execution_policy=_EXECUTION_POLICY,
        )

        frozen = runtime.mcp_tool_snapshot_service.freeze_agent_only(
            job_id=job.id,
            requester_id="local-user",
            agent_publication_id="agent_publication_default_v1",
            routing_context={"environment": "test", "placement": "edge"},
            business_authorization={},
            runtime_authorization={},
        )

        assert "target" not in frozen["snapshot"]
        assert "allowed_placements" not in frozen["snapshot"]
        assert frozen["snapshot"]["tools"]
        binding = runtime.mcp_tool_snapshot_service.tool_binding(
            job_id=job.id,
            tool_identifier=frozen["snapshot"]["tools"][0]["tool_identifier"],
        )
        assert binding is not None
        assert binding[0] == {}
        assert binding[1][0]["available_placements"] == []
        assert runtime.database.execute("select * from platform_resource") == []
    finally:
        runtime.database.close()


def test_job_snapshot_fails_closed_on_schema_drift() -> None:
    runtime = container()
    try:
        session = runtime.agent_repository.create_session(
            dingding_conversation_id="mcp-drift-conversation",
            dingding_user_id="local-user",
            source="debug",
            project_code="default",
        )
        job = runtime.agent_repository.create_job(
            session_id=session.id,
            idempotency_key="mcp-drift-job",
            user_id="local-user",
            project_code="default",
            source="debug",
            user_message="hello",
            max_retry_count=0,
            agent_publication_id="agent_publication_default_v1",
            execution_policy=_EXECUTION_POLICY,
        )
        frozen = runtime.mcp_tool_snapshot_service.freeze_agent_only(
            job_id=job.id,
            requester_id="local-user",
            agent_publication_id="agent_publication_default_v1",
            routing_context={},
            business_authorization={},
            runtime_authorization={},
        )
        snapshot = dict(frozen["snapshot"])
        tools = [dict(value) for value in snapshot["tools"]]
        tools[0]["schema_hash"] = "0" * 64
        snapshot["tools"] = tools
        runtime.database.execute(
            """
            update agent_job_mcp_tool_snapshot
               set snapshot_json = ?, snapshot_hash = ?
             where job_id = ?
            """,
            (
                JobMcpToolSnapshotService._json_text(snapshot),
                JobMcpToolSnapshotService._hash(snapshot),
                job.id,
            ),
        )

        with pytest.raises(ToolPolicyError) as drift:
            runtime.mcp_tool_snapshot_service.verify(job.id)
        assert drift.value.error_code == "mcp_tool_schema_drift"
    finally:
        runtime.database.close()
