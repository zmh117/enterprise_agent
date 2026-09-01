from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol, cast
from urllib.parse import quote, urlsplit

import jwt

from app.modules.agent.domain.runtime import (
    AgentRunRequest,
    AgentRunResult,
    McpRuntimeBinding,
)
from app.modules.agent.infrastructure.runtime_protocol import (
    canonical_request_digest,
    validate_execution_request,
    validate_runtime_contract,
)
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.shared.mcp_server_policy import (
    DINGTALK_MCP_SERVER_CODE,
    FILE_MCP_SERVER_CODE,
    MAX_BUSINESS_PRINCIPAL_HEADER_BYTES,
    MAX_BUSINESS_PRINCIPAL_SERVERS,
    MAX_MCP_PRINCIPAL_TOKEN_BYTES,
    MCP_SERVER_POLICIES,
    ONES_MCP_SERVER_CODE,
    TOOL_MCP_SERVER_CODE,
    McpServerAuthMode,
    McpServerPolicy,
    business_principal_header_name,
    require_mcp_server_policy,
    validate_mcp_server_policies,
)
from app.shared.database import assert_external_io_allowed
from app.shared.build_identity import (
    BuildIdentity,
    BuildIdentityError,
    build_identity_from_environment,
)
from app.shared.exceptions import (
    ExecutionTimeout,
    NonRetryableExecutionError,
    RetryableExecutionError,
)
from app.shared.tool_contract import canonical_json_sha256
from app.shared.agent_run_audit_codec import decode_audit_chunks

MAX_EVENT_LINE_BYTES = 65_536
MAX_STREAM_BYTES = 2_097_152
MAX_STREAM_BYTES_V15 = 96 * 1024 * 1024
MAX_EVENTS = 2_048
IN_PROGRESS_RECOVERY_ATTEMPTS = 12
IN_PROGRESS_RECOVERY_DELAY_SECONDS = 0.5
STANDARD_TOOL_MCP_CODE = TOOL_MCP_SERVER_CODE
FILE_MCP_CODE = FILE_MCP_SERVER_CODE


def _audit_chunk_event_for_persistence(event: dict[str, Any]) -> dict[str, Any]:
    """Keep Runtime sequence evidence without copying audit chunk content."""
    payload = event.get("payload")
    chunk = payload if isinstance(payload, dict) else {}
    content = str(chunk.get("content") or "")
    return {
        **event,
        "payload": {
            "encoding": str(chunk.get("encoding") or "")[:32],
            "chunk_index": int(chunk.get("chunk_index") or 0),
            "chunk_count": int(chunk.get("chunk_count") or 0),
            "sha256": str(chunk.get("sha256") or "")[:64],
            "content_status": "OMITTED",
            "encoded_character_count": len(content),
        },
    }


def _manifest_canonical_item(item: Mapping[str, Any]) -> dict[str, Any]:
    try:
        allowed_actions = [str(value) for value in item["allowed_actions"]]
        return {
            "file_id": str(item["file_id"]),
            "version_id": str(item["version_id"]),
            "display_name": str(item["display_name"]),
            "format_code": str(item.get("format_code") or "TXT"),
            "source_kind": str(item["source_kind"]),
            "allowed_actions": allowed_actions,
            "auto_materialize": bool(item.get("auto_materialize")),
            "conflict_candidate": bool(item.get("conflict_candidate")),
            "source_received_at": item.get("source_received_at"),
            "version_created_at": str(item["version_created_at"]),
            "representation_id": item.get("representation_id"),
            "representation_kind": item.get("representation_kind"),
            "representation_size_bytes": item.get("representation_size_bytes"),
            "representation_sha256": item.get("representation_sha256"),
            "representation_format_code": item.get("representation_format_code"),
            "representation_created_at": item.get("representation_created_at"),
        }
    except (KeyError, TypeError) as exc:
        raise NonRetryableExecutionError(
            "Manifest v5 cannot be projected into the Runtime contract",
            safe_message="任务文件清单无效",
            error_code="file_manifest_runtime_invalid",
        ) from exc


def _manifest_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _require_current_file_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and pass Manifest v5 to Runtime without projection."""

    try:
        schema_version = int(manifest.get("schema_version") or 0)
    except (TypeError, ValueError) as exc:
        raise NonRetryableExecutionError(
            "Job File Manifest schema version is invalid",
            safe_message="任务文件清单无效",
            error_code="file_manifest_runtime_invalid",
        ) from exc
    if schema_version != 5:
        raise NonRetryableExecutionError(
            "Only Manifest schema v5 can enter the current Runtime",
            safe_message="任务文件清单版本不受支持",
            error_code="file_manifest_schema_unsupported",
        )
    raw_items = manifest.get("items")
    catalog_revision_id = manifest.get("workspace_catalog_revision_id")
    if (
        not isinstance(raw_items, list)
        or any(not isinstance(item, dict) for item in raw_items)
        or not isinstance(catalog_revision_id, str)
        or not catalog_revision_id
    ):
        raise NonRetryableExecutionError(
            "Manifest v5 projection facts are invalid",
            safe_message="任务文件清单无效",
            error_code="file_manifest_runtime_invalid",
        )
    canonical_items = [_manifest_canonical_item(item) for item in raw_items]
    stored_hash = _manifest_hash(
        {
            "schema_version": 5,
            "workspace_catalog_revision_id": catalog_revision_id,
            "items": canonical_items,
        }
    )
    if stored_hash != str(manifest.get("manifest_hash") or ""):
        raise NonRetryableExecutionError(
            "Manifest v5 hash does not match before Runtime transfer",
            safe_message="任务文件清单无效",
            error_code="file_manifest_runtime_invalid",
        )
    return {
        "schema_version": 5,
        "workspace_catalog_revision_id": catalog_revision_id,
        "manifest_hash": str(manifest["manifest_hash"]),
        "observed_at": manifest.get("observed_at"),
        "items": [dict(item) for item in raw_items],
        **(
            {"readability_notices": list(manifest["readability_notices"])}
            if "readability_notices" in manifest
            else {}
        ),
    }


def _runtime_event_count(value: object) -> int:
    if type(value) is int:
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


class RuntimeTransport(Protocol):
    def stream(
        self,
        *,
        url: str,
        body: bytes,
        headers: dict[str, str],
        timeout_seconds: int,
    ) -> Iterator[bytes]: ...

    def post(
        self,
        *,
        url: str,
        body: bytes,
        headers: dict[str, str],
        timeout_seconds: int,
    ) -> dict[str, Any]: ...


class PrincipalTokenIssuerPort(Protocol):
    def issue_business_mcp_for_job(self, *, job_id: str, server_code: str) -> str: ...

    def issue_file_for_job(self, *, job_id: str) -> str: ...


@dataclass(frozen=True, slots=True)
class RuntimePrincipalTokens:
    business: Mapping[str, str] = dataclass_field(default_factory=dict, repr=False)
    files: str = dataclass_field(default="", repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "business", MappingProxyType(dict(self.business)))

    def __repr__(self) -> str:
        return "RuntimePrincipalTokens(business=<hidden>, files=<hidden>)"


class UrlLibRuntimeTransport:
    def stream(
        self,
        *,
        url: str,
        body: bytes,
        headers: dict[str, str],
        timeout_seconds: int,
    ) -> Iterator[bytes]:
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                content_type = str(response.headers.get("content-type") or "").lower()
                if response.status != 200 or "application/x-ndjson" not in content_type:
                    raise RetryableExecutionError(
                        "Agent Runtime returned an invalid streaming response",
                        safe_message="Agent Runtime 返回了无效响应",
                        error_code="runtime_transport_invalid_response",
                    )
                yield from response
        except urllib.error.HTTPError as exc:
            if exc.code in {400, 401, 403, 404, 409, 413, 422}:
                raise NonRetryableExecutionError(
                    "Agent Runtime rejected the execution request",
                    safe_message="Agent Runtime 拒绝了执行请求",
                    error_code="runtime_request_rejected",
                ) from exc
            raise RetryableExecutionError(
                "Agent Runtime is temporarily unavailable",
                safe_message="Agent Runtime 暂时不可用",
                error_code="runtime_transport_error",
            ) from exc
        except TimeoutError as exc:
            raise RetryableExecutionError(
                "Agent Runtime transport timed out",
                safe_message="Agent Runtime 通信超时",
                error_code="runtime_transport_error",
                diagnostics={"cancel_reason": "WORKER_TIMEOUT"},
            ) from exc
        except OSError as exc:
            cancel_reason = (
                "WORKER_TIMEOUT"
                if isinstance(getattr(exc, "reason", None), TimeoutError)
                else "CLIENT_DISCONNECTED"
            )
            raise RetryableExecutionError(
                "Agent Runtime transport failed",
                safe_message="Agent Runtime 通信失败",
                error_code="runtime_transport_error",
                diagnostics={"cancel_reason": cancel_reason},
            ) from exc

    def post(
        self,
        *,
        url: str,
        body: bytes,
        headers: dict[str, str],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                if response.status != 200:
                    raise RetryableExecutionError(
                        "Agent Runtime cancel returned an invalid status",
                        safe_message="Agent Runtime 取消请求失败",
                        error_code="runtime_cancel_failed",
                    )
                payload = json.loads(response.read(65_536).decode("utf-8"))
                return payload if isinstance(payload, dict) else {}
        except (OSError, TimeoutError, ValueError) as exc:
            raise RetryableExecutionError(
                "Agent Runtime cancel transport failed",
                safe_message="Agent Runtime 取消请求失败",
                error_code="runtime_cancel_failed",
            ) from exc


class RuntimeGrantIssuer:
    def __init__(self, private_key: bytes, *, now: Callable[[], int] | None = None) -> None:
        if not private_key.startswith(b"-----BEGIN PRIVATE KEY-----"):
            raise ValueError("Runtime Grant private key must be PKCS8 PEM")
        self._private_key = private_key
        self._now = now or (lambda: int(time.time()))

    @classmethod
    def from_file(cls, path: str) -> RuntimeGrantIssuer:
        configured = path.strip()
        if not configured:
            raise ValueError("RUNTIME_GRANT_PRIVATE_KEY_FILE is required")
        key_path = Path(configured)
        try:
            if not 64 <= key_path.stat().st_size <= 16_384:
                raise ValueError("Runtime Grant private key size is invalid")
            private_key = key_path.read_bytes()
        except OSError as exc:
            raise ValueError("Runtime Grant private key is unreadable") from exc
        return cls(private_key)

    def issue(self, request: dict[str, Any]) -> str:
        now = self._now()
        timeout_seconds = int(request["limits"]["timeout_seconds"])
        ttl_seconds = min(timeout_seconds + 60, 15 * 60)
        claims = {
            "iss": "enterprise-agent-worker",
            "aud": "agent-runtime",
            "azp": "agent-worker",
            "runtime_kind": str(request["runtime_kind"]),
            "sub": str(request["app_user_id"]),
            "job_id": str(request["job_id"]),
            "invocation_id": str(request["invocation_id"]),
            "agent_publication_id": str(request["agent_publication_id"]),
            "application_publication_id": str(request["application_publication_id"]),
            "request_digest": str(request["request_digest"]),
            "iat": now,
            "nbf": now - 1,
            "exp": now + ttl_seconds,
            "jti": f"{request['invocation_id']}.{request['request_digest'][:16]}",
        }
        validate_runtime_contract(
            "RuntimeGrantClaims",
            claims,
            protocol_version=str(request["protocol_version"]),
        )
        return str(
            jwt.encode(
                claims,
                self._private_key,
                algorithm="EdDSA",
                headers={"typ": "JWT"},
            )
        )


@dataclass(frozen=True)
class RuntimeClientSettings:
    base_url: str
    allowed_runtime_hosts: tuple[str, ...]
    runtime_kind: str = "python-v1"
    allowed_mcp_server_codes: tuple[str, ...] = (
        STANDARD_TOOL_MCP_CODE,
        ONES_MCP_SERVER_CODE,
        DINGTALK_MCP_SERVER_CODE,
        FILE_MCP_CODE,
    )
    allow_insecure_internal_http: bool = False

    def execution_url(self) -> str:
        normalized = self.base_url.strip().rstrip("/")
        parsed = urlsplit(normalized)
        host = (parsed.hostname or "").lower()
        allowed_hosts = {value.strip().lower() for value in self.allowed_runtime_hosts}
        if (
            parsed.scheme not in {"http", "https"}
            or not host
            or host not in allowed_hosts
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("Agent Runtime URL is outside the deployment boundary")
        if parsed.scheme == "http":
            loopback = host in {"localhost", "127.0.0.1", "::1"}
            if not loopback and not self.allow_insecure_internal_http:
                raise ValueError(
                    "Agent Runtime HTTP requires explicit private-network opt-in; use HTTPS "
                    "for authenticated service identity outside local Compose"
                )
        return f"{normalized}/internal/v1/executions"


def probe_runtime_readiness(settings: RuntimeClientSettings) -> dict[str, Any]:
    """Passive service-identity/readiness probe; never invokes a model or MCP Tool."""

    def get(base_url: str, path: str, *, accepted_statuses: set[int]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{base_url}{path}",
            headers={"Accept": "application/json"},
            method="GET",
        )
        assert_external_io_allowed("agent_runtime.passive_readiness")
        try:
            response = urllib.request.urlopen(request, timeout=2)
        except urllib.error.HTTPError as exc:
            if exc.code not in accepted_statuses:
                raise
            response = exc
        with response:
            raw = response.read(65_537)
            if response.status not in accepted_statuses or len(raw) > 65_536:
                raise ValueError("Agent Runtime passive probe returned an invalid response")
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Agent Runtime passive probe payload is invalid")
        return payload

    try:
        settings.execution_url()
        base_url = settings.base_url.strip().rstrip("/")
        version = get(base_url, "/version", accepted_statuses={200})
        readiness = get(base_url, "/ready", accepted_statuses={200, 503})
        expected_release = build_identity_from_environment("control-plane")
        runtime_identity: BuildIdentity | None = None
        readiness_identity: BuildIdentity | None = None
        try:
            version_identity = version.get("build_identity")
            ready_identity = readiness.get("build_identity")
            if not isinstance(version_identity, dict) or not isinstance(
                ready_identity,
                dict,
            ):
                raise BuildIdentityError("Runtime build identity is missing")
            runtime_identity = BuildIdentity.from_dict(
                version_identity,
                expected_component="python-runtime",
            )
            readiness_identity = BuildIdentity.from_dict(
                ready_identity,
                expected_component="python-runtime",
            )
        except BuildIdentityError:
            runtime_identity = None
            readiness_identity = None
        build_identity_ready = (
            runtime_identity is not None
            and readiness_identity == runtime_identity
            and runtime_identity.source_revision == expected_release.source_revision
            and runtime_identity.build_id == expected_release.build_id
        )
        identity_ready = (
            version.get("runtime") == settings.runtime_kind
            and version.get("protocol_version") == "1.5"
            and isinstance(version.get("runtime_version"), str)
            and build_identity_ready
        )
        dependency_ready = (
            readiness.get("ready") is True
            and readiness.get("database") == "ready"
            and readiness.get("master_key") == "ready"
        )
        return {
            "configured": True,
            "ready": bool(identity_ready and dependency_ready),
            "identity": "verified" if identity_ready else "invalid",
            "database": readiness.get("database", "unavailable"),
            "master_key": readiness.get("master_key", "unavailable"),
            "runtime_version": (str(version.get("runtime_version")) if identity_ready else ""),
            "protocol_version": (str(version.get("protocol_version")) if identity_ready else ""),
            "sdk_version": str(version.get("sdk_version")) if identity_ready else "",
            "cli_version": str(version.get("cli_version")) if identity_ready else "",
            "build_identity": (
                runtime_identity.to_dict() if runtime_identity is not None else None
            ),
            "model_invoked": False,
            "mcp_invoked": False,
        }
    except Exception:
        return {
            "configured": True,
            "ready": False,
            "identity": "unavailable",
            "database": "unavailable",
            "master_key": "unavailable",
            "runtime_version": "",
            "protocol_version": "",
            "sdk_version": "",
            "cli_version": "",
            "build_identity": None,
            "model_invoked": False,
            "mcp_invoked": False,
        }


class AgentRuntimeHttpClient:
    def __init__(
        self,
        *,
        settings: RuntimeClientSettings,
        grant_issuer: RuntimeGrantIssuer,
        transport: RuntimeTransport | None = None,
        event_sink: Callable[[str, dict[str, Any]], None] | None = None,
        principal_token_issuer: PrincipalTokenIssuerPort | None = None,
        server_policies: Mapping[str, McpServerPolicy] | None = None,
        worker_build_identity: BuildIdentity | None = None,
    ) -> None:
        self.settings = settings
        self.execution_url = settings.execution_url()
        self.grant_issuer = grant_issuer
        self.transport = transport or UrlLibRuntimeTransport()
        self.event_sink = event_sink
        self.principal_token_issuer = principal_token_issuer
        self.worker_build_identity = worker_build_identity or build_identity_from_environment(
            "agent-worker"
        )
        self._server_policies = MappingProxyType(
            dict(MCP_SERVER_POLICIES if server_policies is None else server_policies)
        )
        validate_mcp_server_policies(self._server_policies)

    def run(self, run_request: AgentRunRequest) -> AgentRunResult:
        request = self._execution_request(run_request)
        grant = self.grant_issuer.issue(request)
        principal_tokens = self._principal_tokens(run_request, request)
        try:
            return self._consume_stream(run_request, request, grant, principal_tokens)
        except RetryableExecutionError as exc:
            if getattr(exc, "error_code", "") not in {
                "runtime_transport_error",
                "runtime_terminal_missing",
            }:
                raise
            observed = _runtime_event_count(exc.diagnostics.get("runtime_events_observed", 0))
            recovery_attempts = IN_PROGRESS_RECOVERY_ATTEMPTS if observed else 1
            recovery_error = exc
            for recovery_attempt in range(recovery_attempts):
                if observed:
                    time.sleep(IN_PROGRESS_RECOVERY_DELAY_SECONDS)
                try:
                    # Every recovery uses the exact same invocation and digest.
                    # Once a stream event was observed, no new Job attempt may
                    # start until this bounded recovery returns a terminal.
                    return self._consume_stream(run_request, request, grant, principal_tokens)
                except RetryableExecutionError as candidate:
                    recovery_error = candidate
                    observed = max(
                        observed,
                        _runtime_event_count(
                            candidate.diagnostics.get("runtime_events_observed", 0)
                        ),
                    )
                    if getattr(candidate, "error_code", "") not in {
                        "runtime_transport_error",
                        "runtime_terminal_missing",
                    }:
                        raise
                    if recovery_attempt + 1 < recovery_attempts:
                        continue
                if getattr(recovery_error, "error_code", "") not in {
                    "runtime_transport_error",
                    "runtime_terminal_missing",
                }:
                    raise
                reason = str(
                    getattr(recovery_error, "diagnostics", {}).get(
                        "cancel_reason", "CLIENT_DISCONNECTED"
                    )
                )
                if reason not in {
                    "JOB_CANCELLED",
                    "WORKER_TIMEOUT",
                    "CLIENT_DISCONNECTED",
                    "WORKER_SHUTDOWN",
                }:
                    reason = "CLIENT_DISCONNECTED"
                try:
                    self._cancel_prepared(run_request, request, reason)
                except RetryableExecutionError as cancel_error:
                    recovery_error.diagnostics["cancel_error_code"] = getattr(
                        cancel_error, "error_code", "runtime_cancel_failed"
                    )
                if observed:
                    raise NonRetryableExecutionError(
                        "Runtime invocation outcome is unknown after an interrupted stream",
                        safe_message=("Agent Runtime 执行中断；为避免重复模型调用，本次执行已失败"),
                        tool_events=recovery_error.tool_events,
                        error_code="runtime_invocation_outcome_unknown",
                        diagnostics={
                            **recovery_error.diagnostics,
                            "runtime_events_observed": observed,
                        },
                    ) from recovery_error
                raise
            raise recovery_error

    def _consume_stream(
        self,
        run_request: AgentRunRequest,
        request: dict[str, Any],
        grant: str,
        principal_tokens: RuntimePrincipalTokens,
    ) -> AgentRunResult:
        body = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {grant}",
            "Content-Type": "application/json",
            "Accept": "application/x-ndjson",
            "X-Correlation-Id": f"job:{run_request.job_id}",
        }
        for server_code, token in sorted(principal_tokens.business.items()):
            headers[
                business_principal_header_name(
                    server_code,
                    policies=self._server_policies,
                )
            ] = token
        if principal_tokens.files:
            headers["X-File-Principal-Token"] = principal_tokens.files
        events: list[dict[str, Any]] = []
        audit_chunks: list[dict[str, Any]] = []
        tool_events: list[dict[str, Any]] = []
        total_bytes = 0
        event_count = 0
        terminal: dict[str, Any] | None = None
        tool_contract_status: str | None = None
        expected_sequence = 1
        stream = iter(
            self.transport.stream(
                url=self.execution_url,
                body=body,
                headers=headers,
                timeout_seconds=run_request.context.timeout_seconds + 10,
            )
        )
        while True:
            try:
                raw_line = next(stream)
            except StopIteration:
                break
            except RetryableExecutionError as exc:
                exc.diagnostics["runtime_events_observed"] = event_count
                if tool_events:
                    exc.tool_events = tool_events
                raise
            total_bytes += len(raw_line)
            stream_limit = (
                MAX_STREAM_BYTES_V15 if request["protocol_version"] == "1.5" else MAX_STREAM_BYTES
            )
            if len(raw_line) > MAX_EVENT_LINE_BYTES or total_bytes > stream_limit:
                raise self._protocol_error(
                    "Runtime event stream exceeds its byte boundary", tool_events
                )
            if event_count >= MAX_EVENTS:
                raise self._protocol_error(
                    "Runtime event stream exceeds its event boundary", tool_events
                )
            try:
                event = json.loads(raw_line.decode("utf-8"))
                validate_runtime_contract("RuntimeEvent", event)
            except (UnicodeError, ValueError, TypeError) as exc:
                raise self._protocol_error("Runtime emitted an invalid event", tool_events) from exc
            if (
                event["invocation_id"] != request["invocation_id"]
                or event["request_digest"] != request["request_digest"]
                or event["protocol_version"] != request["protocol_version"]
                or int(event["sequence"]) != expected_sequence
                or terminal is not None
            ):
                raise self._protocol_error(
                    "Runtime event identity or sequence mismatch", tool_events
                )
            expected_sequence += 1
            event_count += 1
            event_type = str(event["event_type"])
            if event_type == "audit_chunk":
                audit_chunks.append(dict(event["payload"]))
            else:
                events.append(event)
            if tool_contract_status is None and event_type not in {
                "execution_started",
                "tool_contract_observed",
            }:
                raise self._protocol_error(
                    "Runtime event preceded the Tool contract observation",
                    tool_events,
                )
            if event["event_type"] == "tool_contract_observed":
                if tool_contract_status is not None:
                    raise self._protocol_error(
                        "Runtime emitted more than one Tool contract observation",
                        tool_events,
                    )
                observation = dict(event["payload"])
                observation_hash = str(observation.pop("observation_hash", ""))
                identities = observation.get("component_build_identities") or []
                if (
                    observation_hash != canonical_json_sha256(observation)
                    or observation.get("snapshot_hash") != request["job_tool_snapshot_hash"]
                    or observation.get("prompt", {}).get("template_version")
                    != request["prompt"]["template_version"]
                    or request["control_plane_build_identity"] not in identities
                    or request["worker_build_identity"] not in identities
                ):
                    raise self._protocol_error(
                        "Runtime Tool contract observation identity mismatch",
                        tool_events,
                    )
                tool_contract_status = str(observation.get("status") or "")
            elif tool_contract_status != "MATCH" and event_type in {
                "runtime_initialized",
                "model_call",
                "api_retry",
                "tool_event",
                "assistant_text",
            }:
                raise self._protocol_error(
                    "Runtime continued execution after Tool contract drift",
                    tool_events,
                )
            if self.event_sink is not None:
                persisted_event = (
                    _audit_chunk_event_for_persistence(event)
                    if event_type == "audit_chunk"
                    else event
                )
                self.event_sink(run_request.job_id, persisted_event)
            if event["event_type"] == "tool_event":
                tool_events.append(
                    {
                        **dict(event["payload"]),
                        "invocation_id": str(event["invocation_id"]),
                    }
                )
            if event["event_type"] == "terminal":
                terminal = dict(event["payload"])
        if terminal is None:
            raise RetryableExecutionError(
                "Agent Runtime stream ended without a terminal result",
                safe_message="Agent Runtime 未返回终态",
                tool_events=tool_events,
                error_code="runtime_terminal_missing",
                diagnostics={"runtime_events_observed": event_count},
            )
        if tool_contract_status is None:
            raise self._protocol_error(
                "Runtime terminal omitted the Tool contract observation",
                tool_events,
            )
        if tool_contract_status != "MATCH" and terminal.get("status") == "SUCCEEDED":
            raise self._protocol_error(
                "Runtime succeeded despite Tool contract drift",
                tool_events,
            )
        if int(terminal["last_sequence"]) != expected_sequence - 1:
            raise self._protocol_error("Runtime terminal sequence mismatch", tool_events)
        provenance = dict(terminal["runtime_provenance"])
        run_audit: dict[str, Any] = {}
        audit_sha256 = str(terminal.get("audit_sha256") or "")
        audit_chunk_count = int(terminal.get("audit_chunk_count") or 0)
        if audit_sha256 or audit_chunk_count or audit_chunks:
            try:
                run_audit = decode_audit_chunks(
                    audit_chunks,
                    expected_sha256=audit_sha256,
                    expected_count=audit_chunk_count,
                )
            except ValueError as exc:
                raise self._protocol_error(
                    "Runtime Agent run audit is incomplete or invalid",
                    tool_events,
                ) from exc
        if terminal["status"] == "SUCCEEDED":
            return AgentRunResult(
                final_answer=str(terminal["final_answer"]),
                tool_events=tool_events,
                runtime_provenance=provenance,
                runtime_events=[
                    event
                    for event in events
                    if event["event_type"]
                    in {
                        "tool_contract_observed",
                        "runtime_initialized",
                        "model_call",
                        "api_retry",
                    }
                ],
                execution_accounting=dict(terminal.get("accounting") or {}),
                run_audit=run_audit,
            )
        failure = dict(terminal.get("failure") or {})
        failure_code = str(failure.get("code") or "runtime_failure")
        exception_type: type[
            ExecutionTimeout | RetryableExecutionError | NonRetryableExecutionError
        ]
        if failure_code == "runtime_timeout":
            exception_type = ExecutionTimeout
        elif failure.get("retry_class") == "TRANSIENT":
            exception_type = RetryableExecutionError
        else:
            exception_type = NonRetryableExecutionError
        error = exception_type(
            f"Agent Runtime failed with {failure_code}",
            safe_message=str(failure.get("safe_message") or "Agent Runtime 执行失败"),
            tool_events=tool_events,
            error_code=failure_code,
            diagnostics={
                "runtime_provenance": provenance,
                "runtime_events": [
                    event
                    for event in events
                    if event["event_type"]
                    in {
                        "tool_contract_observed",
                        "runtime_initialized",
                        "model_call",
                        "api_retry",
                    }
                ],
                "execution_accounting": dict(terminal.get("accounting") or {}),
            },
        )
        setattr(error, "run_audit", run_audit)
        raise error

    def cancel(self, run_request: AgentRunRequest, reason: str) -> dict[str, Any]:
        request = self._execution_request(run_request)
        return self._cancel_prepared(run_request, request, reason)

    def _cancel_prepared(
        self,
        run_request: AgentRunRequest,
        request: dict[str, Any],
        reason: str,
    ) -> dict[str, Any]:
        grant = self.grant_issuer.issue(request)
        payload = {
            "protocol_version": request["protocol_version"],
            "invocation_id": request["invocation_id"],
            "request_digest": request["request_digest"],
            "reason": reason,
        }
        validate_runtime_contract("CancelRequest", payload)
        return self.transport.post(
            url=(
                f"{self.settings.base_url.rstrip('/')}/internal/v1/executions/"
                f"{quote(str(request['invocation_id']), safe='')}/cancel"
            ),
            body=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {grant}",
                "Content-Type": "application/json",
                "X-Correlation-Id": f"job:{run_request.job_id}",
            },
            timeout_seconds=5,
        )

    def _execution_request(self, run_request: AgentRunRequest) -> dict[str, Any]:
        context = run_request.context
        if context.runtime_kind != self.settings.runtime_kind:
            raise NonRetryableExecutionError(
                "Job runtime kind does not match the fixed Runtime client",
                safe_message="当前 Job 与目标 Runtime 不匹配",
                error_code="runtime_kind_mismatch",
            )
        binding = context.model_runtime_binding
        if binding is None or not binding.connection_revision_id or len(binding.config_hash) != 64:
            raise NonRetryableExecutionError(
                "Agent Runtime requires a frozen model connection revision",
                safe_message="当前 Job 缺少固定模型连接",
                error_code="runtime_model_binding_missing",
            )
        if not context.publication_id or not context.application_publication_id:
            raise NonRetryableExecutionError(
                "Agent Runtime requires frozen Agent and Application publications",
                safe_message="当前 Job 缺少固定发布版本",
                error_code="runtime_publication_binding_missing",
            )
        if len(context.job_tool_snapshot_hash) != 64:
            raise NonRetryableExecutionError(
                "Agent Runtime requires the frozen Job MCP Tool Snapshot hash",
                safe_message="当前 Job 缺少 MCP 工具快照完整性信息",
                error_code="mcp_tool_snapshot_missing",
            )
        try:
            control_plane_build_identity = BuildIdentity.from_dict(
                context.control_plane_build_identity,
                expected_component="control-plane",
            ).to_dict()
        except ValueError as exc:
            raise NonRetryableExecutionError(
                "Agent Runtime requires a valid Control Plane build identity",
                safe_message="当前 Job 构建身份无效",
                error_code="build_identity_invalid",
            ) from exc
        grouped: dict[str, list[McpRuntimeBinding]] = {}
        for binding_item in self._runtime_bindings(run_request):
            if binding_item.server_code not in self.settings.allowed_mcp_server_codes:
                raise NonRetryableExecutionError(
                    "Job references an unapproved MCP server",
                    safe_message="当前 Job 引用了未允许的 MCP 服务",
                    error_code="mcp_server_not_allowed",
                )
            try:
                require_mcp_server_policy(
                    binding_item.server_code,
                    policies=self._server_policies,
                )
            except ValueError as exc:
                raise NonRetryableExecutionError(
                    "Job references an MCP server without a fixed auth policy",
                    safe_message="当前 Job 引用了鉴权策略无效的 MCP 服务",
                    error_code="mcp_server_policy_invalid",
                ) from exc
            grouped.setdefault(binding_item.server_code, []).append(binding_item)
        mcp_servers: list[dict[str, Any]] = []
        for server_code, tool_bindings in sorted(grouped.items()):
            tools = []
            for item in sorted(tool_bindings, key=lambda value: value.tool_name):
                tool = {
                    "tool_name": item.tool_name,
                    "required_scope": item.required_scope,
                    "tool_schema_hash": item.tool_schema_hash,
                }
                for field in (
                    "resource_code",
                    "resource_deployment_id",
                    "resource_revision_id",
                ):
                    value = str(getattr(item, field) or "")
                    if value:
                        tool[field] = value
                tools.append(tool)
            mcp_servers.append(
                {
                    "server_code": server_code,
                    "tools": tools,
                }
            )
        protocol_version = str(context.runtime_protocol_version or "")
        if protocol_version not in {"1.4", "1.5"}:
            raise NonRetryableExecutionError(
                "Job runtime protocol version is unsupported",
                safe_message="当前 Job Runtime 协议版本不受支持",
                error_code="runtime_protocol_unsupported",
            )
        retrieved_context = dict(context.retrieved_context)
        raw_manifest = retrieved_context.get("file_manifest")
        current_manifest = (
            _require_current_file_manifest(raw_manifest)
            if isinstance(raw_manifest, Mapping)
            else None
        )
        if current_manifest is not None:
            retrieved_context["file_manifest"] = current_manifest
        request: dict[str, Any] = {
            "protocol_version": protocol_version,
            "runtime_kind": context.runtime_kind,
            "invocation_id": run_request.invocation_id or f"{run_request.job_id}.attempt-0",
            "request_digest": "0" * 64,
            "job_id": run_request.job_id,
            "app_user_id": run_request.user_id,
            "project_code": run_request.project_code,
            "agent_publication_id": context.publication_id,
            "application_publication_id": context.application_publication_id,
            "job_tool_snapshot_hash": context.job_tool_snapshot_hash,
            "control_plane_build_identity": control_plane_build_identity,
            "worker_build_identity": self.worker_build_identity.to_dict(),
            "model_connection": {
                "revision_id": binding.connection_revision_id,
                "config_hash": binding.config_hash,
            },
            "prompt": {
                "template_version": context.prompt_template_version,
                "system_role": context.system_role,
                "safety_rules": list(context.safety_rules),
                "business_instructions": context.business_instructions,
                "tool_restrictions": list(context.tool_restrictions),
                "user_question": context.user_question,
                "conversation_summary": context.conversation_summary,
                "retrieved_context": retrieved_context,
                "skills": context.skills,
                "mcp_unavailable_notices": [
                    {
                        "tool_name": notice.tool_name,
                        "reason_code": notice.reason_code,
                        "message": notice.message,
                    }
                    for notice in context.mcp_unavailable_notices
                ],
            },
            "limits": {
                "timeout_seconds": context.timeout_seconds,
                "max_turns": context.max_turns,
                "max_tool_calls": context.max_tool_calls,
            },
            "mcp_servers": mcp_servers,
        }
        request["file_context"] = {"file_manifest": current_manifest}
        request["request_digest"] = canonical_request_digest(request)
        return cast(dict[str, Any], validate_execution_request(request))

    def _principal_tokens(
        self,
        run_request: AgentRunRequest,
        request: dict[str, Any],
    ) -> RuntimePrincipalTokens:
        server_codes = {
            str(server.get("server_code") or "")
            for server in request.get("mcp_servers") or []
            if isinstance(server, dict)
        }
        business_server_codes: list[str] = []
        requires_files = False
        for server_code in sorted(server_codes):
            try:
                policy = require_mcp_server_policy(
                    server_code,
                    policies=self._server_policies,
                )
            except ValueError as exc:
                raise NonRetryableExecutionError(
                    "Runtime request references an MCP server without a fixed auth policy",
                    safe_message="当前 Job 引用了鉴权策略无效的 MCP 服务",
                    error_code="mcp_server_policy_invalid",
                ) from exc
            if policy.auth_mode is McpServerAuthMode.BUSINESS_PRINCIPAL_JWT:
                business_server_codes.append(server_code)
            elif policy.auth_mode is McpServerAuthMode.FILE_PRINCIPAL_JWT:
                requires_files = True
        if not business_server_codes and not requires_files:
            return RuntimePrincipalTokens()
        if len(business_server_codes) > MAX_BUSINESS_PRINCIPAL_SERVERS:
            raise NonRetryableExecutionError(
                "Runtime request requires too many Business Principal Tokens",
                safe_message="当前 Job 需要的业务身份凭证过多",
                error_code="principal_token_count_exceeded",
            )
        if self.principal_token_issuer is None:
            raise NonRetryableExecutionError(
                "Governed MCP requires a Principal Token issuer",
                safe_message="当前 Job 缺少平台身份凭证签发服务",
                error_code="principal_token_issuer_unavailable",
            )
        business_tokens = {
            server_code: self._validated_principal_token(
                self.principal_token_issuer.issue_business_mcp_for_job(
                    job_id=run_request.job_id,
                    server_code=server_code,
                )
            )
            for server_code in business_server_codes
        }
        file_token = (
            self._validated_principal_token(
                self.principal_token_issuer.issue_file_for_job(job_id=run_request.job_id)
            )
            if requires_files
            else ""
        )
        total_header_bytes = sum(
            len(
                business_principal_header_name(
                    server_code,
                    policies=self._server_policies,
                ).encode("ascii")
            )
            + len(token.encode("ascii"))
            for server_code, token in business_tokens.items()
        )
        if file_token:
            total_header_bytes += len("X-File-Principal-Token") + len(file_token.encode("ascii"))
        if total_header_bytes > MAX_BUSINESS_PRINCIPAL_HEADER_BYTES:
            raise NonRetryableExecutionError(
                "Runtime Principal Token headers are too large",
                safe_message="当前 Job 的业务身份凭证过大",
                error_code="principal_token_headers_too_large",
            )
        return RuntimePrincipalTokens(business=business_tokens, files=file_token)

    @staticmethod
    def _validated_principal_token(token: str) -> str:
        try:
            encoded = token.encode("ascii")
        except UnicodeError as exc:
            raise NonRetryableExecutionError(
                "Principal Token is not ASCII",
                safe_message="平台身份凭证无效",
                error_code="principal_token_invalid",
            ) from exc
        if (
            not token
            or len(encoded) > MAX_MCP_PRINCIPAL_TOKEN_BYTES
            or "\r" in token
            or "\n" in token
        ):
            raise NonRetryableExecutionError(
                "Principal Token is invalid",
                safe_message="平台身份凭证无效",
                error_code="principal_token_invalid",
            )
        return token

    @staticmethod
    def _runtime_bindings(run_request: AgentRunRequest) -> tuple[McpRuntimeBinding, ...]:
        context = run_request.context
        if context.mcp_bindings:
            return context.mcp_bindings
        bindings: list[McpRuntimeBinding] = []
        for tool_name in context.allowed_tools:
            definition = MCP_TOOL_MANIFEST.get(tool_name)
            if definition is None:
                raise NonRetryableExecutionError(
                    "Job references an unknown MCP Tool",
                    safe_message="当前 Job 包含未知 MCP 工具",
                    error_code="runtime_tool_mapping_missing",
                )
            bindings.append(
                McpRuntimeBinding(
                    server_code=definition.server_code,
                    tool_name=tool_name,
                    required_scope=f"tool:{tool_name}",
                    tool_schema_hash=definition.schema_hash,
                )
            )
        return tuple(bindings)

    @staticmethod
    def _protocol_error(
        message: str, tool_events: list[dict[str, Any]]
    ) -> NonRetryableExecutionError:
        return NonRetryableExecutionError(
            message,
            safe_message="Agent Runtime 协议校验失败",
            tool_events=tool_events,
            error_code="runtime_protocol_error",
        )
