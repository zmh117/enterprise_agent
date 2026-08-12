from __future__ import annotations

import hashlib
import inspect
import json
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from app.modules.agent.infrastructure.runtime_protocol import canonical_request_digest
from app.modules.agent.infrastructure.typescript_runtime_client import RuntimeGrantIssuer
from app.modules.agent.domain.runtime import (
    AgentExecutionContext,
    AgentRunRequest,
    McpRuntimeBinding,
)
from app.modules.model_connection.domain import (
    DEFAULT_MODEL_CONNECTION_CODE,
    ModelRuntimeBinding,
)
from app.python_runtime.grant import RuntimeGrantVerifier
from app.python_runtime.invocations import (
    PythonInvocationRegistry,
    PythonTerminalLedger,
)
from app.python_runtime.model_binding import (
    PythonModelBindingResolver,
    ResolvedPythonModelBinding,
)
from app.python_runtime.claude_agent_sdk_adapter import ClaudeSdk
from app.python_runtime.sdk_executor import (
    PythonExecutionOutcome,
    PythonRuntimeSdkExecutor,
    RemoteMcpClaudeCodeAgentClient,
    _normalize_tool_events,
)
from app.python_runtime.service import PythonRuntimeDependencies, create_app
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import Migrator
from app.shared.model_probe_envelope import (
    ModelProbeEnvelopeCipher,
    ModelProbeEnvelopeError,
)
from backend.tests.helpers import test_settings as build_settings
from backend.tests.helpers import container


class FakePythonExecutor:
    sdk_version = "0.2.134"
    cli_version = "2.1.226"

    def __init__(self, *, block_until_cancelled: bool = False) -> None:
        self.requests: list[dict[str, Any]] = []
        self.principal_tokens: list[str] = []
        self.started = threading.Event()
        self.block_until_cancelled = block_until_cancelled

    def execute(
        self,
        request: dict[str, Any],
        cancel_event: threading.Event,
        secret_context: Any,
    ) -> PythonExecutionOutcome:
        self.requests.append(request)
        self.principal_tokens.append(str(secret_context.principal_token))
        self.started.set()
        if self.block_until_cancelled:
            cancel_event.wait(timeout=2)
        provenance = _provenance(request)
        if cancel_event.is_set():
            return PythonExecutionOutcome(
                status="CANCELLED",
                usage={"input_tokens": 0, "output_tokens": 0},
                runtime_provenance=provenance,
                failure={
                    "code": "runtime_cancelled",
                    "retry_class": "NEVER",
                    "safe_message": "Agent 执行已取消",
                },
            )
        return PythonExecutionOutcome(
            status="SUCCEEDED",
            final_answer="python final answer",
            usage={"input_tokens": 3, "output_tokens": 2},
            runtime_provenance=provenance,
            tool_events=(
                {
                    "tool_call_id": "tool-call-1",
                    "server_code": "ones-mcp",
                    "tool_name": "ones_work_item_search",
                    "status": "SUCCEEDED",
                    "request_summary": {"project_code": "project-1"},
                    "response_summary": {"count": 1},
                    "duration_ms": 5,
                },
            ),
        )

    def probe(self, request: dict[str, Any]) -> dict[str, Any]:
        return {
            "protocol_version": "1.0",
            "runtime_kind": "python-v1",
            "probe_id": request["probe_id"],
            "success": True,
            "connection_revision_id": request["model_connection"]["revision_id"],
            "provider_host": "api.deepseek.com",
            "model": "deepseek-chat",
            "runtime_version": "0.1.0",
            "sdk_version": self.sdk_version,
            "duration_ms": 1,
        }


class FakePythonBindingResolver:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def resolve(self, revision_id: str, config_hash: str) -> ResolvedPythonModelBinding:
        self.calls.append((revision_id, config_hash))
        return ResolvedPythonModelBinding(
            binding=ModelRuntimeBinding(
                protocol="anthropic_compatible",
                base_url="https://api.deepseek.com/anthropic",
                model="deepseek-chat",
                default_opus_model="deepseek-chat",
                default_sonnet_model="deepseek-chat",
                default_haiku_model="deepseek-chat",
                subagent_model="deepseek-chat",
                effort_level="max",
                connection_id="model-connection-1",
                connection_code="default",
                connection_revision_id=revision_id,
                connection_revision=1,
                config_hash=config_hash,
                secret_ref="secret://not-projected",
            ),
            api_key="fake-provider-binding-secret",
        )


def _database(tmp_path: Path) -> Database:
    database = Database(f"sqlite:///{tmp_path / 'python-runtime.db'}")
    Migrator(database, default_migrations_dir(), migrator_build="python-runtime-test").run()
    return database


def _keys() -> tuple[bytes, bytes]:
    private = Ed25519PrivateKey.generate()
    return (
        private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
        private.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ),
    )


def _request() -> dict[str, Any]:
    path = Path("agent-runtime/contracts/v1/golden/execution-request.json")
    request = json.loads(path.read_text(encoding="utf-8"))
    request["runtime_kind"] = "python-v1"
    request["request_digest"] = canonical_request_digest(request)
    return request


def _provenance(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "runtime_kind": "python-v1",
        "runtime_version": "0.1.0",
        "protocol_version": "1.0",
        "sdk_version": "0.2.134",
        "cli_version": "2.1.226",
        "model_connection_revision_id": request["model_connection"]["revision_id"],
        "model_connection_config_hash": request["model_connection"]["config_hash"],
    }


def _token(private_key: bytes, request: dict[str, Any]) -> str:
    return RuntimeGrantIssuer(private_key).issue(request)


def _dependencies(
    tmp_path: Path,
    executor: FakePythonExecutor,
) -> tuple[PythonRuntimeDependencies, bytes]:
    database = _database(tmp_path)
    private_key, public_key = _keys()
    settings = replace(build_settings(), app_config_master_key="runtime-test-master-key")
    dependencies = PythonRuntimeDependencies(
        database=database,
        registry=PythonInvocationRegistry(executor, PythonTerminalLedger(database)),
        grant_verifier=RuntimeGrantVerifier(public_key),
        executor=cast(PythonRuntimeSdkExecutor, executor),
        model_probe_token="probe-token-" + "x" * 32,
        settings=settings,
    )
    return dependencies, private_key


def test_python_runtime_http_contract_replays_one_terminal_without_tokens(
    tmp_path: Path,
) -> None:
    executor = FakePythonExecutor()
    dependencies, private_key = _dependencies(tmp_path, executor)
    client = TestClient(create_app(dependencies))
    request = _request()
    principal = "test-only-python-principal-token"
    headers = {
        "Authorization": f"Bearer {_token(private_key, request)}",
        "X-MCP-Principal-Token": principal,
    }

    first = client.post("/internal/v1/executions", json=request, headers=headers)
    second = client.post("/internal/v1/executions", json=request, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    first_events = [json.loads(line) for line in first.text.strip().splitlines()]
    second_events = [json.loads(line) for line in second.text.strip().splitlines()]
    assert first_events == second_events
    assert [event["event_type"] for event in first_events] == [
        "execution_started",
        "tool_event",
        "terminal",
    ]
    assert first_events[-1]["payload"]["status"] == "SUCCEEDED"
    assert first_events[-1]["payload"]["final_answer"] == "python final answer"
    assert len(executor.requests) == 1
    assert executor.principal_tokens == [principal]
    serialized = json.dumps(executor.requests)
    assert "access_token" not in serialized
    assert "Authorization" not in serialized
    assert "secret_ref" not in serialized
    ledger_text = json.dumps(
        dependencies.database.execute("select * from agent_runtime_terminal_ledger")
    )
    assert principal not in ledger_text

    terminal = client.get(
        f"/internal/v1/executions/{request['invocation_id']}/terminal",
        headers=headers,
    )
    assert terminal.status_code == 200
    assert terminal.json()["status"] == "SUCCEEDED"


def test_python_runtime_rejects_missing_ones_principal_before_execution(
    tmp_path: Path,
) -> None:
    executor = FakePythonExecutor()
    dependencies, private_key = _dependencies(tmp_path, executor)
    client = TestClient(create_app(dependencies))
    request = _request()

    response = client.post(
        "/internal/v1/executions",
        json=request,
        headers={"Authorization": f"Bearer {_token(private_key, request)}"},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "runtime_principal_token_missing"
    assert executor.requests == []


def test_python_runtime_cancel_wins_once_and_ledger_recovers_after_restart(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    executor = FakePythonExecutor(block_until_cancelled=True)
    registry = PythonInvocationRegistry(executor, PythonTerminalLedger(database))
    request = _request()

    invocation = registry.acquire(request)
    assert executor.started.wait(timeout=1)
    assert invocation.cancel() is True
    events = list(invocation.stream())

    assert events[-1]["payload"]["status"] == "CANCELLED"
    assert len([event for event in events if event["event_type"] == "terminal"]) == 1
    assert invocation.cancel() is False

    replacement = FakePythonExecutor()
    recovered = PythonInvocationRegistry(
        replacement,
        PythonTerminalLedger(database),
    ).acquire(request)
    assert recovered.events() == tuple(events)
    assert replacement.requests == []


def test_python_runtime_restart_fails_orphan_without_replaying_model(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    request = _request()
    ledger = PythonTerminalLedger(database)
    assert ledger.claim(request, "runtime-before-restart").status == "CLAIMED"
    started = {
        "protocol_version": "1.0",
        "invocation_id": request["invocation_id"],
        "request_digest": request["request_digest"],
        "sequence": 1,
        "event_type": "execution_started",
        "timestamp": "2026-08-11T00:00:00Z",
        "payload": _provenance(request),
    }
    ledger.append(request, started)
    replacement = FakePythonExecutor()

    recovered = PythonInvocationRegistry(
        replacement,
        ledger,
        owner_instance_id="runtime-after-restart",
    ).acquire(request)
    events = recovered.events()

    assert replacement.requests == []
    assert len(events) == 2
    assert events[0] == started
    assert events[1]["event_type"] == "terminal"
    assert events[1]["payload"]["status"] == "FAILED"
    assert events[1]["payload"]["failure"] == {
        "code": "runtime_orphaned_invocation",
        "retry_class": "NEVER",
        "safe_message": "Agent Runtime 在执行中重启；为避免重复模型调用，本次执行已失败",
    }
    replayed = PythonInvocationRegistry(
        replacement,
        ledger,
        owner_instance_id="runtime-later-restart",
    ).acquire(request)
    assert replayed.events() == events
    assert replacement.requests == []
    assert database.execute_one("select count(*) as count from agent_runtime_terminal_ledger") == {
        "count": 1
    }
    assert database.execute_one("select count(*) as count from agent_runtime_invocation_claim") == {
        "count": 0
    }
    assert database.execute_one("select count(*) as count from agent_runtime_invocation_event") == {
        "count": 0
    }


def test_python_runtime_model_probe_and_fixed_mcp_url_boundary(tmp_path: Path) -> None:
    executor = FakePythonExecutor()
    dependencies, _private_key = _dependencies(tmp_path, executor)
    client = TestClient(create_app(dependencies))
    probe = {
        "protocol_version": "1.0",
        "runtime_kind": "python-v1",
        "probe_id": "probe-1",
        "model_connection": {"revision_id": "revision-1", "config_hash": "a" * 64},
        "timeout_seconds": 3,
    }

    response = client.post(
        "/internal/v1/model-probes",
        json=probe,
        headers={"Authorization": "Bearer " + dependencies.model_probe_token},
    )

    assert response.status_code == 200
    assert response.json()["runtime_kind"] == "python-v1"
    assert response.json()["success"] is True
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").status_code == 200

    try:
        PythonRuntimeSdkExecutor(
            cast(Any, None),
            limits=build_settings().execution,
            mcp_server_url="https://attacker.example/mcp",
            sdk_version="0.2.134",
        )
    except ValueError as exc:
        assert "fixed deployment boundary" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("arbitrary MCP URL was accepted")


def test_python_runtime_exposes_only_the_fixed_remote_tool_mcp_server() -> None:
    context = AgentExecutionContext(
        system_role="readonly diagnostic agent",
        safety_rules=["readonly"],
        user_question="inspect test data",
        project_code="project-1",
        allowed_tools=["get_schema_directory", "query_database"],
        tool_restrictions=["bounded"],
        skills={},
        retrieved_context={},
        conversation_summary="",
        publication_id="agent-publication-1",
        application_publication_id="application-publication-1",
    )
    request = AgentRunRequest(
        job_id="job-1",
        user_id="app-user-1",
        project_code="project-1",
        invocation_id="invocation-1",
        context=context,
    )
    client = RemoteMcpClaudeCodeAgentClient(
        limits=build_settings().execution,
        api_key="runtime-only-model-secret",
        mcp_server_url="http://tool-mcp:9103/mcp",
    )
    captured: dict[str, Any] = {}

    def options(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return kwargs

    sdk = ClaudeSdk(
        query=cast(Any, None),
        options=options,
        tool=cast(Any, None),
        create_sdk_mcp_server=cast(Any, None),
        tool_annotations=None,
    )
    binding = ModelRuntimeBinding(
        protocol="anthropic_compatible",
        base_url="https://api.deepseek.com/anthropic",
        model="deepseek-chat",
        default_opus_model="deepseek-chat",
        default_sonnet_model="deepseek-chat",
        default_haiku_model="deepseek-chat",
        subagent_model="deepseek-chat",
        effort_level="max",
        secret_ref="secret://not-projected",
    )

    server = client._build_mcp_server(request)
    built = client._build_options(sdk, context, server, [], binding)

    assert built == captured
    assert captured["mcp_servers"] == {
        "tool_mcp": {
            "type": "http",
            "url": "http://tool-mcp:9103/mcp",
            "headers": {
                "X-Correlation-Id": "job:job-1",
                "X-Job-Id": "job-1",
                "X-App-User-Id": "app-user-1",
                "X-Project-Code": "project-1",
                "X-Invocation-Id": "invocation-1",
                "X-Agent-Publication-Id": "agent-publication-1",
                "X-Application-Publication-Id": "application-publication-1",
            },
        }
    }
    assert captured["allowed_tools"] == [
        "mcp__tool_mcp__get_schema_directory",
        "mcp__tool_mcp__query_database",
    ]
    assert "internal" not in captured["mcp_servers"]


def test_python_runtime_routes_principal_only_to_fixed_ones_mcp_server() -> None:
    context = AgentExecutionContext(
        system_role="readonly ONES agent",
        safety_rules=["readonly"],
        user_question="search ONES work items",
        project_code="project-1",
        allowed_tools=["ones_work_item_search"],
        tool_restrictions=["bounded"],
        skills={},
        retrieved_context={},
        conversation_summary="",
        publication_id="agent-publication-1",
        application_publication_id="application-publication-1",
        mcp_bindings=(
            McpRuntimeBinding(
                server_code="ones-mcp",
                tool_name="ones_work_item_search",
                required_scope="mcp:ones-mcp:ones_work_item_search:invoke",
                tool_schema_hash="c" * 64,
            ),
        ),
    )
    request = AgentRunRequest(
        job_id="job-1",
        user_id="app-user-1",
        project_code="project-1",
        invocation_id="invocation-1",
        context=context,
    )
    principal = "test-only-principal-token"
    client = RemoteMcpClaudeCodeAgentClient(
        limits=build_settings().execution,
        api_key="runtime-only-model-secret",
        mcp_server_url="http://tool-mcp:9103/mcp",
        ones_mcp_server_url="http://ones-mcp:9104/mcp",
        principal_token=principal,
    )
    captured: dict[str, Any] = {}

    def options(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return kwargs

    sdk = ClaudeSdk(
        query=cast(Any, None),
        options=options,
        tool=cast(Any, None),
        create_sdk_mcp_server=cast(Any, None),
        tool_annotations=None,
    )
    binding = ModelRuntimeBinding(
        protocol="anthropic_compatible",
        base_url="https://api.deepseek.com/anthropic",
        model="deepseek-chat",
        default_opus_model="deepseek-chat",
        default_sonnet_model="deepseek-chat",
        default_haiku_model="deepseek-chat",
        subagent_model="deepseek-chat",
        effort_level="max",
        secret_ref="secret://not-projected",
    )

    server = client._build_mcp_server(request)
    client._build_options(sdk, context, server, [], binding)

    assert set(captured["mcp_servers"]) == {"ones_mcp"}
    assert captured["mcp_servers"]["ones_mcp"]["url"] == ("http://ones-mcp:9104/mcp")
    assert captured["mcp_servers"]["ones_mcp"]["headers"]["Authorization"] == (
        f"Bearer {principal}"
    )
    assert captured["allowed_tools"] == ["mcp__ones_mcp__ones_work_item_search"]
    assert principal not in repr(context)

    normalized = _normalize_tool_events(
        [
            {
                "tool_name": "mcp__ones_mcp__ones_work_item_search",
                "status": "SUCCEEDED",
                "request_payload": {"keyword": "test"},
                "response_summary": {"count": 1},
            }
        ],
        _request(),
    )
    assert normalized[0]["server_code"] == "ones-mcp"
    assert normalized[0]["tool_name"] == "ones_work_item_search"


def test_python_test_only_fake_provider_resolves_binding_and_retries_once() -> None:
    resolver = FakePythonBindingResolver()
    executor = PythonRuntimeSdkExecutor(
        cast(PythonModelBindingResolver, resolver),
        limits=build_settings().execution,
        mcp_server_url="http://tool-mcp:9103/mcp",
        sdk_version="0.2.134",
        cli_version="2.1.226",
        fake_provider_mode=True,
    )
    first = _request()
    first["invocation_id"] = f"{first['job_id']}.attempt-0"
    first["prompt"]["user_question"] = "[smoke:retry-once] verify retry"
    retry = executor.execute(first, threading.Event())
    second = dict(first)
    second["invocation_id"] = f"{first['job_id']}.attempt-1"
    succeeded = executor.execute(second, threading.Event())

    assert retry.status == "FAILED"
    assert retry.failure and retry.failure["retry_class"] == "TRANSIENT"
    assert succeeded.status == "SUCCEEDED"
    assert succeeded.final_answer == "Python Runtime fake-provider smoke completed."
    assert len(resolver.calls) == 2
    assert "binding-secret" not in json.dumps([retry.__dict__, succeeded.__dict__])


def test_python_runtime_resolves_only_frozen_model_revision_and_active_secret() -> None:
    runtime = container()
    runtime.model_connection_service.dns_resolver = lambda *_args, **_kwargs: [
        (2, 1, 6, "", ("8.8.8.8", 443))
    ]
    connection = runtime.model_connection_service.get(DEFAULT_MODEL_CONNECTION_CODE)
    config = {
        "schema_version": 1,
        "protocol": "anthropic_compatible",
        "base_url": "https://api.deepseek.com/anthropic",
        "model": "deepseek-chat",
        "default_opus_model": "deepseek-chat",
        "default_sonnet_model": "deepseek-chat",
        "default_haiku_model": "deepseek-chat",
        "subagent_model": "deepseek-chat",
        "effort_level": "max",
    }
    revision = runtime.model_connection_service.save_revision(
        actor_id="user_local_admin",
        code=DEFAULT_MODEL_CONNECTION_CODE,
        expected_revision=connection["revision"],
        config=config,
    )
    ready = runtime.model_connection_service.rotate_credential(
        actor_id="user_local_admin",
        code=DEFAULT_MODEL_CONNECTION_CODE,
        expected_revision=revision["revision"],
        api_key="python-runtime-only-secret-value",
    )
    private_revision = runtime.model_connection_service.repository.get_revision(ready["id"])
    resolver = PythonModelBindingResolver(
        runtime.database,
        master_key=runtime.settings.app_config_master_key,
        allowed_hosts=("api.deepseek.com",),
    )

    resolved = resolver.resolve(str(ready["id"]), str(private_revision["config_hash"]))

    assert resolved.binding.connection_revision_id == ready["id"]
    assert resolved.binding.config_hash == private_revision["config_hash"]
    assert resolved.api_key == "python-runtime-only-secret-value"
    assert "python-runtime-only-secret-value" not in json.dumps(
        resolved.binding.public_provenance()
    )
    resolver_source = inspect.getsource(PythonModelBindingResolver.resolve).lower()
    assert "select r.*" not in resolver_source
    assert "select s.*" not in resolver_source


def test_python_runtime_decrypts_draft_probe_once_without_persisting_credential(
    tmp_path: Path,
) -> None:
    master_key = "python-draft-probe-test-master-key"
    config = {
        "schema_version": 1,
        "protocol": "anthropic_compatible",
        "base_url": "https://api.deepseek.com/anthropic",
        "model": "deepseek-chat",
        "default_opus_model": "deepseek-chat",
        "default_sonnet_model": "deepseek-chat",
        "default_haiku_model": "deepseek-chat",
        "subagent_model": "deepseek-chat",
        "effort_level": "max",
    }
    config_hash = hashlib.sha256(
        json.dumps(
            config,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    request: dict[str, Any] = {
        "protocol_version": "1.0",
        "runtime_kind": "python-v1",
        "probe_id": "probe-python-draft-test",
        "config_hash": config_hash,
        "timeout_seconds": 15,
    }
    request["credential_envelope"] = ModelProbeEnvelopeCipher(master_key).encrypt(
        probe_id=request["probe_id"],
        runtime_kind=request["runtime_kind"],
        config_hash=config_hash,
        config=config,
        api_key="fixture-python-draft-key",
        lifetime_seconds=30,
    )
    resolver = PythonModelBindingResolver(
        _database(tmp_path),
        master_key=master_key,
        allowed_hosts=("api.deepseek.com",),
        dns_resolver=lambda *_args, **_kwargs: [(2, 1, 6, "", ("8.8.8.8", 443))],
    )

    resolved = resolver.resolve_draft(request)

    assert resolved.binding.connection_revision_id == "draft-probe-python-draft-test"
    assert resolved.api_key == "fixture-python-draft-key"
    assert "fixture-python-draft-key" not in json.dumps(request)
    assert "deepseek-chat" not in json.dumps(request)
    try:
        resolver.resolve_draft(request)
    except ModelProbeEnvelopeError:
        pass
    else:  # pragma: no cover
        raise AssertionError("draft probe envelope replay was accepted")
