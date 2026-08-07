from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi.testclient import TestClient

from app.bootstrap import build_test_container
from app.modules.agent.infrastructure.claude_code_agent_client import (
    ClaudeSdk,
    RealClaudeCodeAgentClient,
)
from app.modules.internal_api_platform.app import create_app as create_internal_api_app
from app.modules.internal_api_platform.application.platform_service import PlatformService
from app.modules.internal_api_platform.domain.access import AccessPolicy
from app.modules.internal_api_platform.domain.addressing import RevisionResource
from app.modules.internal_api_platform.domain.schema_directory import (
    SchemaColumn,
    SchemaTable,
)
from app.modules.internal_api_platform.domain.topology import (
    Base,
    DatabaseConnection,
    DatabaseEngine,
    Environment,
    LokiConnection,
    RedisConnection,
    ResourceKind,
    Topology,
)
from app.modules.internal_api_platform.infrastructure.db.executor import FakeQueryExecutor
from app.modules.internal_api_platform.infrastructure.db.schema_directory import (
    FakeSchemaInspector,
    SchemaInspectorFactory,
)
from app.modules.internal_api_platform.infrastructure.job_authorization import (
    BusinessApplicationJobAccessAuthorizer,
)
from app.modules.internal_api_platform.infrastructure.loki_gateway import FakeLokiClient
from app.modules.internal_api_platform.infrastructure.redis_gateway import FakeRedisGateway
from app.modules.internal_api_platform.infrastructure.registry import TopologyRegistry
from app.modules.internal_tools.infrastructure.internal_api_client import HttpInternalApiClient
from app.modules.job.domain.job_status import JobStatus
from app.shared.config import Settings
from app.workers.agent_job_worker import AgentJobWorker
from backend.tests.helpers import (
    dispatch_pending_deliveries,
    prepare_debug_application_access,
    publish_pending_agent_jobs,
)
from backend.tests.test_business_application_control_plane import control_plane_settings


SERVICE_TOKEN = "builtin-tool-e2e-token-0000000001"


class _FakeOptions:
    def __init__(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


def _fake_tool(
    name: str,
    description: str,
    schema: dict[str, Any],
    **kwargs: Any,
) -> Any:
    def decorator(handler: Any) -> Any:
        handler.tool_name = name
        handler.description = description
        handler.schema = schema
        handler.annotations = kwargs.get("annotations")
        return handler

    return decorator


def _fake_server(name: str, tools: list[Any]) -> dict[str, Any]:
    return {"name": name, "tools": {tool.tool_name: tool for tool in tools}}


class _BridgeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> _BridgeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


class _SharedDatabaseJobAuthorizer(BusinessApplicationJobAccessAuthorizer):
    def close(self) -> None:
        # The acceptance PlatformService shares the Runtime's in-memory database.
        # The Runtime owns that connection and closes it after all evidence checks.
        return None


class _RecordingDeliveryAdapter:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def send(self, **kwargs: object) -> None:
        self.calls.append(kwargs)


def _revision_resources(
    *,
    candidates: dict[str, dict[str, object]],
    database: DatabaseConnection,
    redis: RedisConnection,
    loki: LokiConnection,
) -> dict[str, RevisionResource]:
    return {
        str(candidates["database"]["resource_revision_id"]): RevisionResource(
            resource_revision_id=str(candidates["database"]["resource_revision_id"]),
            resource_id="e2e-database-resource",
            environment_code="local",
            base_code="debug-base",
            workshop_code="",
            kind=ResourceKind.DATABASE,
            engine=DatabaseEngine.MYSQL,
            database=database,
        ),
        str(candidates["redis"]["resource_revision_id"]): RevisionResource(
            resource_revision_id=str(candidates["redis"]["resource_revision_id"]),
            resource_id="e2e-redis-resource",
            environment_code="local",
            base_code="debug-base",
            workshop_code="",
            kind=ResourceKind.REDIS,
            engine=DatabaseEngine.MYSQL,
            redis=redis,
        ),
        str(candidates["loki"]["resource_revision_id"]): RevisionResource(
            resource_revision_id=str(candidates["loki"]["resource_revision_id"]),
            resource_id="e2e-loki-resource",
            environment_code="local",
            base_code="",
            workshop_code="",
            kind=ResourceKind.LOKI,
            engine=DatabaseEngine.MYSQL,
            loki=loki,
        ),
    }


def test_runtime_worker_internal_platform_tools_and_delivery_chain(tmp_path: Path) -> None:
    runtime = build_test_container(control_plane_settings(), migrate=True, seed=True)
    capabilities = ("query_database", "query_redis_get", "query_loki")
    selection = prepare_debug_application_access(
        runtime,
        application_code="builtin-tool-runtime-e2e",
        role_code="builtin-tool-runtime-e2e-role",
        capabilities=capabilities,
        additional_deliveries=(
            {
                "delivery_type": "dingtalk_group",
                "connector_id": "connector-dingtalk-enterprise-default",
                "enabled": True,
                "config": {
                    "target_reference": "open-conversation-e2e",
                    "reply_mode": "fixed",
                },
            },
        ),
    )
    job, _ = runtime.debug_job_access_service.create_job(
        user_id="user_local_admin",
        display_name="本地管理员",
        message="验证数据库、Redis、Loki 只读工具完整链",
        application_id=selection["application_id"],
        execution_scope_id=selection["execution_scope_id"],
        delivery_binding_id=selection["delivery_binding_id"],
        idempotency_key="builtin-tool-runtime-e2e",
        correlation_id="correlation-builtin-tool-runtime-e2e",
    )

    frozen = runtime.builtin_tool_snapshot_service.verify(job.id)
    candidates = {
        str(candidate["resource_kind"]): dict(candidate)
        for binding in frozen["snapshot"]["bindings"]
        for candidate in binding["candidates"]
    }
    assert set(candidates) == {"database", "redis", "loki"}

    database_connection = DatabaseConnection(
        host="database.test",
        port=3306,
        database="diagnostic",
        user="readonly",
        password="not-used-by-fake",
    )
    redis_connection = RedisConnection(host="redis.test", port=6379)
    loki_connection = LokiConnection(base_url="http://loki.test:3100")
    base = Base(
        code="debug-base",
        engine=DatabaseEngine.MYSQL,
        database=database_connection,
        redis=redis_connection,
        loki=loki_connection,
    )
    topology = Topology(
        environments={
            "local": Environment(code="local", bases={"debug-base": base})
        }
    )
    database_executor = FakeQueryExecutor(rows=[{"result": "database-ok"}])
    redis_gateway = FakeRedisGateway(values={"order:1": "redis-ok"})
    loki_client = FakeLokiClient(highlights=["loki-ok"])
    platform = PlatformService(
        registry=TopologyRegistry(
            topology,
            revision_resources=_revision_resources(
                candidates=candidates,
                database=database_connection,
                redis=redis_connection,
                loki=loki_connection,
            ),
        ),
        access_policy=AccessPolicy(),
        executors={DatabaseEngine.MYSQL: database_executor},
        schema_inspector_factory=SchemaInspectorFactory(
            {
                DatabaseEngine.MYSQL: FakeSchemaInspector(
                    tables=[
                        SchemaTable(
                            name="diagnostic_result",
                            columns=[
                                SchemaColumn(
                                    name="result",
                                    data_type="varchar",
                                    nullable=False,
                                )
                            ],
                        )
                    ]
                )
            }
        ),
        redis_gateway=redis_gateway,
        loki_client=loki_client,
        job_access_authorizer=_SharedDatabaseJobAuthorizer(runtime.database),
    )

    token_path = tmp_path / "internal-api-token.json"
    token_path.write_text(json.dumps({"current": SERVICE_TOKEN}), encoding="utf-8")
    internal_app = create_internal_api_app(
        Settings(
            environment="test",
            internal_api_auth_token_file=str(token_path),
        ),
        service=platform,
    )
    delivery_adapter = _RecordingDeliveryAdapter()
    runtime.result_delivery_service.adapters["dingtalk_enterprise_robot"] = delivery_adapter

    async def model_query(prompt: str, options: _FakeOptions) -> Any:
        del prompt
        tools = options.mcp_servers["internal"]["tools"]
        await tools["query_database"](
            {"sql": "select result from diagnostic_result", "limit": 5}
        )
        await tools["query_redis_get"]({"key": "order:1"})
        await tools["query_loki"](
            {
                "selector": {"service": "orders"},
                "query": "failed",
                "minutes": 5,
                "limit": 5,
            }
        )
        yield {"result": "数据库、Redis、Loki 证据均已获取"}

    with TestClient(internal_app) as internal_client:

        def bridge_urlopen(request: object, *, timeout: int) -> _BridgeResponse:
            assert timeout == runtime.settings.internal_api_timeout_seconds
            parsed = urlparse(str(getattr(request, "full_url")))
            response = internal_client.request(
                str(getattr(request, "method")),
                f"{parsed.path}?{parsed.query}" if parsed.query else parsed.path,
                content=getattr(request, "data"),
                headers=dict(getattr(request, "header_items")()),
            )
            assert response.status_code == 200, response.text
            return _BridgeResponse(response.content)

        runtime.tool_service.internal_api_client = HttpInternalApiClient(
            "http://internal-api.test",
            auth_token=SERVICE_TOKEN,
            timeout_seconds=runtime.settings.internal_api_timeout_seconds,
            urlopen_func=bridge_urlopen,
        )
        runtime.agent_executor.claude_client = RealClaudeCodeAgentClient(
            model="acceptance-model",
            tool_registry=runtime.agent_executor.tool_registry,
            limits=runtime.settings.execution,
            api_key="sk-acceptance-valid-shaped-value",
            sdk_loader=lambda: ClaudeSdk(
                query=model_query,
                options=_FakeOptions,
                tool=_fake_tool,
                create_sdk_mcp_server=_fake_server,
                tool_annotations=None,
            ),
        )

        publish_pending_agent_jobs(runtime)
        AgentJobWorker(runtime.settings, container=runtime).run_once()
        dispatch_pending_deliveries(runtime)

    persisted = runtime.agent_repository.get_job(job.id)
    assert persisted.status is JobStatus.SUCCEEDED
    assert persisted.business_application_publication_id == selection["publication_id"]
    assert runtime.builtin_tool_snapshot_service.verify(job.id)["snapshot_hash"] == frozen[
        "snapshot_hash"
    ]

    tool_calls = runtime.agent_repository.list_tool_calls(job.id)
    assert [call["tool_name"] for call in tool_calls] == list(capabilities)
    assert [call["status"] for call in tool_calls] == ["SUCCEEDED"] * 3, [
        (call["tool_name"], call["response_summary"]) for call in tool_calls
    ]
    assert all(call["audit_id"] for call in tool_calls), [
        (call["tool_name"], call["audit_id"]) for call in tool_calls
    ]
    assert len(database_executor.calls) == 1
    assert redis_gateway.calls == [("get", "order:1")]
    assert loki_client.calls[0]["selector"] == {
        "customer": "local",
        "service": "orders",
    }

    facts = runtime.database.execute(
        """
        select authorization_decision, decision_reason_code,
               resource_revision_id, effective_scope_hash,
               effective_selector_hash
          from agent_tool_call_builtin_tool_fact fact
          join agent_tool_call call on call.id = fact.tool_call_id
         where call.job_id = ?
         order by call.created_at, call.id
        """,
        (job.id,),
    )
    assert len(facts) == 3
    assert all(fact["authorization_decision"] == "ALLOWED" for fact in facts)
    assert all(fact["decision_reason_code"] == "exact_job_snapshot_allowed" for fact in facts)
    assert all(fact["resource_revision_id"] for fact in facts)
    assert all(fact["effective_scope_hash"] for fact in facts)

    audit_types = {
        row["event_type"]
        for row in runtime.database.execute(
            "select event_type from audit_event where job_id = ?",
            (job.id,),
        )
    }
    assert {"worker.claimed", "result.delivery.requested", "delivery.completed"} <= audit_types, (
        sorted(audit_types)
    )
    attempts = runtime.agent_repository.list_delivery_attempts(job.id)
    assert len(attempts) == 1
    assert attempts[0]["status"] == "SUCCEEDED"
    assert attempts[0]["delivery_outbox_id"]
    assert len(delivery_adapter.calls) == 1

    runtime.database.close()
