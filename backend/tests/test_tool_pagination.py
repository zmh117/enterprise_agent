from __future__ import annotations

import json
from dataclasses import replace
from unittest.mock import MagicMock, patch

import pytest

from app.modules.authorization_center.application.service import BusinessAuthorizationService
from app.modules.mcp_tool_runtime.contracts import ResourceAccessGrant, ToolRequestContext
from app.modules.mcp_tool_runtime.direct_executor import DirectReadOnlyToolExecutor
from app.modules.mcp_tool_runtime.domain.addressing import ResourceBinding
from app.modules.mcp_tool_runtime.domain.schema_directory import SchemaColumn, SchemaTable
from app.modules.mcp_tool_runtime.domain.topology import (
    Base,
    DatabaseConnection,
    DatabaseEngine,
    Environment,
    ResourceKind,
    RedisConnection,
)
from app.modules.mcp_tool_runtime.infrastructure.db.schema_directory import (
    FakeSchemaInspector,
    SchemaInspectorFactory,
)
from app.modules.mcp_tool_runtime.infrastructure.redis_gateway import (
    FakeRedisGateway,
    RealRedisGateway,
)
from app.modules.mcp_tool_runtime.pagination import ToolPaginationCursorCodec
from app.modules.mcp_tool_runtime.resource_resolver import (
    DirectResourceResolver,
    ResolvedToolResource,
)
from app.shared.config import ExecutionSettings
from app.shared.exceptions import ToolPolicyError


def _context(*, job_id: str = "job-1") -> ToolRequestContext:
    return ToolRequestContext(
        job_id=job_id,
        user_id="user-1",
        project_code="default",
        application_id="app-1",
        snapshot_hash="a" * 64,
        authorization_hash="b" * 64,
    )


def test_tool_cursor_round_trips_only_for_same_job_request_and_state() -> None:
    request = {"resource_kind": "database", "query": "order"}
    cursor = ToolPaginationCursorCodec.encode(
        context=_context(),
        purpose="resource-directory",
        request=request,
        state_fingerprint="c" * 64,
        position=["database", "prod", "order-db"],
    )

    assert ToolPaginationCursorCodec.decode(
        cursor,
        context=_context(),
        purpose="resource-directory",
        request=request,
        state_fingerprint="c" * 64,
    ) == ["database", "prod", "order-db"]

    with pytest.raises(ToolPolicyError) as cross_job:
        ToolPaginationCursorCodec.decode(
            cursor,
            context=_context(job_id="job-2"),
            purpose="resource-directory",
            request=request,
            state_fingerprint="c" * 64,
        )
    assert cross_job.value.error_code == "mcp_pagination_cursor_invalid"

    with pytest.raises(ToolPolicyError) as cross_filter:
        ToolPaginationCursorCodec.decode(
            cursor,
            context=_context(),
            purpose="resource-directory",
            request={"resource_kind": "redis", "query": "order"},
            state_fingerprint="c" * 64,
        )
    assert cross_filter.value.error_code == "mcp_pagination_cursor_invalid"


def test_tool_cursor_rejects_tampering_and_stale_state() -> None:
    cursor = ToolPaginationCursorCodec.encode(
        context=_context(),
        purpose="schema-directory",
        request={"environment": "prod", "query": ""},
        state_fingerprint="revision-1",
        position="orders",
    )

    replacement = "A" if cursor[-1] != "A" else "B"
    with pytest.raises(ToolPolicyError) as tampered:
        ToolPaginationCursorCodec.decode(
            cursor[:-1] + replacement,
            context=_context(),
            purpose="schema-directory",
            request={"environment": "prod", "query": ""},
            state_fingerprint="revision-1",
        )
    assert tampered.value.error_code == "mcp_pagination_cursor_invalid"

    with pytest.raises(ToolPolicyError) as stale:
        ToolPaginationCursorCodec.decode(
            cursor,
            context=_context(),
            purpose="schema-directory",
            request={"environment": "prod", "query": ""},
            state_fingerprint="revision-2",
        )
    assert stale.value.error_code == "mcp_pagination_cursor_stale"


class _RowsDatabase:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def execute(self, _sql: str, parameters: tuple[object, ...] = ()) -> list[dict[str, object]]:
        return [row for row in self.rows if row["resource_kind"] == parameters[0]]


class _SecretMustNotResolve:
    def resolve(self, _ref: str) -> str:
        raise AssertionError("resource directory must not resolve a Secret")


def _resource(index: int, *, environment: str = "prod") -> dict[str, object]:
    code = f"db-{index:03d}"
    return {
        "resource_id": f"resource-{code}",
        "code": code,
        "resource_kind": "database",
        "scope_type": "environment",
        "placement": "cloud",
        "environment_code": environment,
        "base_code": "",
        "workshop_code": "",
        "resource_revision_id": f"revision-{code}",
        "revision": 1,
        "scope_bindings_json": json.dumps([]),
        "content_hash": f"{index:064x}",
    }


def test_authorized_resource_directory_pages_without_resolving_secrets() -> None:
    database = _RowsDatabase(
        [*[_resource(index) for index in range(51)], _resource(99, environment="secret")]
    )
    executor = DirectReadOnlyToolExecutor(
        DirectResourceResolver(database, secret_provider=_SecretMustNotResolve()),  # type: ignore[arg-type]
        limits=ExecutionSettings(),
    )
    grants = (
        ResourceAccessGrant(
            tool_identifier="query_database",
            resource_kind="database",
            environment="prod",
        ),
    )

    first = executor.list_available_tool_resources(
        _context(),
        grants=grants,
        resource_kind="database",
        limit=50,
    )

    assert len(first.summary["resources"]) == 50
    assert first.summary["has_more"] is True
    assert first.summary["next_cursor"]
    assert first.truncated is True
    assert all(item["environment"] == "prod" for item in first.summary["resources"])
    assert all(item["resolution_status"] == "AMBIGUOUS" for item in first.summary["resources"])
    assert "host" not in json.dumps(first.summary)

    second = executor.list_available_tool_resources(
        _context(),
        grants=grants,
        resource_kind="database",
        limit=50,
        cursor=first.summary["next_cursor"],
    )
    assert [item["resource_code"] for item in second.summary["resources"]] == ["db-050"]
    assert second.summary["has_more"] is False
    assert second.summary["next_cursor"] == ""


class _ProjectionDatabase:
    def execute_one(self, _sql: str, _parameters: tuple[object, ...]) -> dict[str, str]:
        return {"id": "app-1", "status": "enabled"}


class _ProjectionRepository:
    database = _ProjectionDatabase()

    def application_tool_is_effective(self, _application_id: str, tool: str) -> bool:
        return tool == "query_database"

    def business_access_for_user(self, **_: object) -> list[dict[str, object]]:
        return [
            {
                "tool_identifiers": ["query_database"],
                "scopes": [{"environment_code": "other", "base_code": "", "workshop_code": ""}],
            },
            {
                "tool_identifiers": ["list_available_tool_resources"],
                "scopes": [{"environment_code": "prod", "base_code": "", "workshop_code": ""}],
            },
        ]


class _ProjectionIdentityRepository:
    def get_user(self, _user_id: str) -> dict[str, str]:
        return {"status": "enabled"}


def test_business_resource_projection_keeps_tool_and_scope_on_same_access() -> None:
    service = BusinessAuthorizationService(
        _ProjectionRepository(),  # type: ignore[arg-type]
        _ProjectionIdentityRepository(),  # type: ignore[arg-type]
    )

    projection = service.resource_access_projection(
        user_id="user-1",
        application_id="app-1",
        tool_identifiers=("query_database",),
    )

    assert projection == (
        {
            "tool_identifiers": ("query_database",),
            "environment": "other",
            "base": "",
            "workshop": "",
        },
    )


class _ResolvedDatabaseResourceResolver:
    def __init__(self) -> None:
        self.revision = "revision-db-1"

    def resolve(self, **_: object) -> ResolvedToolResource:
        database = DatabaseConnection(
            host="db.internal",
            port=3306,
            database="app",
            user="reader",
            password="secret",
        )
        base = Base(code="main", engine=DatabaseEngine.MYSQL, database=database)
        binding = ResourceBinding(
            environment=Environment(code="prod", bases={"main": base}),
            base=base,
            kind=ResourceKind.DATABASE,
            workshop=None,
            engine=DatabaseEngine.MYSQL,
            database=database,
        )
        return ResolvedToolResource(
            resource_id="resource-db",
            resource_code="db-main",
            resource_revision_id=self.revision,
            resource_content_hash=("d" * 64 if self.revision.endswith("1") else "e" * 64),
            placement="cloud",
            table_prefix="",
            redis_namespace_prefixes=(),
            loki_selector_conditions=(),
            scope_target=("prod", "main", ""),
            binding=binding,
        )


def test_schema_directory_pages_51_tables_and_binds_resource_revision() -> None:
    resolver = _ResolvedDatabaseResourceResolver()
    executor = DirectReadOnlyToolExecutor(resolver, limits=ExecutionSettings())  # type: ignore[arg-type]
    inspector = FakeSchemaInspector(
        [
            SchemaTable(f"orders_{index:03d}", [SchemaColumn("id", "bigint", False)])
            for index in range(51)
        ]
    )
    executor.schema_inspectors = SchemaInspectorFactory({DatabaseEngine.MYSQL: inspector})

    first = executor.get_schema_directory(
        _context(),
        environment="prod",
        base="main",
        placement="cloud",
        limit=50,
    )
    assert len(first.summary["tables"]) == 50
    assert first.summary["has_more"] is True
    assert first.summary["next_cursor"]

    second = executor.get_schema_directory(
        _context(),
        environment="prod",
        base="main",
        placement="cloud",
        limit=50,
        cursor=first.summary["next_cursor"],
    )
    assert [table["name"] for table in second.summary["tables"]] == ["orders_050"]
    assert second.summary["has_more"] is False
    assert inspector.calls[-1]["after_table"] == "orders_049"

    resolver.revision = "revision-db-2"
    with pytest.raises(ToolPolicyError) as stale:
        executor.get_schema_directory(
            _context(),
            environment="prod",
            base="main",
            placement="cloud",
            limit=50,
            cursor=first.summary["next_cursor"],
        )
    assert stale.value.error_code == "mcp_pagination_cursor_stale"


def test_schema_field_truncation_does_not_create_table_cursor() -> None:
    resolver = _ResolvedDatabaseResourceResolver()
    executor = DirectReadOnlyToolExecutor(resolver, limits=ExecutionSettings())  # type: ignore[arg-type]
    inspector = FakeSchemaInspector(
        [
            SchemaTable(
                "wide_table",
                [SchemaColumn(f"column_{index}", "varchar", True) for index in range(81)],
            )
        ]
    )
    executor.schema_inspectors = SchemaInspectorFactory({DatabaseEngine.MYSQL: inspector})

    result = executor.get_schema_directory(
        _context(),
        environment="prod",
        base="main",
        limit=50,
    )

    assert result.summary["has_more"] is False
    assert result.summary["columns_truncated"] is True
    assert result.summary["next_cursor"] == ""
    assert result.truncated is True


class _ResolvedRedisResourceResolver:
    def __init__(self) -> None:
        self.revision = "revision-redis-1"

    def resolve(self, **_: object) -> ResolvedToolResource:
        redis = RedisConnection(host="redis.internal", port=6379)
        base = Base(code="main", engine=DatabaseEngine.MYSQL, redis=redis)
        binding = ResourceBinding(
            environment=Environment(code="prod", bases={"main": base}),
            base=base,
            kind=ResourceKind.REDIS,
            workshop=None,
            engine=DatabaseEngine.MYSQL,
            redis=redis,
        )
        return ResolvedToolResource(
            resource_id="resource-redis",
            resource_code="redis-main",
            resource_revision_id=self.revision,
            resource_content_hash=("f" * 64 if self.revision.endswith("1") else "1" * 64),
            placement="cloud",
            table_prefix="",
            redis_namespace_prefixes=("mes:",),
            loki_selector_conditions=(),
            scope_target=("prod", "main", ""),
            binding=binding,
        )


def test_redis_scan_wraps_and_resumes_provider_cursor() -> None:
    resolver = _ResolvedRedisResourceResolver()
    executor = DirectReadOnlyToolExecutor(resolver, limits=ExecutionSettings(redis_scan_limit=2))  # type: ignore[arg-type]
    executor.redis = FakeRedisGateway(keys=["mes:a", "mes:b", "mes:c"])  # type: ignore[assignment]

    first = executor.query_redis_scan(
        "ignored",
        "mes:*",
        2,
        _context(),
        environment="prod",
        base="main",
        placement="cloud",
    )
    assert first.summary["keys"] == ["mes:a", "mes:b"]
    assert first.summary["has_more"] is True
    assert first.summary["next_cursor"]

    second = executor.query_redis_scan(
        "ignored",
        "mes:*",
        2,
        _context(),
        environment="prod",
        base="main",
        placement="cloud",
        cursor=first.summary["next_cursor"],
    )
    assert second.summary["keys"] == ["mes:c"]
    assert second.summary["has_more"] is False
    assert second.summary["next_cursor"] == ""

    with pytest.raises(ToolPolicyError) as changed_pattern:
        executor.query_redis_scan(
            "ignored",
            "mes:other*",
            2,
            _context(),
            environment="prod",
            base="main",
            placement="cloud",
            cursor=first.summary["next_cursor"],
        )
    assert changed_pattern.value.error_code == "mcp_pagination_cursor_invalid"

    resolver.revision = "revision-redis-2"
    with pytest.raises(ToolPolicyError) as stale:
        executor.query_redis_scan(
            "ignored",
            "mes:*",
            2,
            _context(),
            environment="prod",
            base="main",
            placement="cloud",
            cursor=first.summary["next_cursor"],
        )
    assert stale.value.error_code == "mcp_pagination_cursor_stale"


@pytest.mark.parametrize("next_provider_cursor", [0, 29])
def test_real_gateway_opaque_cursor_drains_51_keys_and_rejects_context_changes(
    next_provider_cursor: int,
) -> None:
    resolver = _ResolvedRedisResourceResolver()
    executor = DirectReadOnlyToolExecutor(resolver, limits=ExecutionSettings())  # type: ignore[arg-type]
    gateway = RealRedisGateway()
    executor.redis = gateway
    client = MagicMock()
    # Long keys must not be embedded into the 4096-character public cursor.
    keys = [f"mes:{index:03d}:" + "x" * 500 for index in range(51)]
    client.scan.return_value = (next_provider_cursor, keys)
    options = dict(environment="prod", base="main", placement="cloud")
    with patch.object(gateway, "_connect", return_value=client) as connect:
        first = executor.query_redis_scan("ignored", "mes:*", 50, _context(), **options)
        cursor = first.summary["next_cursor"]
        assert first.summary["keys"] == keys[:50]
        assert first.summary["has_more"] is True
        assert 0 < len(cursor) <= ToolPaginationCursorCodec.MAX_CURSOR_CHARS
        for context in (
            replace(_context(), job_id="another-job"),
            replace(_context(), user_id="another-user"),
            replace(_context(), application_id="another-app"),
            replace(_context(), authorization_hash="d" * 64),
            replace(_context(), snapshot_hash="e" * 64),
        ):
            with pytest.raises(ToolPolicyError) as rejected:
                executor.query_redis_scan("ignored", "mes:*", 50, context, cursor=cursor, **options)
            assert rejected.value.error_code == "mcp_pagination_cursor_invalid"
        with pytest.raises(ToolPolicyError):
            executor.query_redis_scan("ignored", "mes:*", 49, _context(), cursor=cursor, **options)
        assert connect.call_count == 1  # Reject before any new provider scan.
        resolver.revision = "revision-redis-2"
        with pytest.raises(ToolPolicyError) as stale:
            executor.query_redis_scan("ignored", "mes:*", 50, _context(), cursor=cursor, **options)
        assert stale.value.error_code == "mcp_pagination_cursor_stale"
        assert connect.call_count == 1
        resolver.revision = "revision-redis-1"
        second = executor.query_redis_scan(
            "ignored", "mes:*", 50, _context(), cursor=cursor, **options
        )
        assert second.summary["keys"] == keys[50:]
        assert second.summary["has_more"] is bool(next_provider_cursor)
        if next_provider_cursor:
            client.scan.return_value = (0, [])
            third = executor.query_redis_scan(
                "ignored", "mes:*", 50, _context(), cursor=second.summary["next_cursor"], **options
            )
            assert third.summary["has_more"] is False
            assert third.summary["next_cursor"] == ""
            assert client.scan.call_args.kwargs["cursor"] == next_provider_cursor
        else:
            assert second.summary["next_cursor"] == ""


@pytest.mark.parametrize("cursor", [True, -1, 2**64, 1.5, "0", {}, {"node:6379": 1}])
def test_redis_rejects_malformed_position_before_connection(cursor: object) -> None:
    resource = _ResolvedRedisResourceResolver().resolve()
    gateway = RealRedisGateway()
    with patch.object(gateway, "_connect") as connect, pytest.raises(ToolPolicyError) as rejected:
        gateway.scan(resource.binding, "mes:*", 50, cursor)
    assert rejected.value.error_code == "mcp_pagination_cursor_invalid"
    connect.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [
        ("provider_cursor", True),
        ("provider_cursor", 2**64),
        ("offset", -1),
        ("offset", 1.5),
        ("offset", 1),  # A remainder requires a batch hash.
        ("batch_hash", "f" * 64),  # A hash without a remainder is invalid.
        ("node_index", 1),  # A node index requires a topology hash.
        ("topology_hash", "private-host:6379"),
    ],
)
def test_redis_rejects_invalid_structured_position(field: str, value: object) -> None:
    from app.modules.mcp_tool_runtime.domain.redis_pagination import RedisScanPosition

    position = RedisScanPosition().as_cursor()
    position[field] = value
    test_redis_rejects_malformed_position_before_connection(position)


def test_redis_empty_batch_with_nonzero_cursor_is_not_terminal() -> None:
    resource = _ResolvedRedisResourceResolver().resolve()
    gateway = RealRedisGateway()
    client = MagicMock()
    client.scan.side_effect = [(17, []), (0, ["mes:a"])]
    with patch.object(gateway, "_connect", return_value=client):
        first = gateway.scan(resource.binding, "mes:*", 50)
        assert first.summary["keys"] == []
        assert first.truncated is True
        second = gateway.scan(resource.binding, "mes:*", 50, first.metadata["next_provider_cursor"])
    assert second.summary["keys"] == ["mes:a"]
    assert second.truncated is False
    assert client.scan.call_args.kwargs["cursor"] == 17
