from __future__ import annotations

import json
import io
import urllib.error
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.modules.agent.domain.runtime import (
    AgentExecutionContext,
    AgentRunRequest,
    McpRuntimeBinding,
)
from app.modules.agent.infrastructure.runtime_http_client import (
    AgentRuntimeHttpClient,
    RuntimeClientSettings,
    RuntimeGrantIssuer,
    RuntimePrincipalTokens,
    probe_runtime_readiness,
)
from app.shared.mcp_server_policy import ONES_MCP_SERVER_CODE
from app.modules.model_connection.domain import (
    ANTHROPIC_COMPATIBLE_PROTOCOL,
    ModelRuntimeBinding,
)
from app.shared.exceptions import NonRetryableExecutionError, RetryableExecutionError
from backend.tests.business_mcp_fixtures import (
    TEST_BUSINESS_SERVER_CODE,
    TEST_BUSINESS_TOOL_IDENTIFIER,
    business_mcp_test_policies,
)


class _PassiveResponse:
    def __init__(self, payload: dict[str, Any], *, status: int = 200) -> None:
        self.payload = payload
        self.status = status

    def __enter__(self) -> _PassiveResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_passive_runtime_readiness_calls_only_version_and_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths: list[str] = []

    def fake_urlopen(request: Any, timeout: int) -> _PassiveResponse:
        del timeout
        paths.append(request.full_url)
        assert request.method == "GET"
        assert request.get_header("Authorization") is None
        if request.full_url.endswith("/version"):
            return _PassiveResponse(
                {
                    "runtime": "python-v1",
                    "runtime_version": "0.1.0",
                    "protocol_version": "1.0",
                    "sdk_version": "0.3.226",
                    "cli_version": "2.1.226",
                }
            )
        return _PassiveResponse({"ready": True, "database": "ready", "master_key": "ready"})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = probe_runtime_readiness(
        RuntimeClientSettings(
            base_url="http://agent-runtime:9102",
            allowed_runtime_hosts=("agent-runtime",),
            allow_insecure_internal_http=True,
        )
    )

    assert result["ready"] is True
    assert result["model_invoked"] is False
    assert result["mcp_invoked"] is False
    assert paths == [
        "http://agent-runtime:9102/version",
        "http://agent-runtime:9102/ready",
    ]


def test_passive_runtime_readiness_preserves_degraded_dependency_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request: Any, timeout: int) -> _PassiveResponse:
        del timeout
        if request.full_url.endswith("/version"):
            return _PassiveResponse(
                {
                    "runtime": "python-v1",
                    "runtime_version": "0.1.0",
                    "protocol_version": "1.0",
                    "sdk_version": "0.3.226",
                    "cli_version": "2.1.226",
                }
            )
        body = json.dumps(
            {"ready": False, "database": "ready", "master_key": "unavailable"}
        ).encode("utf-8")
        raise urllib.error.HTTPError(
            request.full_url,
            503,
            "not ready",
            {},
            io.BytesIO(body),
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = probe_runtime_readiness(
        RuntimeClientSettings(
            base_url="http://agent-runtime:9102",
            allowed_runtime_hosts=("agent-runtime",),
            allow_insecure_internal_http=True,
        )
    )

    assert result["ready"] is False
    assert result["identity"] == "verified"
    assert result["database"] == "ready"
    assert result["master_key"] == "unavailable"
    assert result["model_invoked"] is False
    assert result["mcp_invoked"] is False


def _private_key() -> tuple[bytes, bytes]:
    private = Ed25519PrivateKey.generate()
    private_pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


def _context() -> AgentExecutionContext:
    return AgentExecutionContext(
        system_role="readonly project agent",
        safety_rules=["readonly"],
        user_question="find failed work items",
        project_code="project-1",
        allowed_tools=[],
        tool_restrictions=["bounded"],
        skills={},
        retrieved_context={},
        conversation_summary="none",
        timeout_seconds=120,
        max_turns=12,
        max_tool_calls=30,
        publication_id="agent-publication-1",
        application_publication_id="application-publication-1",
        model_runtime_binding=ModelRuntimeBinding(
            protocol=ANTHROPIC_COMPATIBLE_PROTOCOL,
            base_url="https://api.deepseek.com/anthropic",
            model="deepseek-chat",
            default_opus_model="deepseek-chat",
            default_sonnet_model="deepseek-chat",
            default_haiku_model="deepseek-chat",
            subagent_model="deepseek-chat",
            effort_level="max",
            connection_revision_id="model-connection-revision-1",
            config_hash="a" * 64,
            secret_ref="secret://platform/must-not-cross-worker-boundary",
        ),
        mcp_bindings=(
            McpRuntimeBinding(
                server_code="tool-mcp",
                tool_name="query_database",
                required_scope="tool:query_database",
                tool_schema_hash="b" * 64,
            ),
        ),
        runtime_kind="python-v1",
    )


def _request() -> AgentRunRequest:
    return AgentRunRequest(
        job_id="job-1",
        user_id="app-user-1",
        project_code="project-1",
        context=_context(),
        invocation_id="job-1.attempt-0",
    )


def _provenance(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "runtime_kind": "python-v1",
        "runtime_version": "0.1.0",
        "protocol_version": request["protocol_version"],
        "sdk_version": "0.3.226",
        "cli_version": "2.1.226",
        "model_connection_revision_id": request["model_connection"]["revision_id"],
        "model_connection_config_hash": request["model_connection"]["config_hash"],
    }


class GoldenTransport:
    def __init__(self, *, terminal_status: str = "SUCCEEDED") -> None:
        self.terminal_status = terminal_status
        self.request: dict[str, Any] = {}
        self.headers: dict[str, str] = {}
        self.cancel_payload: dict[str, Any] = {}

    def stream(
        self,
        *,
        url: str,
        body: bytes,
        headers: dict[str, str],
        timeout_seconds: int,
    ) -> Iterator[bytes]:
        del url, timeout_seconds
        self.request = json.loads(body)
        self.headers = headers
        provenance = _provenance(self.request)
        events = [
            {
                "protocol_version": self.request["protocol_version"],
                "invocation_id": self.request["invocation_id"],
                "request_digest": self.request["request_digest"],
                "sequence": 1,
                "event_type": "execution_started",
                "timestamp": "2026-08-09T00:00:00Z",
                "payload": provenance,
            },
            {
                "protocol_version": self.request["protocol_version"],
                "invocation_id": self.request["invocation_id"],
                "request_digest": self.request["request_digest"],
                "sequence": 2,
                "event_type": "tool_event",
                "timestamp": "2026-08-09T00:00:01Z",
                "payload": {
                    "tool_call_id": "tool-call-1",
                    "server_code": self.request["mcp_servers"][0]["server_code"],
                    "tool_name": self.request["mcp_servers"][0]["tools"][0]["tool_name"],
                    "status": "SUCCEEDED",
                    "request_summary": {"project_code": "project-1"},
                    "response_summary": {"count": 1},
                    "duration_ms": 10,
                    **(
                        {
                            "tool_origin": "mcp",
                            "mcp_call_id": "mcp-call-1",
                            "persisted_tool_call_id": "agent-tool-call-1",
                        }
                        if self.request["protocol_version"] != "1.0"
                        else {}
                    ),
                },
            },
        ]
        terminal: dict[str, Any] = {
            "protocol_version": self.request["protocol_version"],
            "invocation_id": self.request["invocation_id"],
            "request_digest": self.request["request_digest"],
            "last_sequence": 3,
            "status": self.terminal_status,
            "usage": {
                "input_tokens": 10,
                "output_tokens": 4,
                **(
                    {
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                    }
                    if self.request["protocol_version"] in {"1.2", "1.3"}
                    else {}
                ),
            },
            "runtime_provenance": provenance,
        }
        if self.request["protocol_version"] in {"1.2", "1.3"}:
            terminal["accounting"] = {
                "status": "COMPLETE",
                "duration_ms": 20,
                "duration_api_ms": 10,
                "num_turns": 1,
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 4,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                },
                "model_usage": [],
                "estimated_cost_usd": 0.001,
                "permission_denials_count": 0,
            }
        if self.terminal_status == "SUCCEEDED":
            terminal["final_answer"] = "final answer"
        else:
            terminal["failure"] = {
                "code": "runtime_model_rate_limited",
                "retry_class": "TRANSIENT",
                "safe_message": "模型服务当前繁忙，请稍后重试",
            }
        events.append(
            {
                "protocol_version": self.request["protocol_version"],
                "invocation_id": self.request["invocation_id"],
                "request_digest": self.request["request_digest"],
                "sequence": 3,
                "event_type": "terminal",
                "timestamp": "2026-08-09T00:00:02Z",
                "payload": terminal,
            }
        )
        yield from (f"{json.dumps(event)}\n".encode() for event in events)

    def post(
        self,
        *,
        url: str,
        body: bytes,
        headers: dict[str, str],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        del url, headers, timeout_seconds
        self.cancel_payload = json.loads(body)
        return {"status": "cancelled"}


def _client(
    transport: Any,
    *,
    events: list[dict[str, Any]] | None = None,
    principal_token_issuer: Any | None = None,
    server_policies: Any | None = None,
    allowed_mcp_server_codes: tuple[str, ...] | None = None,
):
    private_pem, public_pem = _private_key()
    captured_events = events if events is not None else []
    return (
        AgentRuntimeHttpClient(
            settings=RuntimeClientSettings(
                base_url="http://agent-runtime:8090",
                allowed_runtime_hosts=("agent-runtime",),
                **(
                    {"allowed_mcp_server_codes": allowed_mcp_server_codes}
                    if allowed_mcp_server_codes is not None
                    else {}
                ),
                allow_insecure_internal_http=True,
            ),
            grant_issuer=RuntimeGrantIssuer(private_pem, now=lambda: 1_800_000_000),
            principal_token_issuer=principal_token_issuer,
            server_policies=server_policies,
            transport=transport,
            event_sink=lambda _job_id, event: captured_events.append(event),
        ),
        public_pem,
    )


def test_worker_builds_exact_request_and_validates_ndjson_terminal() -> None:
    transport = GoldenTransport()
    persisted_events: list[dict[str, Any]] = []
    client, public_pem = _client(transport, events=persisted_events)

    result = client.run(_request())

    assert result.final_answer == "final answer"
    assert result.runtime_provenance["runtime_kind"] == "python-v1"
    assert len(result.tool_events) == 1
    assert [event["sequence"] for event in persisted_events] == [1, 2, 3]
    runtime_claims = jwt.decode(
        transport.headers["Authorization"].removeprefix("Bearer "),
        public_pem,
        algorithms=["EdDSA"],
        audience="agent-runtime",
        issuer="enterprise-agent-worker",
        options={"verify_exp": False, "verify_iat": False, "verify_nbf": False},
    )
    assert runtime_claims["azp"] == "agent-worker"
    assert runtime_claims["runtime_kind"] == "python-v1"
    assert runtime_claims["job_id"] == "job-1"
    assert runtime_claims["request_digest"] == transport.request["request_digest"]
    assert runtime_claims["application_publication_id"] == "application-publication-1"
    assert runtime_claims["exp"] - runtime_claims["iat"] == 180
    assert "secret_ref" not in json.dumps(transport.request)
    assert transport.request["runtime_kind"] == "python-v1"
    assert transport.request["mcp_servers"][0]["server_code"] == "tool-mcp"
    assert transport.request["mcp_servers"][0]["tools"] == [
        {
            "tool_name": "query_database",
            "required_scope": "tool:query_database",
            "tool_schema_hash": "b" * 64,
        }
    ]
    assert "access_token" not in transport.request["mcp_servers"][0]
    assert "url" not in transport.request["mcp_servers"][0]


class _PrincipalTokenIssuer:
    def __init__(self, *, business_tokens: dict[str, str] | None = None) -> None:
        self.business_tokens = business_tokens or {
            ONES_MCP_SERVER_CODE: "test-only-principal-token"
        }
        self.business_calls: list[tuple[str, str]] = []
        self.file_job_ids: list[str] = []

    def issue_business_mcp_for_job(self, *, job_id: str, server_code: str) -> str:
        self.business_calls.append((job_id, server_code))
        return self.business_tokens[server_code]

    def issue_file_for_job(self, *, job_id: str) -> str:
        self.file_job_ids.append(job_id)
        return "test-only-file-principal-token"


def test_runtime_principal_token_mapping_is_readonly_and_hidden() -> None:
    tokens = RuntimePrincipalTokens(
        business={ONES_MCP_SERVER_CODE: "must-not-appear"},
        files="file-must-not-appear",
    )

    assert repr(tokens) == "RuntimePrincipalTokens(business=<hidden>, files=<hidden>)"
    with pytest.raises(TypeError):
        tokens.business[ONES_MCP_SERVER_CODE] = "reused"  # type: ignore[index]


def test_worker_projects_principal_only_to_runtime_header_for_ones_mcp() -> None:
    issuer = _PrincipalTokenIssuer()
    transport = GoldenTransport()
    captured_events: list[dict[str, Any]] = []
    client, _ = _client(
        transport,
        events=captured_events,
        principal_token_issuer=issuer,
    )
    request = _request()
    request = replace(
        request,
        context=replace(
            request.context,
            allowed_tools=["ones_work_item_search"],
            mcp_bindings=(
                McpRuntimeBinding(
                    server_code="ones-mcp",
                    tool_name="ones_work_item_search",
                    required_scope="mcp:ones-mcp:ones_work_item_search:invoke",
                    tool_schema_hash="c" * 64,
                ),
            ),
        ),
    )

    result = client.run(request)

    assert result.final_answer == "final answer"
    assert issuer.business_calls == [("job-1", ONES_MCP_SERVER_CODE)]
    assert transport.headers["X-MCP-Principal-Token-Ones-Mcp"] == ("test-only-principal-token")
    assert "X-MCP-Principal-Token" not in transport.headers
    assert transport.request["mcp_servers"][0]["server_code"] == "ones-mcp"
    persisted = json.dumps([transport.request, captured_events])
    assert "test-only-principal-token" not in persisted


def test_worker_fails_closed_when_ones_mcp_has_no_principal_issuer() -> None:
    client, _ = _client(GoldenTransport())
    request = _request()
    request = replace(
        request,
        context=replace(
            request.context,
            allowed_tools=["ones_work_item_search"],
            mcp_bindings=(
                McpRuntimeBinding(
                    server_code="ones-mcp",
                    tool_name="ones_work_item_search",
                    required_scope="mcp:ones-mcp:ones_work_item_search:invoke",
                    tool_schema_hash="c" * 64,
                ),
            ),
        ),
    )

    with pytest.raises(NonRetryableExecutionError) as raised:
        client.run(request)

    assert raised.value.error_code == "principal_token_issuer_unavailable"


def test_worker_issues_a_separate_file_principal_for_file_mcp() -> None:
    issuer = _PrincipalTokenIssuer()
    client, _ = _client(
        GoldenTransport(),
        principal_token_issuer=issuer,
    )
    request = _request()
    request = replace(
        request,
        context=replace(
            request.context,
            runtime_protocol_version="1.2",
            allowed_tools=["file_prepare_materialization"],
            mcp_bindings=(
                McpRuntimeBinding(
                    server_code="file-service",
                    tool_name="file_prepare_materialization",
                    required_scope=("mcp:file-service:file_prepare_materialization:invoke"),
                    tool_schema_hash="d" * 64,
                ),
            ),
        ),
    )

    execution_request = client._execution_request(request)
    tokens = client._principal_tokens(request, execution_request)

    assert dict(tokens.business) == {}
    assert tokens.files == "test-only-file-principal-token"
    assert issuer.business_calls == []
    assert issuer.file_job_ids == ["job-1"]
    assert "test-only-file-principal-token" not in json.dumps(execution_request)


def test_worker_projects_two_business_principals_to_distinct_runtime_headers() -> None:
    policies = business_mcp_test_policies()
    issuer = _PrincipalTokenIssuer(
        business_tokens={
            ONES_MCP_SERVER_CODE: "test-only-ones-principal-token",
            TEST_BUSINESS_SERVER_CODE: "test-only-second-principal-token",
        }
    )
    transport = GoldenTransport()
    captured_events: list[dict[str, Any]] = []
    client, _ = _client(
        transport,
        events=captured_events,
        principal_token_issuer=issuer,
        server_policies=policies,
        allowed_mcp_server_codes=tuple(policies),
    )
    request = replace(
        _request(),
        context=replace(
            _request().context,
            runtime_protocol_version="1.1",
            allowed_tools=["ones_work_item_search", TEST_BUSINESS_TOOL_IDENTIFIER],
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
                    required_scope=("mcp:test-business-mcp:test_business_lookup:invoke"),
                    tool_schema_hash="d" * 64,
                ),
            ),
        ),
    )

    result = client.run(request)
    execution_request = transport.request

    assert result.final_answer == "final answer"
    assert issuer.business_calls == [
        ("job-1", ONES_MCP_SERVER_CODE),
        ("job-1", TEST_BUSINESS_SERVER_CODE),
    ]
    assert transport.headers["X-MCP-Principal-Token-Ones-Mcp"] == ("test-only-ones-principal-token")
    assert transport.headers["X-MCP-Principal-Token-Test-Business-Mcp"] == (
        "test-only-second-principal-token"
    )
    serialized = json.dumps([execution_request, captured_events], sort_keys=True)
    assert "test-only-ones-principal-token" not in serialized
    assert "test-only-second-principal-token" not in serialized


def test_worker_projects_business_and_file_principals_to_separate_headers() -> None:
    issuer = _PrincipalTokenIssuer()
    transport = GoldenTransport()
    client, _ = _client(transport, principal_token_issuer=issuer)
    request = replace(
        _request(),
        context=replace(
            _request().context,
            runtime_protocol_version="1.2",
            allowed_tools=["ones_work_item_search", "file_prepare_materialization"],
            mcp_bindings=(
                McpRuntimeBinding(
                    server_code=ONES_MCP_SERVER_CODE,
                    tool_name="ones_work_item_search",
                    required_scope="mcp:ones-mcp:ones_work_item_search:invoke",
                    tool_schema_hash="c" * 64,
                ),
                McpRuntimeBinding(
                    server_code="file-service",
                    tool_name="file_prepare_materialization",
                    required_scope=("mcp:file-service:file_prepare_materialization:invoke"),
                    tool_schema_hash="d" * 64,
                ),
            ),
        ),
    )

    result = client.run(request)

    assert result.final_answer == "final answer"
    assert issuer.business_calls == [("job-1", ONES_MCP_SERVER_CODE)]
    assert issuer.file_job_ids == ["job-1"]
    assert transport.headers["X-MCP-Principal-Token-Ones-Mcp"] == ("test-only-principal-token")
    assert transport.headers["X-File-Principal-Token"] == ("test-only-file-principal-token")
    serialized = json.dumps(transport.request)
    assert "test-only-principal-token" not in serialized
    assert "test-only-file-principal-token" not in serialized


@pytest.mark.parametrize(
    "token",
    ["", "x" * 8193, "invalid\rprincipal", "invalid\nprincipal", "非ascii"],
)
def test_worker_rejects_invalid_business_principal_before_transport(token: str) -> None:
    issuer = _PrincipalTokenIssuer(business_tokens={ONES_MCP_SERVER_CODE: token})
    client, _ = _client(GoldenTransport(), principal_token_issuer=issuer)
    request = replace(
        _request(),
        context=replace(
            _request().context,
            allowed_tools=["ones_work_item_search"],
            mcp_bindings=(
                McpRuntimeBinding(
                    server_code=ONES_MCP_SERVER_CODE,
                    tool_name="ones_work_item_search",
                    required_scope="mcp:ones-mcp:ones_work_item_search:invoke",
                    tool_schema_hash="c" * 64,
                ),
            ),
        ),
    )

    with pytest.raises(NonRetryableExecutionError) as rejected:
        client.run(request)

    assert rejected.value.error_code == "principal_token_invalid"


def test_worker_maps_runtime_failure_and_preserves_prior_tool_events() -> None:
    client, _ = _client(GoldenTransport(terminal_status="FAILED"))

    with pytest.raises(RetryableExecutionError) as raised:
        client.run(_request())

    assert raised.value.error_code == "runtime_model_rate_limited"
    assert len(raised.value.tool_events) == 1
    assert raised.value.diagnostics["runtime_provenance"]["sdk_version"] == "0.3.226"


class BrokenSequenceTransport(GoldenTransport):
    def stream(self, **kwargs: Any) -> Iterator[bytes]:
        lines = list(super().stream(**kwargs))
        event = json.loads(lines[1])
        event["sequence"] = 3
        lines[1] = f"{json.dumps(event)}\n".encode()
        yield from lines


def test_worker_rejects_sequence_gap_before_committing_terminal() -> None:
    client, _ = _client(BrokenSequenceTransport())

    with pytest.raises(NonRetryableExecutionError) as raised:
        client.run(_request())

    assert raised.value.error_code == "runtime_protocol_error"


class RecoverTerminalTransport(GoldenTransport):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0
        self.digests: list[str] = []
        self.header_sets: list[dict[str, str]] = []

    def stream(self, **kwargs: Any) -> Iterator[bytes]:
        self.calls += 1
        self.header_sets.append(dict(kwargs["headers"]))
        lines = list(super().stream(**kwargs))
        self.digests.append(self.request["request_digest"])
        yield from (lines[:-1] if self.calls == 1 else lines)


def test_worker_reconnects_once_with_same_invocation_to_recover_terminal() -> None:
    transport = RecoverTerminalTransport()
    issuer = _PrincipalTokenIssuer()
    client, _ = _client(transport, principal_token_issuer=issuer)
    request = replace(
        _request(),
        context=replace(
            _request().context,
            allowed_tools=["ones_work_item_search"],
            mcp_bindings=(
                McpRuntimeBinding(
                    server_code=ONES_MCP_SERVER_CODE,
                    tool_name="ones_work_item_search",
                    required_scope="mcp:ones-mcp:ones_work_item_search:invoke",
                    tool_schema_hash="c" * 64,
                ),
            ),
        ),
    )

    result = client.run(request)

    assert result.final_answer == "final answer"
    assert transport.calls == 2
    assert len(set(transport.digests)) == 1
    assert issuer.business_calls == [("job-1", ONES_MCP_SERVER_CODE)]
    assert len(transport.header_sets) == 2
    assert transport.header_sets[0] == transport.header_sets[1]
    assert transport.header_sets[0]["X-MCP-Principal-Token-Ones-Mcp"] == (
        "test-only-principal-token"
    )


class InterruptedInProgressTransport(GoldenTransport):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0
        self.digests: list[str] = []

    def stream(self, **kwargs: Any) -> Iterator[bytes]:
        self.calls += 1
        lines = list(super().stream(**kwargs))
        self.digests.append(self.request["request_digest"])
        if self.calls == 1:
            yield lines[0]
        raise RetryableExecutionError(
            "runtime connection was lost",
            safe_message="Agent Runtime 通信失败",
            error_code="runtime_transport_error",
            diagnostics={"cancel_reason": "CLIENT_DISCONNECTED"},
        )


def test_observed_stream_never_advances_to_a_new_attempt_when_recovery_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = InterruptedInProgressTransport()
    persisted_events: list[dict[str, Any]] = []
    client, _ = _client(transport, events=persisted_events)
    monkeypatch.setattr(
        "app.modules.agent.infrastructure.runtime_http_client.time.sleep",
        lambda _seconds: None,
    )

    with pytest.raises(NonRetryableExecutionError) as raised:
        client.run(_request())

    assert raised.value.error_code == "runtime_invocation_outcome_unknown"
    assert raised.value.diagnostics["runtime_events_observed"] == 1
    assert transport.calls == 1 + 12
    assert len(set(transport.digests)) == 1
    assert [event["sequence"] for event in persisted_events] == [1]
    assert transport.cancel_payload["invocation_id"] == "job-1.attempt-0"


class ReconnectFailureTransport(GoldenTransport):
    def __init__(self, *, cancel_reason: str) -> None:
        super().__init__()
        self.calls = 0
        self.cancel_reason = cancel_reason

    def stream(self, **kwargs: Any) -> Iterator[bytes]:
        del kwargs
        self.calls += 1
        raise RetryableExecutionError(
            "runtime connection was lost",
            safe_message="Agent Runtime 通信失败",
            error_code="runtime_transport_error",
            diagnostics={"cancel_reason": self.cancel_reason},
        )
        yield b""  # pragma: no cover - keeps this a generator for the transport protocol


@pytest.mark.parametrize("reason", ["CLIENT_DISCONNECTED", "WORKER_TIMEOUT"])
def test_worker_cancels_same_invocation_when_terminal_reconnect_also_fails(
    reason: str,
) -> None:
    transport = ReconnectFailureTransport(cancel_reason=reason)
    client, _ = _client(transport)

    with pytest.raises(RetryableExecutionError) as raised:
        client.run(_request())

    assert raised.value.error_code == "runtime_transport_error"
    assert transport.calls == 2
    assert transport.cancel_payload == {
        "protocol_version": "1.0",
        "invocation_id": "job-1.attempt-0",
        "request_digest": transport.cancel_payload["request_digest"],
        "reason": reason,
    }
    assert len(transport.cancel_payload["request_digest"]) == 64


def test_worker_cancel_uses_same_invocation_digest_and_grant() -> None:
    transport = GoldenTransport()
    client, _ = _client(transport)

    result = client.cancel(_request(), "JOB_CANCELLED")

    assert result == {"status": "cancelled"}
    assert transport.cancel_payload["invocation_id"] == "job-1.attempt-0"
    assert len(transport.cancel_payload["request_digest"]) == 64


def test_runtime_client_rejects_missing_publication_or_model_binding() -> None:
    client, _ = _client(GoldenTransport())
    missing_publication = _request()
    missing_publication = replace(
        missing_publication,
        context=replace(missing_publication.context, publication_id=""),
    )

    with pytest.raises(NonRetryableExecutionError) as publication_error:
        client.run(missing_publication)
    assert publication_error.value.error_code == "runtime_publication_binding_missing"
