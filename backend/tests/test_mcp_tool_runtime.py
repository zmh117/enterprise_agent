from __future__ import annotations

import json
from typing import Any

import pytest

from app.modules.job.domain.job_status import JobStatus
from app.modules.mcp_tool_runtime.job_snapshot import JobMcpToolSnapshotService
from app.modules.mcp_tool_runtime.manifest import (
    MCP_TOOL_MANIFEST,
    mcp_tool_schema_hash,
    require_mcp_tool,
)
from app.modules.mcp_tool_runtime.policies import assert_readonly_sql
from app.modules.mcp_tool_runtime.resource_resolver import DirectResourceResolver
from app.shared.exceptions import ToolPolicyError
from backend.tests.helpers import container


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


def test_direct_mcp_sql_policy_rejects_mutation() -> None:
    assert_readonly_sql("select id from orders")
    with pytest.raises(ToolPolicyError):
        assert_readonly_sql("delete from orders")
    with pytest.raises(ToolPolicyError):
        assert_readonly_sql("with changed as (update orders set state='x') select 1")


def test_job_snapshot_freezes_target_without_resolving_a_resource() -> None:
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

        assert frozen["snapshot"]["target"] == {
            "environment_code": "test",
            "base_code": "",
            "workshop_code": "",
        }
        assert frozen["snapshot"]["allowed_placements"] == ["edge"]
        assert frozen["snapshot"]["tools"]
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
