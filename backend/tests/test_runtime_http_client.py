from __future__ import annotations

import hashlib
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
from app.shared.exceptions import (
    ExecutionTimeout,
    NonRetryableExecutionError,
    RetryableExecutionError,
)
from app.shared.build_identity import BuildIdentity
from app.shared.tool_contract import canonical_json_sha256
from app.python_runtime.executor import agent_request_from_runtime_request
from app.python_runtime.tool_contract import build_tool_contract_observation
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
                    "protocol_version": "1.4",
                    "sdk_version": "0.3.226",
                    "cli_version": "2.1.226",
                    "build_identity": {
                        "component": "python-runtime",
                        "source_revision": "test-revision",
                        "build_id": "test-build",
                        "platform": "linux/arm64",
                        "image_digest": f"sha256:{'1' * 64}",
                    },
                }
            )
        return _PassiveResponse(
            {
                "ready": True,
                "database": "ready",
                "master_key": "ready",
                "build_identity": {
                    "component": "python-runtime",
                    "source_revision": "test-revision",
                    "build_id": "test-build",
                    "platform": "linux/arm64",
                    "image_digest": f"sha256:{'1' * 64}",
                },
            }
        )

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
    assert result["build_identity"]["platform"] == "linux/arm64"
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
                    "protocol_version": "1.4",
                    "sdk_version": "0.3.226",
                    "cli_version": "2.1.226",
                    "build_identity": {
                        "component": "python-runtime",
                        "source_revision": "test-revision",
                        "build_id": "test-build",
                        "platform": "linux/amd64",
                    },
                }
            )
        body = json.dumps(
            {
                "ready": False,
                "database": "ready",
                "master_key": "unavailable",
                "build_identity": {
                    "component": "python-runtime",
                    "source_revision": "test-revision",
                    "build_id": "test-build",
                    "platform": "linux/amd64",
                },
            }
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


def test_passive_runtime_readiness_fails_closed_without_build_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request: Any, timeout: int) -> _PassiveResponse:
        del timeout
        if request.full_url.endswith("/version"):
            return _PassiveResponse(
                {
                    "runtime": "python-v1",
                    "runtime_version": "0.1.0",
                    "protocol_version": "1.4",
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

    assert result["ready"] is False
    assert result["identity"] == "invalid"
    assert result["build_identity"] is None


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
        job_tool_snapshot_hash="f" * 64,
        control_plane_build_identity={
            "component": "control-plane",
            "source_revision": "test-revision",
            "build_id": "test-build",
            "platform": "linux/amd64",
        },
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
        "runtime_build_identity": {
            "component": "python-runtime",
            "source_revision": "test-revision",
            "build_id": "test-build",
            "platform": "linux/amd64",
        },
        "model_connection_revision_id": request["model_connection"]["revision_id"],
        "model_connection_config_hash": request["model_connection"]["config_hash"],
    }


class GoldenTransport:
    def __init__(
        self,
        *,
        terminal_status: str = "SUCCEEDED",
        failure: dict[str, str] | None = None,
    ) -> None:
        self.terminal_status = terminal_status
        self.failure = failure
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
        file_tools = [
            {
                "server_code": "file-service",
                "tool_name": str(tool["tool_name"]),
                "schema_hash": str(tool["tool_schema_hash"]),
                "status": "MATCH",
            }
            for server in self.request["mcp_servers"]
            if server["server_code"] == "file-service"
            for tool in server["tools"]
        ]
        file_live = (
            {
                "status": "OBSERVED",
                "tools": file_tools,
                "toolset_hash": canonical_json_sha256(
                    [
                        {
                            "tool_name": item["tool_name"],
                            "schema_hash": item["schema_hash"],
                        }
                        for item in file_tools
                    ]
                ),
                "build_identity": {
                    "component": "file-service",
                    "source_revision": "test-revision",
                    "build_id": "test-build",
                    "platform": "linux/amd64",
                },
            }
            if file_tools
            else None
        )
        observation = build_tool_contract_observation(
            agent_request_from_runtime_request(self.request, None).context,
            file_live=file_live,
            runtime_build_identity=BuildIdentity(
                "python-runtime",
                "test-revision",
                "test-build",
                "linux/amd64",
            ),
        )
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
                "event_type": "tool_contract_observed",
                "timestamp": "2026-08-09T00:00:01Z",
                "payload": observation,
            },
            {
                "protocol_version": self.request["protocol_version"],
                "invocation_id": self.request["invocation_id"],
                "request_digest": self.request["request_digest"],
                "sequence": 3,
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
                    "tool_origin": "mcp",
                    "mcp_call_id": "mcp-call-1",
                    "persisted_tool_call_id": "agent-tool-call-1",
                },
            },
        ]
        terminal: dict[str, Any] = {
            "protocol_version": self.request["protocol_version"],
            "invocation_id": self.request["invocation_id"],
            "request_digest": self.request["request_digest"],
            "last_sequence": 4,
            "status": self.terminal_status,
            "usage": {
                "input_tokens": 10,
                "output_tokens": 4,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
            "runtime_provenance": provenance,
        }
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
            terminal["failure"] = self.failure or {
                "code": "runtime_model_rate_limited",
                "retry_class": "TRANSIENT",
                "safe_message": "模型服务当前繁忙，请稍后重试",
            }
        events.append(
            {
                "protocol_version": self.request["protocol_version"],
                "invocation_id": self.request["invocation_id"],
                "request_digest": self.request["request_digest"],
                "sequence": 4,
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
    assert [event["sequence"] for event in persisted_events] == [1, 2, 3, 4]
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


def test_worker_passes_manifest_v5_without_projection() -> None:
    transport = GoldenTransport()
    client, _public_pem = _client(transport)
    canonical_item = {
        "file_id": "file-source-1",
        "version_id": "version-source-1",
        "display_name": "source.txt",
        "format_code": "TXT",
        "source_kind": "CURRENT_MESSAGE",
        "allowed_actions": ["READ_METADATA", "MATERIALIZE"],
        "auto_materialize": True,
        "conflict_candidate": False,
        "source_received_at": "2026-08-22T02:26:30+00:00",
        "version_created_at": "2026-08-22T02:26:31+00:00",
        "representation_id": None,
        "representation_kind": None,
        "representation_size_bytes": None,
        "representation_sha256": None,
        "representation_format_code": None,
        "representation_created_at": None,
    }
    runtime_item = {
        key: value for key, value in canonical_item.items() if not key.startswith("representation_")
    }
    stored_hash = hashlib.sha256(
        json.dumps(
            {
                "schema_version": 5,
                "workspace_catalog_revision_id": "workspace-catalog-revision-1",
                "items": [canonical_item],
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    context = replace(
        _context(),
        runtime_protocol_version="1.4",
        retrieved_context={
            "file_manifest": {
                "schema_version": 5,
                "workspace_catalog_revision_id": "workspace-catalog-revision-1",
                "manifest_hash": stored_hash,
                "observed_at": "2026-08-22T02:26:33.478129+00:00",
                "readability_notices": [
                    {
                        "file_name": "failed.docx",
                        "status": "UNAVAILABLE",
                        "error_code": "docling_conversion_failed",
                    }
                ],
                "items": [
                    {
                        **runtime_item,
                        "materialization_size_bytes": 128,
                    }
                ],
            }
        },
    )

    result = client.run(replace(_request(), context=context))

    assert result.final_answer == "final answer"
    projected = transport.request["prompt"]["retrieved_context"]["file_manifest"]
    assert projected == transport.request["file_context"]["file_manifest"]
    assert projected["schema_version"] == 5
    assert projected["workspace_catalog_revision_id"] == "workspace-catalog-revision-1"
    assert projected["items"][0]["materialization_size_bytes"] == 128
    assert projected["items"][0]["file_id"] == "file-source-1"
    assert projected["readability_notices"] == [
        {
            "file_name": "failed.docx",
            "status": "UNAVAILABLE",
            "error_code": "docling_conversion_failed",
        }
    ]
    assert (
        projected["manifest_hash"]
        == hashlib.sha256(
            json.dumps(
                {
                    "schema_version": 5,
                    "workspace_catalog_revision_id": "workspace-catalog-revision-1",
                    "items": [canonical_item],
                },
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
    )


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
            runtime_protocol_version="1.4",
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
            runtime_protocol_version="1.4",
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
            runtime_protocol_version="1.4",
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


@pytest.mark.parametrize("retry_class", ["NEVER", "TRANSIENT"])
def test_worker_restores_runtime_timeout_without_retryable_transport_semantics(
    retry_class: str,
) -> None:
    client, _ = _client(
        GoldenTransport(
            terminal_status="FAILED",
            failure={
                "code": "runtime_timeout",
                "retry_class": retry_class,
                "safe_message": "Claude 运行超时",
            },
        )
    )

    with pytest.raises(ExecutionTimeout) as raised:
        client.run(_request())

    assert raised.value.error_code == "runtime_timeout"
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


def _resequence_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for sequence, event in enumerate(events, start=1):
        event["sequence"] = sequence
        if event["event_type"] == "terminal":
            event["payload"]["last_sequence"] = sequence
    return events


class MissingToolContractTransport(GoldenTransport):
    def stream(self, **kwargs: Any) -> Iterator[bytes]:
        events = [json.loads(line) for line in super().stream(**kwargs)]
        events = [event for event in events if event["event_type"] != "tool_contract_observed"]
        yield from (f"{json.dumps(event)}\n".encode() for event in _resequence_events(events))


class DuplicateToolContractTransport(GoldenTransport):
    def stream(self, **kwargs: Any) -> Iterator[bytes]:
        events = [json.loads(line) for line in super().stream(**kwargs)]
        observation = next(
            event for event in events if event["event_type"] == "tool_contract_observed"
        )
        events.insert(2, json.loads(json.dumps(observation)))
        yield from (f"{json.dumps(event)}\n".encode() for event in _resequence_events(events))


class DriftSucceededTransport(GoldenTransport):
    def stream(self, **kwargs: Any) -> Iterator[bytes]:
        events = [json.loads(line) for line in super().stream(**kwargs)]
        events = [event for event in events if event["event_type"] != "tool_event"]
        observation = next(
            event for event in events if event["event_type"] == "tool_contract_observed"
        )
        payload = observation["payload"]
        payload["status"] = "DRIFT"
        unhashed = {key: value for key, value in payload.items() if key != "observation_hash"}
        payload["observation_hash"] = canonical_json_sha256(unhashed)
        yield from (f"{json.dumps(event)}\n".encode() for event in _resequence_events(events))


@pytest.mark.parametrize(
    "transport",
    [MissingToolContractTransport(), DuplicateToolContractTransport(), DriftSucceededTransport()],
)
def test_worker_rejects_missing_duplicate_or_nonmatching_tool_contract(
    transport: GoldenTransport,
) -> None:
    client, _ = _client(transport)

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
        "protocol_version": "1.4",
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
