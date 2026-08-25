from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import json
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request as StarletteRequest

from app.modules.agent.infrastructure.runtime_protocol import (
    CURRENT_RUNTIME_PROTOCOL_VERSION,
    SUPPORTED_RUNTIME_PROTOCOL_VERSIONS,
    canonical_request_digest,
)
from app.modules.agent.infrastructure.runtime_http_client import RuntimeGrantIssuer
from app.modules.mcp_tool_runtime import ONES_MCP_SERVER_CODE
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
from app.python_runtime.job_sandbox import JobSandboxLimits, JobSandboxManager
from app.python_runtime.claude_client import ClaudeSdk, ClaudeSdkClient, build_system_prompt
from app.python_runtime.mcp_config import FixedMcpClaudeSdkClient
from app.python_runtime.sdk_event_normalizer import extract_tool_events
from app.python_runtime.executor import (
    PythonExecutionOutcome,
    PythonRuntimeExecutor,
    agent_request_from_runtime_request,
)
from app.python_runtime.error_mapper import redact_sensitive_text as redact_runtime_error
from app.python_runtime.tool_policy import normalize_tool_events
from app.python_runtime.tool_contract import build_tool_contract_observation
from app.python_runtime.service import (
    PythonRuntimeDependencies,
    _principal_secret_context,
    create_app,
)
from app.shared.database import Database, default_migrations_dir
from app.shared.exceptions import NonRetryableExecutionError, RetryableExecutionError
from app.shared.build_identity import BuildIdentity
from app.shared.migrations import Migrator
from app.shared.model_probe_envelope import (
    ModelProbeEnvelopeCipher,
    ModelProbeEnvelopeError,
)
from backend.tests.business_mcp_fixtures import (
    TEST_BUSINESS_SERVER_CODE,
    TEST_BUSINESS_TOOL_IDENTIFIER,
    business_mcp_test_policies,
)
from backend.tests.support.runtime import container, test_settings as build_settings


class FakePythonExecutor:
    sdk_version = "0.2.134"
    cli_version = "2.1.226"

    def __init__(self, *, block_until_cancelled: bool = False) -> None:
        self.requests: list[dict[str, Any]] = []
        self.mcp_principal_tokens: list[dict[str, str]] = []
        self.started = threading.Event()
        self.block_until_cancelled = block_until_cancelled

    def execute(
        self,
        request: dict[str, Any],
        cancel_event: threading.Event,
        secret_context: Any,
        tool_contract_observer: Any = None,
    ) -> PythonExecutionOutcome:
        self.requests.append(request)
        self.mcp_principal_tokens.append(dict(secret_context.mcp_principal_tokens))
        if tool_contract_observer is not None:
            tool_contract_observer(
                build_tool_contract_observation(
                    agent_request_from_runtime_request(request, None).context,
                    file_live=None,
                    runtime_build_identity=BuildIdentity(
                        component="python-runtime",
                        source_revision="test-revision",
                        build_id="test-build",
                        platform="linux/amd64",
                    ),
                )
            )
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
            runtime_events=(
                {
                    "event_type": "runtime_initialized",
                    "payload": {"model_id": "claude-safe-model", "mcp_servers": []},
                },
                {
                    "event_type": "model_call",
                    "payload": {
                        "model_call_id": "python-message-safe-1",
                        "provider_request_id": None,
                        "provider_message_id": "python-message-safe-1",
                        "model_id": "claude-safe-model",
                        "status": "SUCCEEDED",
                        "started_at": None,
                        "completed_at": "2026-08-12T00:00:01Z",
                        "duration_ms": None,
                        "duration_source": "UNAVAILABLE",
                        "usage": {
                            "input_tokens": 3,
                            "output_tokens": 2,
                            "cache_read_input_tokens": 0,
                            "cache_creation_input_tokens": 0,
                        },
                        "stop_reason": "end_turn",
                        "error_code": None,
                        "error_summary": None,
                    },
                },
            ),
            accounting={
                "status": "COMPLETE",
                "duration_ms": 20,
                "duration_api_ms": 10,
                "num_turns": 1,
                "usage": {
                    "input_tokens": 3,
                    "output_tokens": 2,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                },
                "model_usage": [],
                "estimated_cost_usd": 0.001,
                "permission_denials_count": 0,
            },
            tool_events=(
                {
                    "tool_call_id": "tool-call-1",
                    "server_code": "ones-mcp",
                    "tool_origin": "mcp",
                    "mcp_call_id": "mcp-call-1",
                    "persisted_tool_call_id": "agent-tool-call-1",
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
            "protocol_version": CURRENT_RUNTIME_PROTOCOL_VERSION,
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
    path = Path("contracts/agent-runtime/v1.4/golden/execution-request.json")
    request = json.loads(path.read_text(encoding="utf-8"))
    request["runtime_kind"] = "python-v1"
    request["request_digest"] = canonical_request_digest(request)
    return request


def _current_request() -> dict[str, Any]:
    path = Path("contracts/agent-runtime/v1.4/golden/execution-request.json")
    request = json.loads(path.read_text(encoding="utf-8"))
    request["runtime_kind"] = "python-v1"
    request["mcp_servers"] = []
    request["request_digest"] = canonical_request_digest(request)
    return request


def _request_for_version(protocol_version: str) -> dict[str, Any]:
    assert protocol_version == "1.4"
    path = Path("contracts/agent-runtime/v1.4/golden/execution-request.json")
    request = json.loads(path.read_text(encoding="utf-8"))
    request["runtime_kind"] = "python-v1"
    request["mcp_servers"] = []
    request["request_digest"] = canonical_request_digest(request)
    return request


def _provenance(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "runtime_kind": "python-v1",
        "runtime_version": "0.1.0",
        "protocol_version": request["protocol_version"],
        "sdk_version": "0.2.134",
        "cli_version": "2.1.226",
        "runtime_build_identity": {
            "component": "python-runtime",
            "source_revision": "test-revision",
            "build_id": "test-build",
            "platform": "linux/amd64",
        },
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
        executor=cast(PythonRuntimeExecutor, executor),
        model_probe_token="probe-token-" + "x" * 32,
        settings=settings,
        sandbox_manager=JobSandboxManager(tmp_path / "runtime-sandboxes"),
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
        "X-MCP-Principal-Token-Ones-Mcp": principal,
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
        "tool_contract_observed",
        "runtime_initialized",
        "model_call",
        "tool_event",
        "terminal",
    ]
    assert first_events[-1]["payload"]["status"] == "SUCCEEDED"
    assert first_events[-1]["payload"]["final_answer"] == "python final answer"
    assert len(executor.requests) == 1
    assert executor.mcp_principal_tokens == [{ONES_MCP_SERVER_CODE: principal}]
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


@pytest.mark.parametrize("protocol_version", SUPPORTED_RUNTIME_PROTOCOL_VERSIONS)
def test_python_runtime_accepts_replays_and_rejects_digest_conflict_for_current_version(
    tmp_path: Path,
    protocol_version: str,
) -> None:
    executor = FakePythonExecutor()
    dependencies, private_key = _dependencies(tmp_path, executor)
    client = TestClient(create_app(dependencies))
    request = _request_for_version(protocol_version)
    headers = {"Authorization": f"Bearer {_token(private_key, request)}"}

    first = client.post("/internal/v1/executions", json=request, headers=headers)
    replay = client.post("/internal/v1/executions", json=request, headers=headers)

    assert first.status_code == 200
    assert replay.text == first.text
    events = [json.loads(line) for line in first.text.strip().splitlines()]
    assert events[0]["event_type"] == "execution_started"
    assert events[-1]["event_type"] == "terminal"
    assert events[-1]["payload"]["status"] == "SUCCEEDED"
    assert len(executor.requests) == 1

    conflicting = copy.deepcopy(request)
    conflicting["prompt"]["user_question"] = "conflicting request"
    conflicting["request_digest"] = canonical_request_digest(conflicting)
    conflict = client.post(
        "/internal/v1/executions",
        json=conflicting,
        headers={"Authorization": f"Bearer {_token(private_key, conflicting)}"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "runtime_invocation_conflict"


def test_python_runtime_rejects_invalid_or_cross_release_component_identity(
    tmp_path: Path,
) -> None:
    executor = FakePythonExecutor()
    dependencies, private_key = _dependencies(tmp_path, executor)
    client = TestClient(create_app(dependencies))

    cross_release = _current_request()
    cross_release["worker_build_identity"]["build_id"] = "different-build"
    cross_release["request_digest"] = canonical_request_digest(cross_release)
    mismatch = client.post(
        "/internal/v1/executions",
        json=cross_release,
        headers={"Authorization": f"Bearer {_token(private_key, cross_release)}"},
    )

    invalid = _current_request()
    invalid["control_plane_build_identity"]["component"] = "agent-worker"
    invalid["request_digest"] = canonical_request_digest(invalid)
    malformed = client.post(
        "/internal/v1/executions",
        json=invalid,
        headers={"Authorization": f"Bearer {_token(private_key, invalid)}"},
    )

    assert mismatch.status_code == 409
    assert mismatch.json()["detail"]["code"] == "runtime_build_identity_mismatch"
    assert malformed.status_code == 400
    assert malformed.json()["detail"]["code"] == "runtime_build_identity_invalid"
    assert executor.requests == []


def test_python_runtime_streams_observability_before_accounting_terminal(
    tmp_path: Path,
) -> None:
    executor = FakePythonExecutor()
    dependencies, private_key = _dependencies(tmp_path, executor)
    client = TestClient(create_app(dependencies))
    request = _current_request()

    response = client.post(
        "/internal/v1/executions",
        json=request,
        headers={"Authorization": f"Bearer {_token(private_key, request)}"},
    )
    replay = client.post(
        "/internal/v1/executions",
        json=request,
        headers={"Authorization": f"Bearer {_token(private_key, request)}"},
    )

    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.strip().splitlines()]
    assert [event["event_type"] for event in events] == [
        "execution_started",
        "tool_contract_observed",
        "runtime_initialized",
        "model_call",
        "tool_event",
        "terminal",
    ]
    terminal = events[-1]["payload"]
    assert terminal["accounting"]["status"] == "COMPLETE"
    assert terminal["accounting"]["estimated_cost_usd"] == 0.001
    assert replay.text == response.text
    assert len(executor.requests) == 1


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


def _raw_header_request(headers: list[tuple[bytes, bytes]]) -> StarletteRequest:
    return StarletteRequest({"type": "http", "headers": headers})


def test_python_runtime_parses_exact_dual_business_principal_header_set() -> None:
    payload = _request()
    payload["mcp_servers"] = [
        *payload["mcp_servers"],
        {
            "server_code": TEST_BUSINESS_SERVER_CODE,
            "tools": [{"tool_name": TEST_BUSINESS_TOOL_IDENTIFIER}],
        },
    ]
    context = _principal_secret_context(
        _raw_header_request(
            [
                (b"x-mcp-principal-token-ones-mcp", b"ones-audience-token"),
                (
                    b"x-mcp-principal-token-test-business-mcp",
                    b"second-audience-token",
                ),
            ]
        ),
        payload,
        server_policies=business_mcp_test_policies(),
    )

    assert dict(context.mcp_principal_tokens) == {
        ONES_MCP_SERVER_CODE: "ones-audience-token",
        TEST_BUSINESS_SERVER_CODE: "second-audience-token",
    }
    assert "ones-audience-token" not in repr(context)
    with pytest.raises(TypeError):
        cast(dict[str, str], context.mcp_principal_tokens)[ONES_MCP_SERVER_CODE] = "reused"


def test_python_runtime_http_keeps_dual_business_tokens_out_of_request_and_ledger(
    tmp_path: Path,
) -> None:
    executor = FakePythonExecutor()
    dependencies, private_key = _dependencies(tmp_path, executor)
    dependencies.server_policies = business_mcp_test_policies()
    request = json.loads(
        Path("contracts/agent-runtime/v1.4/golden/execution-request.json").read_text(
            encoding="utf-8"
        )
    )
    request["runtime_kind"] = "python-v1"
    request["mcp_servers"].append(
        {
            "server_code": TEST_BUSINESS_SERVER_CODE,
            "tools": [
                {
                    "tool_name": TEST_BUSINESS_TOOL_IDENTIFIER,
                    "required_scope": (
                        f"mcp:{TEST_BUSINESS_SERVER_CODE}:{TEST_BUSINESS_TOOL_IDENTIFIER}:invoke"
                    ),
                    "tool_schema_hash": "d" * 64,
                }
            ],
        }
    )
    request["request_digest"] = canonical_request_digest(request)
    ones_token = "ones-runtime-only-token"
    second_token = "second-runtime-only-token"

    response = TestClient(create_app(dependencies)).post(
        "/internal/v1/executions",
        json=request,
        headers={
            "Authorization": f"Bearer {_token(private_key, request)}",
            "X-MCP-Principal-Token-Ones-Mcp": ones_token,
            "X-MCP-Principal-Token-Test-Business-Mcp": second_token,
        },
    )

    assert response.status_code == 200
    assert executor.mcp_principal_tokens == [
        {
            ONES_MCP_SERVER_CODE: ones_token,
            TEST_BUSINESS_SERVER_CODE: second_token,
        }
    ]
    serialized_request = json.dumps(executor.requests)
    serialized_ledger = json.dumps(
        dependencies.database.execute("select * from agent_runtime_terminal_ledger")
    )
    assert ones_token not in serialized_request + serialized_ledger + response.text
    assert second_token not in serialized_request + serialized_ledger + response.text


@pytest.mark.parametrize(
    ("headers", "expected_code"),
    [
        (
            [(b"x-mcp-principal-token", b"legacy-single-slot")],
            "runtime_principal_token_invalid",
        ),
        (
            [
                (b"x-mcp-principal-token-ones-mcp", b"first"),
                (b"x-mcp-principal-token-ones-mcp", b"duplicate"),
            ],
            "runtime_principal_token_invalid",
        ),
        (
            [(b"x-mcp-principal-token-ones_mcp", b"illegal-name")],
            "runtime_principal_token_invalid",
        ),
        (
            [(b"x-mcp-principal-token-ones-mcp", b"")],
            "runtime_principal_token_invalid",
        ),
        (
            [(b"x-mcp-principal-token-ones-mcp", b"a" * 8193)],
            "runtime_principal_token_invalid",
        ),
        (
            [(b"x-mcp-principal-token-ones-mcp", b"line-one\r\nline-two")],
            "runtime_principal_token_invalid",
        ),
    ],
)
def test_python_runtime_rejects_invalid_business_principal_headers(
    headers: list[tuple[bytes, bytes]],
    expected_code: str,
) -> None:
    with pytest.raises(HTTPException) as captured:
        _principal_secret_context(_raw_header_request(headers), _request())

    assert captured.value.status_code == 401
    assert cast(dict[str, str], captured.value.detail)["code"] == expected_code
    assert not any(
        value and value.decode("ascii", errors="ignore") in str(captured.value.detail)
        for _, value in headers
    )


def test_python_runtime_rejects_known_extra_business_principal_header() -> None:
    with pytest.raises(HTTPException) as captured:
        _principal_secret_context(
            _raw_header_request(
                [
                    (b"x-mcp-principal-token-ones-mcp", b"ones-token"),
                    (
                        b"x-mcp-principal-token-test-business-mcp",
                        b"extra-token",
                    ),
                ]
            ),
            _request(),
            server_policies=business_mcp_test_policies(),
        )

    assert captured.value.status_code == 401
    assert cast(dict[str, str], captured.value.detail)["code"] == (
        "runtime_principal_token_unexpected"
    )


def test_python_runtime_error_redaction_covers_per_server_and_file_headers() -> None:
    business_token = "business-token-must-not-survive"
    file_token = "file-token-must-not-survive"
    redacted = redact_runtime_error(
        "{'X-MCP-Principal-Token-Ones-Mcp': '"
        + business_token
        + "', 'X-File-Principal-Token': '"
        + file_token
        + "'}"
    )

    assert business_token not in redacted
    assert file_token not in redacted
    assert redacted.count("<redacted>") == 2


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


def test_python_runtime_streams_tool_contract_before_executor_continues(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    executor = FakePythonExecutor(block_until_cancelled=True)
    registry = PythonInvocationRegistry(executor, PythonTerminalLedger(database))
    invocation = registry.acquire(_request())

    assert executor.started.wait(timeout=1)
    assert [event["event_type"] for event in invocation.events()] == [
        "execution_started",
        "tool_contract_observed",
    ]
    assert invocation.events()[1]["payload"]["status"] == "MATCH"

    assert invocation.cancel() is True
    events = list(invocation.stream())
    assert events[-1]["event_type"] == "terminal"
    assert events[-1]["payload"]["status"] == "CANCELLED"


def test_python_runtime_restart_fails_orphan_without_replaying_model(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    request = _request()
    ledger = PythonTerminalLedger(database)
    assert ledger.claim(request, "runtime-before-restart").status == "CLAIMED"
    started = {
        "protocol_version": "1.4",
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
    assert len(events) == 3
    assert events[0] == started
    assert events[1]["event_type"] == "tool_contract_observed"
    assert events[1]["payload"]["status"] == "MATCH"
    assert events[2]["event_type"] == "terminal"
    assert events[2]["payload"]["status"] == "FAILED"
    assert events[2]["payload"]["failure"] == {
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
        "protocol_version": CURRENT_RUNTIME_PROTOCOL_VERSION,
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
    assert response.json()["protocol_version"] == CURRENT_RUNTIME_PROTOCOL_VERSION
    assert client.get("/health").json() == {
        "status": "ok",
        "protocol_version": "1.4",
        "component": "python-runtime",
        "source_revision": "test-revision",
        "build_id": "test-build",
        "platform": "linux/amd64",
    }
    assert client.get("/ready").status_code == 200
    version = client.get("/version").json()
    assert version["protocol_version"] == CURRENT_RUNTIME_PROTOCOL_VERSION
    assert version["supported_protocol_versions"] == ",".join(SUPPORTED_RUNTIME_PROTOCOL_VERSIONS)

    try:
        PythonRuntimeExecutor(
            cast(Any, None),
            limits=build_settings().execution,
            mcp_server_url="https://attacker.example/mcp",
            sdk_version="0.2.134",
        )
    except ValueError as exc:
        assert "fixed deployment boundary" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("arbitrary MCP URL was accepted")


def test_python_runtime_readiness_fails_closed_on_sandbox_v2_config_drift(
    tmp_path: Path,
) -> None:
    executor = FakePythonExecutor()
    dependencies, _private_key = _dependencies(tmp_path, executor)
    dependencies.sandbox_manager = JobSandboxManager(
        tmp_path / "runtime-sandboxes-drifted",
        limits=JobSandboxLimits(max_input_files=39),
    )

    response = TestClient(create_app(dependencies)).get("/ready")

    assert response.status_code == 503
    assert response.json()["ready"] is False
    assert response.json()["sandbox"] == "unavailable"
    assert response.json()["sandbox_max_input_files"] == 39


def test_python_runtime_model_probe_accepts_only_current_request(
    tmp_path: Path,
) -> None:
    executor = FakePythonExecutor()
    dependencies, _private_key = _dependencies(tmp_path, executor)
    client = TestClient(create_app(dependencies))
    probe = {
        "protocol_version": "1.4",
        "runtime_kind": "python-v1",
        "probe_id": "probe-legacy-1",
        "model_connection": {"revision_id": "revision-1", "config_hash": "a" * 64},
        "timeout_seconds": 3,
    }

    response = client.post(
        "/internal/v1/model-probes",
        json=probe,
        headers={"Authorization": "Bearer " + dependencies.model_probe_token},
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["protocol_version"] == CURRENT_RUNTIME_PROTOCOL_VERSION


def test_python_sdk_model_probe_is_single_turn_toolless_and_bounded() -> None:
    captured: dict[str, Any] = {}

    def options(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return kwargs

    async def query(*, prompt: str, options: dict[str, Any]):
        assert prompt == "Reply OK."
        assert options == captured
        yield {"type": "result", "result": "OK"}

    sdk = ClaudeSdk(
        query=query,
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
    )
    client = ClaudeSdkClient(
        model="deepseek-chat",
        limits=build_settings().execution,
        api_key="",
        sdk_loader=lambda: sdk,
    )

    result = client.test_connection(binding, "fixture-provider-key", 3)

    assert result == {"detail": "连接成功"}
    assert captured["mcp_servers"] == {}
    assert captured["tools"] == []
    assert captured["allowed_tools"] == []
    assert captured["max_turns"] == 1
    assert captured["max_buffer_size"] == 64 * 1024 * 1024
    assert captured["setting_sources"] == []
    assert captured["skills"] == []
    assert {"Bash", "Write", "Edit", "WebFetch", "WebSearch"} <= set(captured["disallowed_tools"])
    assert "fixture-provider-key" not in json.dumps(captured, default=str)


def test_python_sdk_model_probe_redacts_provider_error_and_times_out() -> None:
    binding = ModelRuntimeBinding(
        protocol="anthropic_compatible",
        base_url="https://api.deepseek.com/anthropic",
        model="deepseek-chat",
        default_opus_model="deepseek-chat",
        default_sonnet_model="deepseek-chat",
        default_haiku_model="deepseek-chat",
        subagent_model="deepseek-chat",
        effort_level="max",
    )

    async def rejected_query(**_kwargs: Any):
        yield {
            "type": "result",
            "is_error": True,
            "subtype": "provider_error",
            "errors": ["credential-must-not-appear"],
            "result": "",
        }

    rejected_sdk = ClaudeSdk(
        query=rejected_query,
        options=lambda **kwargs: kwargs,
        tool=cast(Any, None),
        create_sdk_mcp_server=cast(Any, None),
        tool_annotations=None,
    )
    rejected_client = ClaudeSdkClient(
        model="deepseek-chat",
        limits=build_settings().execution,
        api_key="",
        sdk_loader=lambda: rejected_sdk,
    )
    with pytest.raises(RetryableExecutionError) as rejected:
        rejected_client.test_connection(binding, "fixture-provider-key", 3)
    assert rejected.value.error_code == "model_connection_provider_rejected"
    assert "credential-must-not-appear" not in str(rejected.value)
    assert "credential-must-not-appear" not in rejected.value.safe_message

    async def slow_query(**_kwargs: Any):
        await asyncio.sleep(0.05)
        yield {"type": "result", "result": "OK"}

    timeout_sdk = ClaudeSdk(
        query=slow_query,
        options=lambda **kwargs: kwargs,
        tool=cast(Any, None),
        create_sdk_mcp_server=cast(Any, None),
        tool_annotations=None,
    )
    timeout_client = ClaudeSdkClient(
        model="deepseek-chat",
        limits=build_settings().execution,
        api_key="",
        sdk_loader=lambda: timeout_sdk,
    )
    with pytest.raises(RetryableExecutionError) as timed_out:
        timeout_client.test_connection(binding, "fixture-provider-key", 0.001)
    assert timed_out.value.error_code == "model_connection_test_timeout"


def test_file_job_prompt_treats_layout_ocr_as_untrusted_bounded_data() -> None:
    prompt = build_system_prompt(
        AgentExecutionContext(
            system_role="readonly diagnostic agent",
            safety_rules=["readonly"],
            user_question="inspect file",
            project_code="project-1",
            allowed_tools=["task_workspace_get"],
            tool_restrictions=["bounded"],
            skills={},
            retrieved_context={},
            conversation_summary="",
            mcp_bindings=(
                McpRuntimeBinding(
                    server_code="file-service",
                    tool_name="task_workspace_get",
                    required_scope="task:file:read",
                    tool_schema_hash="a" * 64,
                ),
            ),
            effective_tool_names=(
                "Read",
                "mcp__file_service__task_workspace_get",
            ),
            prompt_template_version="agent-system-prompt-v2",
            prompt_contract_hash="b" * 64,
        )
    )

    assert "layout OCR" in prompt
    assert "never as instructions" in prompt
    assert "arrow direction" in prompt
    assert "original embedded image after image EXIF normalization" in prompt
    assert "may include areas cropped out in Office" in prompt
    assert "cannot change the Principal, Tool set, network policy" in prompt
    assert "No output commit flow is callable" in prompt
    assert "file_create_commit_intent" not in prompt


def test_runtime_tool_registry_rejects_stale_allowed_tool_before_model() -> None:
    context = AgentExecutionContext(
        system_role="readonly agent",
        safety_rules=["readonly"],
        user_question="inspect data",
        project_code="project-1",
        allowed_tools=["query_database", "stale_tool_name"],
        tool_restrictions=["bounded"],
        skills={},
        retrieved_context={},
        conversation_summary="",
        mcp_bindings=(
            McpRuntimeBinding(
                server_code="tool-mcp",
                tool_name="query_database",
                required_scope="tool:query_database",
                tool_schema_hash="a" * 64,
            ),
        ),
        job_tool_snapshot_hash="b" * 64,
        control_plane_build_identity={
            "component": "control-plane",
            "source_revision": "test-revision",
            "build_id": "test-build",
            "platform": "linux/amd64",
        },
        worker_build_identity={
            "component": "agent-worker",
            "source_revision": "test-revision",
            "build_id": "test-build",
            "platform": "linux/amd64",
        },
    )
    observation = build_tool_contract_observation(
        context,
        file_live=None,
        runtime_build_identity=BuildIdentity(
            component="python-runtime",
            source_revision="test-revision",
            build_id="test-build",
            platform="linux/amd64",
        ),
    )

    assert observation["status"] == "DRIFT"
    assert {(row["tool_name"], row["status"]) for row in observation["rows"]} >= {
        ("stale_tool_name", "UNAUTHORIZED_EFFECTIVE")
    }
    assert observation["prompt"]["declared_tools"] == ["mcp__tool_mcp__query_database"]

    client = FixedMcpClaudeSdkClient(
        limits=build_settings().execution,
        api_key="runtime-only-model-secret",
        mcp_server_url="http://tool-mcp:9103/mcp",
    )
    request = AgentRunRequest(
        job_id="job-stale-tool",
        user_id="user-1",
        project_code="project-1",
        invocation_id="invocation-stale-tool",
        context=context,
    )
    with pytest.raises(NonRetryableExecutionError) as captured:
        asyncio.run(client._open_mcp_server(request, object()))

    assert captured.value.error_code == "runtime_tool_contract_unauthorized_effective"


def test_runtime_tool_registry_marks_required_file_live_failure_as_drift() -> None:
    context = AgentExecutionContext(
        system_role="file agent",
        safety_rules=["bounded"],
        user_question="inspect file",
        project_code="project-1",
        allowed_tools=["file_create_commit_intent"],
        tool_restrictions=["bounded"],
        skills={},
        retrieved_context={},
        conversation_summary="",
        mcp_bindings=(
            McpRuntimeBinding(
                server_code="file-service",
                tool_name="file_create_commit_intent",
                required_scope="file:commit",
                tool_schema_hash="a" * 64,
            ),
        ),
        job_tool_snapshot_hash="b" * 64,
        control_plane_build_identity={
            "component": "control-plane",
            "source_revision": "test-revision",
            "build_id": "test-build",
            "platform": "linux/amd64",
        },
        worker_build_identity={
            "component": "agent-worker",
            "source_revision": "test-revision",
            "build_id": "test-build",
            "platform": "linux/amd64",
        },
    )

    observation = build_tool_contract_observation(
        context,
        file_live=None,
        runtime_build_identity=BuildIdentity(
            component="python-runtime",
            source_revision="test-revision",
            build_id="test-build",
            platform="linux/amd64",
        ),
    )

    assert observation["status"] == "DRIFT"
    assert observation["file_mcp_live"] == {"status": "NOT_OBSERVED", "tools": []}
    assert observation["rows"] == [
        {
            "server_code": "file-service",
            "tool_name": "file_create_commit_intent",
            "status": "REMOTE_NOT_OBSERVED",
        }
    ]
    assert {item["origin"] for item in observation["effective_tools"]} == {"sdk_builtin"}
    assert set(observation["prompt"]["declared_tools"]) == {
        "Read",
        "Glob",
        "Grep",
        "Edit",
        "Write",
    }


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
        mcp_bindings=(
            McpRuntimeBinding(
                server_code="tool-mcp",
                tool_name="get_schema_directory",
                required_scope="tool:get_schema_directory",
                tool_schema_hash="a" * 64,
            ),
            McpRuntimeBinding(
                server_code="tool-mcp",
                tool_name="query_database",
                required_scope="tool:query_database",
                tool_schema_hash="b" * 64,
            ),
        ),
        effective_tool_names=(
            "mcp__tool_mcp__get_schema_directory",
            "mcp__tool_mcp__query_database",
        ),
    )
    request = AgentRunRequest(
        job_id="job-1",
        user_id="app-user-1",
        project_code="project-1",
        invocation_id="invocation-1",
        context=context,
    )
    client = FixedMcpClaudeSdkClient(
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
    sandbox = client.sandbox_manager.create(request.job_id)
    sandbox_token = client._sandbox.set(sandbox)
    try:
        built = client._build_options(sdk, context, server, [], binding)
    finally:
        client._sandbox.reset(sandbox_token)
        sandbox.cleanup()

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
    assert captured["allowed_tools"] == []
    assert captured["max_buffer_size"] == 64 * 1024 * 1024
    assert (
        asyncio.run(
            captured["can_use_tool"](
                "mcp__tool_mcp__query_database",
                {"query": "select 1"},
                object(),
            )
        )["behavior"]
        == "allow"
    )
    assert "internal" not in captured["mcp_servers"]


def test_python_sdk_projects_current_observability_fixture() -> None:
    fixture = json.loads(
        Path("contracts/agent-runtime/v1.4/golden/sdk-observability-fixture.json").read_text(
            encoding="utf-8"
        )
    )

    async def query(**_kwargs: Any) -> Any:
        for name in (
            "status_requesting",
            "init",
            "api_retry",
            "assistant",
            "assistant",
            "result_success",
        ):
            yield fixture[name]

    sdk = ClaudeSdk(
        query=query,
        options=lambda **kwargs: kwargs,
        tool=cast(Any, None),
        create_sdk_mcp_server=cast(Any, None),
        tool_annotations=None,
    )
    context = AgentExecutionContext(
        system_role="readonly agent",
        safety_rules=["readonly"],
        user_question="safe fixture",
        project_code="project-1",
        allowed_tools=[],
        tool_restrictions=["bounded"],
        skills={},
        retrieved_context={},
        conversation_summary="",
        runtime_protocol_version="1.4",
    )
    client = ClaudeSdkClient(
        model="claude-safe-model",
        limits=build_settings().execution,
        api_key="runtime-model-key-value",
        sdk_loader=lambda: sdk,
    )

    result = client.run(
        AgentRunRequest(
            job_id="job-safe-1",
            user_id="user-safe-1",
            project_code="project-1",
            invocation_id="invocation-safe-1",
            context=context,
        )
    )

    assert result.final_answer == "bounded result omitted by audit normalizer"
    assert [item["event_type"] for item in client.last_runtime_events] == [
        "runtime_initialized",
        "api_retry",
        "model_call",
    ]
    assert client.last_runtime_events[-1]["payload"]["duration_source"] == ("SDK_OBSERVED")
    assert client.last_runtime_events[-1]["payload"]["provider_request_id"] == ("request-safe-1")
    assert client.last_accounting["status"] == "COMPLETE"
    assert client.last_accounting["duration_api_ms"] == 1800
    serialized = json.dumps(client.last_runtime_events)
    assert "bounded result omitted" not in serialized


def test_python_sdk_keeps_unknown_accounting_and_omits_raw_content() -> None:
    fixture = json.loads(
        Path("contracts/agent-runtime/v1.4/golden/sdk-observability-fixture.json").read_text(
            encoding="utf-8"
        )
    )
    assistant = json.loads(json.dumps(fixture["assistant"]))
    assistant["message"]["content"] = [
        {"type": "thinking", "thinking": "private-thinking-must-not-persist"},
        {"type": "text", "text": "full-answer-must-not-persist"},
    ]
    result = json.loads(json.dumps(fixture["result_success"]))
    result.pop("usage")
    result.pop("modelUsage")
    result["result"] = "final answer remains execution-only"

    async def query(**_kwargs: Any) -> Any:
        yield assistant
        yield result

    sdk = ClaudeSdk(
        query=query,
        options=lambda **kwargs: kwargs,
        tool=cast(Any, None),
        create_sdk_mcp_server=cast(Any, None),
        tool_annotations=None,
    )
    client = ClaudeSdkClient(
        model="claude-safe-model",
        limits=build_settings().execution,
        api_key="runtime-model-key-value",
        sdk_loader=lambda: sdk,
    )

    client.run(
        AgentRunRequest(
            job_id="job-safe-unknown",
            user_id="user-safe-unknown",
            project_code="project-1",
            invocation_id="invocation-safe-unknown",
            context=AgentExecutionContext(
                system_role="readonly agent",
                safety_rules=["readonly"],
                user_question="safe fixture",
                project_code="project-1",
                allowed_tools=[],
                tool_restrictions=["bounded"],
                skills={},
                retrieved_context={},
                conversation_summary="",
                runtime_protocol_version="1.4",
            ),
        )
    )

    model_call = client.last_runtime_events[-1]["payload"]
    serialized = json.dumps(client.last_runtime_events)
    assert model_call["duration_source"] == "UNAVAILABLE"
    assert model_call["duration_ms"] is None
    assert model_call["started_at"] is None
    assert client.last_accounting["status"] == "UNAVAILABLE"
    assert client.last_accounting["usage"]["input_tokens"] is None
    assert "private-thinking-must-not-persist" not in serialized
    assert "full-answer-must-not-persist" not in serialized
    assert "final answer remains execution-only" not in serialized


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
        effective_tool_names=("mcp__ones_mcp__ones_work_item_search",),
    )
    request = AgentRunRequest(
        job_id="job-1",
        user_id="app-user-1",
        project_code="project-1",
        invocation_id="invocation-1",
        context=context,
    )
    principal = "test-only-principal-token"
    client = FixedMcpClaudeSdkClient(
        limits=build_settings().execution,
        api_key="runtime-only-model-secret",
        mcp_server_url="http://tool-mcp:9103/mcp",
        business_mcp_server_urls={ONES_MCP_SERVER_CODE: "http://ones-mcp:9104/mcp"},
        mcp_principal_tokens={ONES_MCP_SERVER_CODE: principal},
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
    sandbox = client.sandbox_manager.create(request.job_id)
    sandbox_token = client._sandbox.set(sandbox)
    try:
        client._build_options(sdk, context, server, [], binding)
    finally:
        client._sandbox.reset(sandbox_token)
        sandbox.cleanup()

    assert set(captured["mcp_servers"]) == {"ones_mcp"}
    assert captured["mcp_servers"]["ones_mcp"]["url"] == ("http://ones-mcp:9104/mcp")
    assert captured["mcp_servers"]["ones_mcp"]["headers"]["Authorization"] == (
        f"Bearer {principal}"
    )
    assert captured["allowed_tools"] == []
    assert (
        asyncio.run(
            captured["can_use_tool"](
                "mcp__ones_mcp__ones_work_item_search",
                {"keyword": "traceability"},
                object(),
            )
        )["behavior"]
        == "allow"
    )
    assert principal not in repr(context)

    normalized = normalize_tool_events(
        [
            {
                "tool_call_id": "python-tool-use-1",
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


def test_python_runtime_builds_isolated_sdk_config_for_two_business_servers() -> None:
    context = AgentExecutionContext(
        system_role="readonly business agent",
        safety_rules=["readonly"],
        user_question="query two fixed business systems",
        project_code="project-1",
        allowed_tools=["ones_work_item_search", TEST_BUSINESS_TOOL_IDENTIFIER],
        tool_restrictions=["bounded"],
        skills={},
        retrieved_context={},
        conversation_summary="",
        publication_id="agent-publication-1",
        application_publication_id="application-publication-1",
        mcp_bindings=(
            McpRuntimeBinding(
                server_code=ONES_MCP_SERVER_CODE,
                tool_name="ones_work_item_search",
                required_scope="mcp:ones-mcp:ones_work_item_search:invoke",
                tool_schema_hash="c" * 64,
            ),
            McpRuntimeBinding(
                server_code=TEST_BUSINESS_SERVER_CODE,
                tool_name=TEST_BUSINESS_TOOL_IDENTIFIER,
                required_scope=(
                    f"mcp:{TEST_BUSINESS_SERVER_CODE}:{TEST_BUSINESS_TOOL_IDENTIFIER}:invoke"
                ),
                tool_schema_hash="d" * 64,
            ),
        ),
        runtime_protocol_version="1.4",
        job_tool_snapshot_hash="f" * 64,
        control_plane_build_identity={
            "component": "control-plane",
            "source_revision": "test-revision",
            "build_id": "test-build",
            "platform": "linux/amd64",
        },
        worker_build_identity={
            "component": "agent-worker",
            "source_revision": "test-revision",
            "build_id": "test-build",
            "platform": "linux/amd64",
        },
    )
    request = AgentRunRequest(
        job_id="job-dual-business",
        user_id="app-user-1",
        project_code="project-1",
        invocation_id="invocation-dual-business",
        context=context,
    )
    tokens = {
        ONES_MCP_SERVER_CODE: "ones-audience-token",
        TEST_BUSINESS_SERVER_CODE: "second-audience-token",
    }
    client = FixedMcpClaudeSdkClient(
        limits=build_settings().execution,
        api_key="runtime-only-model-secret",
        mcp_server_url="http://tool-mcp:9103/mcp",
        business_mcp_server_urls={
            ONES_MCP_SERVER_CODE: "http://ones-mcp:9104/mcp",
            TEST_BUSINESS_SERVER_CODE: "http://test-business-mcp:9200/mcp",
        },
        mcp_principal_tokens=tokens,
        server_policies=business_mcp_test_policies(),
    )

    servers = client._build_mcp_server(request)

    assert set(servers) == {"ones_mcp", "test_business_mcp"}
    assert servers["ones_mcp"]["headers"]["Authorization"] == ("Bearer ones-audience-token")
    assert servers["test_business_mcp"]["headers"]["Authorization"] == (
        "Bearer second-audience-token"
    )
    assert "second-audience-token" not in json.dumps(servers["ones_mcp"])
    assert "ones-audience-token" not in json.dumps(servers["test_business_mcp"])
    assert "audience-token" not in repr(client)


def test_python_runtime_file_job_uses_fixed_file_mcp_guarded_tools_and_finally_cleanup(
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}

    async def query(*, options: dict[str, Any], **_kwargs: Any) -> Any:
        captured.update(options)
        assert (
            await options["can_use_tool"](
                "Write",
                {"file_path": "outputs/result.txt", "content": "result"},
                object(),
            )
        )["behavior"] == "allow"
        assert (await options["can_use_tool"]("Bash", {"command": "pwd"}, object()))[
            "behavior"
        ] == "deny"
        assert (await options["can_use_tool"]("Read", {"file_path": "/etc/passwd"}, object()))[
            "behavior"
        ] == "deny"
        assert (
            await options["can_use_tool"]("Glob", {"pattern": "**/*.txt", "path": "."}, object())
        )["behavior"] == "allow"
        yield {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": "file job complete",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }

    sdk = ClaudeSdk(
        query=query,
        options=lambda **kwargs: kwargs,
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
    context = AgentExecutionContext(
        system_role="task file agent",
        safety_rules=["sandbox only"],
        user_question="create a TXT result",
        project_code="project-1",
        allowed_tools=["file_create_commit_intent"],
        tool_restrictions=["TXT only"],
        skills={},
        retrieved_context={
            "file_manifest": {
                "schema_version": 5,
                "workspace_catalog_revision_id": "workspace-catalog-file-job",
                "manifest_hash": "e" * 64,
                "observed_at": "2026-08-22T00:00:00Z",
                "items": [],
            }
        },
        conversation_summary="",
        publication_id="agent-publication-1",
        application_publication_id="application-publication-1",
        model_runtime_binding=binding,
        mcp_bindings=(
            McpRuntimeBinding(
                server_code="file-service",
                tool_name="file_create_commit_intent",
                required_scope=("mcp:file-service:file_create_commit_intent:invoke"),
                tool_schema_hash="d" * 64,
            ),
        ),
        runtime_protocol_version="1.4",
        job_tool_snapshot_hash="f" * 64,
        control_plane_build_identity={
            "component": "control-plane",
            "source_revision": "test-revision",
            "build_id": "test-build",
            "platform": "linux/amd64",
        },
        worker_build_identity={
            "component": "agent-worker",
            "source_revision": "test-revision",
            "build_id": "test-build",
            "platform": "linux/amd64",
        },
    )
    file_principal = "file-principal-token-not-for-events"
    bridge_capture: dict[str, Any] = {}

    class FakeFileBridge:
        server = {"type": "sdk", "name": "enterprise-file-bridge"}
        local_tool_names = ("select_sandbox_output",)
        live_observation = {
            "status": "OBSERVED",
            "tools": [
                {
                    "server_code": "file-service",
                    "tool_name": "file_create_commit_intent",
                    "schema_hash": "d" * 64,
                    "status": "MATCH",
                }
            ],
            "toolset_hash": "e" * 64,
            "build_identity": {
                "component": "file-service",
                "source_revision": "test-revision",
                "build_id": "test-build",
                "platform": "linux/amd64",
            },
        }

        async def connect(self) -> None:
            bridge_capture["connected"] = True

        async def close(self) -> None:
            bridge_capture["closed"] = True

    def file_bridge_factory(**kwargs: Any) -> FakeFileBridge:
        bridge_capture.update(kwargs)
        return FakeFileBridge()

    client = FixedMcpClaudeSdkClient(
        limits=build_settings().execution,
        api_key="runtime-only-model-secret",
        mcp_server_url="http://tool-mcp:9103/mcp",
        file_mcp_server_url="http://file-service:9105/mcp",
        file_principal_token=file_principal,
        sandbox_manager=JobSandboxManager(tmp_path / "sandboxes"),
        file_bridge_factory=file_bridge_factory,
    )
    client.sdk_loader = lambda: sdk

    result = client.run(
        AgentRunRequest(
            job_id="job-file-1",
            user_id="app-user-1",
            project_code="project-1",
            invocation_id="invocation-file-1",
            context=context,
        )
    )

    assert result.final_answer == "file job complete"
    assert captured["setting_sources"] == []
    assert captured["tools"] == ["Read", "Glob", "Grep", "Edit", "Write"]
    assert captured["allowed_tools"] == []
    assert "Bash" in captured["disallowed_tools"]
    assert "Write" not in captured["disallowed_tools"]
    assert captured["mcp_servers"]["file_service"] == FakeFileBridge.server
    assert bridge_capture["mcp_server_url"] == "http://file-service:9105/mcp"
    assert bridge_capture["headers"]["Authorization"] == (f"Bearer {file_principal}")
    assert bridge_capture["connected"] is True
    assert bridge_capture["closed"] is True
    sandbox_path = Path(captured["cwd"])
    assert not sandbox_path.exists()
    assert file_principal not in json.dumps(client.last_runtime_events)


def test_python_runtime_cancellation_interrupts_sdk_and_cleans_sandbox(
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}
    cancelled = threading.Event()

    async def query(*, options: dict[str, Any], **_kwargs: Any) -> Any:
        captured.update(options)
        while True:
            await asyncio.sleep(1)
        yield  # pragma: no cover

    sdk = ClaudeSdk(
        query=query,
        options=lambda **kwargs: kwargs,
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
    client = FixedMcpClaudeSdkClient(
        limits=build_settings().execution,
        api_key="runtime-only-model-secret",
        mcp_server_url="http://tool-mcp:9103/mcp",
        sandbox_manager=JobSandboxManager(tmp_path / "sandboxes"),
        cancellation_event=cancelled,
    )
    client.sdk_loader = lambda: sdk
    timer = threading.Timer(0.1, cancelled.set)
    timer.start()
    try:
        with pytest.raises(NonRetryableExecutionError) as captured_error:
            client.run(
                AgentRunRequest(
                    job_id="job-cancel-1",
                    user_id="app-user-1",
                    project_code="project-1",
                    context=AgentExecutionContext(
                        system_role="safe agent",
                        safety_rules=["no tools"],
                        user_question="wait",
                        project_code="project-1",
                        allowed_tools=[],
                        tool_restrictions=["no tools"],
                        skills={},
                        retrieved_context={},
                        conversation_summary="",
                        model_runtime_binding=binding,
                        job_tool_snapshot_hash="0" * 64,
                        control_plane_build_identity={
                            "component": "control-plane",
                            "source_revision": "test-revision",
                            "build_id": "test-build",
                            "platform": "linux/amd64",
                        },
                        worker_build_identity={
                            "component": "agent-worker",
                            "source_revision": "test-revision",
                            "build_id": "test-build",
                            "platform": "linux/amd64",
                        },
                    ),
                )
            )
        assert captured_error.value.error_code == "runtime_cancelled"
    finally:
        timer.cancel()
    assert not Path(captured["cwd"]).exists()


def test_python_runtime_preserves_sdk_tool_use_id_meta_and_exact_origin() -> None:
    calls: dict[str, dict[str, Any]] = {}
    limits = build_settings().execution
    started = extract_tool_events(
        {
            "content": [
                {
                    "type": "tool_use",
                    "id": "sdk-tool-use-1",
                    "name": "mcp__ones_mcp__ones_work_item_search",
                    "input": {"keyword": "test"},
                }
            ]
        },
        limits,
        calls,
    )
    completed = extract_tool_events(
        {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "sdk-tool-use-1",
                    "content": {"count": 1},
                }
            ],
            "tool_use_result": {
                "_meta": {
                    "enterprise-agent/mcp-call-id": "mcp-call-python",
                    "enterprise-agent/agent-tool-call-id": "agent-tool-call-python",
                }
            },
        },
        limits,
        calls,
    )
    request = _request()
    request["protocol_version"] = "1.4"

    normalized = normalize_tool_events([*started, *completed], request)

    assert [event["tool_call_id"] for event in normalized] == [
        "sdk-tool-use-1",
        "sdk-tool-use-1",
    ]
    assert normalized[0]["tool_origin"] == "mcp"
    assert "invocation_id" not in normalized[0]
    assert normalized[1]["mcp_call_id"] == "mcp-call-python"
    assert normalized[1]["persisted_tool_call_id"] == "agent-tool-call-python"

    classified = normalize_tool_events(
        [
            {"tool_call_id": "builtin-1", "tool_name": "Bash", "status": "DENIED"},
            {"tool_call_id": "unknown-1", "tool_name": "mystery", "status": "DENIED"},
        ],
        request,
    )
    assert [(event["tool_origin"], event["server_code"]) for event in classified] == [
        ("sdk_builtin", None),
        ("unknown", None),
    ]


def test_python_test_only_fake_provider_resolves_binding_and_retries_once() -> None:
    resolver = FakePythonBindingResolver()
    executor = PythonRuntimeExecutor(
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


def test_python_test_only_fake_provider_calls_ones_concurrently_with_exact_meta(
    monkeypatch: Any,
) -> None:
    lock = threading.Lock()
    tool_calls = 0
    authorization_headers: list[str] = []

    class Response:
        headers = {"content-type": "application/json"}

        def __init__(self, payload: dict[str, Any]) -> None:
            self.payload = payload

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, _limit: int) -> bytes:
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request: Any, timeout: int) -> Response:
        nonlocal tool_calls
        assert timeout == 10
        authorization_headers.append(str(request.headers.get("Authorization") or ""))
        payload = json.loads(bytes(request.data).decode("utf-8"))
        if payload["method"] != "tools/call":
            return Response({"jsonrpc": "2.0", "id": 1, "result": {}})
        with lock:
            tool_calls += 1
            index = tool_calls
        return Response(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {
                    "isError": False,
                    "content": [{"type": "text", "text": "ok"}],
                    "_meta": {
                        "enterprise-agent/mcp-call-id": f"mcp-call-python-{index}",
                        "enterprise-agent/agent-tool-call-id": f"agent-tool-python-{index}",
                    },
                },
            }
        )

    monkeypatch.setattr("app.python_runtime.executor.urlopen", fake_urlopen)
    executor = PythonRuntimeExecutor(
        cast(PythonModelBindingResolver, FakePythonBindingResolver()),
        limits=build_settings().execution,
        mcp_server_url="http://tool-mcp:9103/mcp",
        sdk_version="0.2.134",
        cli_version="2.1.226",
        fake_provider_mode=True,
    )
    request = _request()
    request["protocol_version"] = "1.4"
    request["prompt"]["user_question"] = "[smoke:mcp:ones-mcp-concurrent] verify exact metadata"
    result = executor.execute(
        request,
        threading.Event(),
        SimpleNamespace(
            mcp_principal_tokens={ONES_MCP_SERVER_CODE: "test-only-principal-token"},
            file_principal_token="",
        ),
    )

    assert result.status == "SUCCEEDED"
    assert tool_calls == 2
    assert authorization_headers == ["Bearer test-only-principal-token"] * 4
    assert len(result.tool_events) == 4
    assert [item["status"] for item in result.tool_events] == [
        "STARTED",
        "STARTED",
        "SUCCEEDED",
        "SUCCEEDED",
    ]
    assert {item["mcp_call_id"] for item in result.tool_events[2:]} == {
        "mcp-call-python-1",
        "mcp-call-python-2",
    }
    assert "test-only-principal-token" not in json.dumps(result.tool_events)


def test_python_test_only_fake_provider_isolates_second_business_server_token(
    monkeypatch: Any,
) -> None:
    authorization_headers: list[str] = []
    requested_urls: list[str] = []
    tool_calls = 0

    class Response:
        headers = {"content-type": "application/json"}

        def __init__(self, payload: dict[str, Any]) -> None:
            self.payload = payload

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, _limit: int) -> bytes:
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request: Any, timeout: int) -> Response:
        nonlocal tool_calls
        assert timeout == 10
        requested_urls.append(str(request.full_url))
        authorization_headers.append(str(request.headers.get("Authorization") or ""))
        payload = json.loads(bytes(request.data).decode("utf-8"))
        if payload["method"] != "tools/call":
            return Response({"jsonrpc": "2.0", "id": 1, "result": {}})
        tool_calls += 1
        assert payload["params"] == {
            "name": TEST_BUSINESS_TOOL_IDENTIFIER,
            "arguments": {},
        }
        return Response(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {
                    "isError": False,
                    "content": [{"type": "text", "text": "ok"}],
                    "_meta": {
                        "enterprise-agent/mcp-call-id": f"mcp-call-second-{tool_calls}",
                        "enterprise-agent/agent-tool-call-id": (f"agent-tool-second-{tool_calls}"),
                    },
                },
            }
        )

    monkeypatch.setattr("app.python_runtime.executor.urlopen", fake_urlopen)
    executor = PythonRuntimeExecutor(
        cast(PythonModelBindingResolver, FakePythonBindingResolver()),
        limits=build_settings().execution,
        mcp_server_url="http://tool-mcp:9103/mcp",
        business_mcp_server_urls={
            ONES_MCP_SERVER_CODE: "http://ones-mcp:9104/mcp",
            TEST_BUSINESS_SERVER_CODE: "http://test-business-mcp:9200/mcp",
        },
        server_policies=business_mcp_test_policies(),
        sdk_version="0.2.134",
        cli_version="2.1.226",
        fake_provider_mode=True,
    )
    request = _request()
    request["protocol_version"] = "1.4"
    request["mcp_servers"] = [
        {
            "server_code": TEST_BUSINESS_SERVER_CODE,
            "tools": [{"tool_name": TEST_BUSINESS_TOOL_IDENTIFIER}],
        }
    ]
    request["prompt"]["user_question"] = (
        f"[smoke:mcp:{TEST_BUSINESS_SERVER_CODE}-concurrent] verify isolation"
    )
    result = executor.execute(
        request,
        threading.Event(),
        SimpleNamespace(
            mcp_principal_tokens={
                ONES_MCP_SERVER_CODE: "wrong-audience-token",
                TEST_BUSINESS_SERVER_CODE: "second-audience-token",
            },
            file_principal_token="",
        ),
    )

    assert result.status == "SUCCEEDED"
    assert tool_calls == 2
    assert requested_urls == ["http://test-business-mcp:9200/mcp"] * 4
    assert authorization_headers == ["Bearer second-audience-token"] * 4
    assert "wrong-audience-token" not in json.dumps(result.tool_events)
    assert "second-audience-token" not in json.dumps(result.tool_events)


def test_python_test_only_fake_provider_calls_file_service_with_file_principal(
    monkeypatch: Any,
) -> None:
    authorization_headers: list[str] = []
    requested_urls: list[str] = []

    class Response:
        headers = {"content-type": "application/json"}

        def __init__(self, payload: dict[str, Any]) -> None:
            self.payload = payload

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, _limit: int) -> bytes:
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request: Any, timeout: int) -> Response:
        assert timeout == 10
        requested_urls.append(str(request.full_url))
        authorization_headers.append(str(request.headers.get("Authorization") or ""))
        payload = json.loads(bytes(request.data).decode("utf-8"))
        if payload["method"] != "tools/call":
            return Response({"jsonrpc": "2.0", "id": 1, "result": {}})
        assert payload["params"] == {"name": "task_workspace_get", "arguments": {}}
        return Response(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {
                    "isError": False,
                    "content": [{"type": "text", "text": "ok"}],
                    "_meta": {
                        "enterprise-agent/mcp-call-id": "mcp-call-file-python",
                        "enterprise-agent/agent-tool-call-id": "agent-tool-file-python",
                    },
                },
            }
        )

    monkeypatch.setattr("app.python_runtime.executor.urlopen", fake_urlopen)
    executor = PythonRuntimeExecutor(
        cast(PythonModelBindingResolver, FakePythonBindingResolver()),
        limits=build_settings().execution,
        mcp_server_url="http://tool-mcp:9103/mcp",
        file_mcp_server_url="http://file-service:9105/mcp",
        sdk_version="0.2.134",
        cli_version="2.1.226",
        fake_provider_mode=True,
    )
    request = _request()
    request["protocol_version"] = "1.4"
    request["prompt"]["user_question"] = "[smoke:mcp:file-service] verify exact metadata"
    request["mcp_servers"] = [
        {
            "server_code": "file-service",
            "tools": [{"tool_name": "task_workspace_get"}],
        }
    ]
    file_principal = "test-only-file-principal-token"
    result = executor.execute(
        request,
        threading.Event(),
        SimpleNamespace(mcp_principal_tokens={}, file_principal_token=file_principal),
    )

    assert result.status == "SUCCEEDED"
    assert requested_urls == ["http://file-service:9105/mcp"] * 2
    assert authorization_headers == [f"Bearer {file_principal}"] * 2
    assert [item["status"] for item in result.tool_events] == ["STARTED", "SUCCEEDED"]
    assert result.tool_events[1]["server_code"] == "file-service"
    assert result.tool_events[1]["mcp_call_id"] == "mcp-call-file-python"
    assert file_principal not in json.dumps(result.tool_events)


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
        "protocol_version": "1.4",
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


def test_python_runtime_draft_probe_accepts_allowlisted_internal_http_gateway(
    tmp_path: Path,
) -> None:
    master_key = "python-draft-probe-gateway-master-key"
    config = {
        "schema_version": 1,
        "protocol": "anthropic_compatible",
        "base_url": "http://aikeyhub.gateway.mdzy/api",
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
        "protocol_version": "1.4",
        "runtime_kind": "python-v1",
        "probe_id": "probe-python-draft-gateway",
        "config_hash": config_hash,
        "timeout_seconds": 15,
    }
    request["credential_envelope"] = ModelProbeEnvelopeCipher(master_key).encrypt(
        probe_id=request["probe_id"],
        runtime_kind=request["runtime_kind"],
        config_hash=config_hash,
        config=config,
        api_key="fixture-python-draft-gateway-key",
        lifetime_seconds=30,
    )
    resolver = PythonModelBindingResolver(
        _database(tmp_path),
        master_key=master_key,
        allowed_hosts=("api.deepseek.com", "aikeyhub.gateway.mdzy"),
        dns_resolver=lambda *_args, **_kwargs: [(2, 1, 6, "", ("10.20.30.40", 80))],
    )

    resolved = resolver.resolve_draft(request)

    assert resolved.binding.base_url == "http://aikeyhub.gateway.mdzy/api"
    assert resolved.api_key == "fixture-python-draft-gateway-key"
