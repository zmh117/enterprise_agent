# Generated from contracts/agent-runtime/v1.3. Do not edit.
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, NotRequired, TypedDict

from jsonschema import Draft202012Validator

PROTOCOL_VERSION = "1.3"
CONTRACT_SCHEMA_SHA256 = "67d89960ad67945a17057eb388572314c94dd068661c7f3ff13c8d5b194d6867"
CONTRACT_SCHEMA_PATH = (
    Path(__file__).resolve().parents[5]
    / "contracts"
    / "agent-runtime"
    / "v1.3"
    / "protocol.schema.json"
)

Identifier = str
Sha256Digest = str
RuntimeKind = Literal["python-v1"]
SafeMessage = str
TextFormatCode = Literal["TXT", "LOG", "MARKDOWN"]
DocumentSourceFormatCode = Literal["PDF", "DOCX", "PPTX", "XLSX", "PNG", "JPEG", "WEBP"]
RepresentationKind = Literal["MARKDOWN"]
FileAction = Literal["READ_METADATA", "MATERIALIZE", "EDIT", "COMMIT", "RETAIN", "DELIVER"]
RuntimeEvent = (
    dict[str, object]
    | dict[str, object]
    | dict[str, object]
    | dict[str, object]
    | dict[str, object]
    | dict[str, object]
    | dict[str, object]
)


class JsonSummary(TypedDict):
    pass


class ExecutionLimits(TypedDict):
    timeout_seconds: int
    max_turns: int
    max_tool_calls: int


class Prompt(TypedDict):
    system_role: str
    safety_rules: list[str]
    business_instructions: str
    tool_restrictions: list[str]
    user_question: str
    conversation_summary: str
    retrieved_context: dict[str, object]
    skills: NotRequired[dict[str, str]]
    mcp_unavailable_notices: NotRequired[list[dict[str, object]]]


class ModelConnectionBinding(TypedDict):
    revision_id: Identifier
    config_hash: Sha256Digest


class ModelProbeRequest(TypedDict):
    protocol_version: Literal["1.3"]
    runtime_kind: RuntimeKind
    probe_id: Identifier
    model_connection: ModelConnectionBinding
    timeout_seconds: int


class ModelProbeCredentialEnvelope(TypedDict):
    algorithm: Literal["AES-256-GCM-DERIVED-PROBE-V1"]
    nonce: str
    ciphertext: str
    expires_at: int


class DraftModelProbeRequest(TypedDict):
    protocol_version: Literal["1.3"]
    runtime_kind: RuntimeKind
    probe_id: Identifier
    config_hash: Sha256Digest
    credential_envelope: ModelProbeCredentialEnvelope
    timeout_seconds: int


class ModelProbeFailure(TypedDict):
    code: Identifier
    safe_message: SafeMessage


class ModelProbeResponse(TypedDict):
    protocol_version: Literal["1.3"]
    runtime_kind: RuntimeKind
    probe_id: Identifier
    success: bool
    connection_revision_id: Identifier
    provider_host: str
    model: str
    runtime_version: str
    sdk_version: str
    duration_ms: int
    failure: NotRequired[ModelProbeFailure]


class McpToolBinding(TypedDict):
    tool_name: Identifier
    required_scope: Identifier
    tool_schema_hash: Sha256Digest
    resource_code: NotRequired[Identifier]
    resource_deployment_id: NotRequired[Identifier]
    resource_revision_id: NotRequired[Identifier]


class McpServerBinding(TypedDict):
    server_code: Identifier
    tools: list[McpToolBinding]


class JobFileManifestItem(TypedDict):
    file_id: Identifier
    version_id: Identifier
    display_name: str
    format_code: TextFormatCode | DocumentSourceFormatCode
    source_kind: Literal["CURRENT_MESSAGE", "EXPLICIT_REFERENCE", "WORKSPACE", "CONFLICT"]
    allowed_actions: list[FileAction]
    auto_materialize: bool
    conflict_candidate: bool
    source_received_at: str | None
    version_created_at: str
    materialization_size_bytes: int
    representation_id: NotRequired[Identifier]
    representation_kind: NotRequired[RepresentationKind]
    representation_size_bytes: NotRequired[int]
    representation_sha256: NotRequired[Sha256Digest]
    representation_format_code: NotRequired[RepresentationKind]
    representation_created_at: NotRequired[str]


class JobFileReadabilityNotice(TypedDict):
    file_name: str
    status: Literal["PARTIAL", "NO_TEXT", "UNAVAILABLE"]
    error_code: str


class JobFileManifest(TypedDict):
    schema_version: Literal[5]
    workspace_catalog_revision_id: Identifier
    manifest_hash: Sha256Digest
    observed_at: str
    items: list[JobFileManifestItem]
    readability_notices: NotRequired[list[JobFileReadabilityNotice]]


class FileContext(TypedDict):
    file_manifest: JobFileManifest | None


class AgentExecutionRequestV13(TypedDict):
    protocol_version: Literal["1.3"]
    runtime_kind: RuntimeKind
    invocation_id: Identifier
    request_digest: Sha256Digest
    job_id: Identifier
    app_user_id: Identifier
    project_code: Identifier
    agent_publication_id: Identifier
    application_publication_id: Identifier
    model_connection: ModelConnectionBinding
    prompt: Prompt
    limits: ExecutionLimits
    mcp_servers: list[McpServerBinding]
    file_context: FileContext


class RuntimeGrantClaims(TypedDict):
    iss: Literal["enterprise-agent-worker"]
    aud: Literal["agent-runtime"]
    azp: Literal["agent-worker"]
    runtime_kind: RuntimeKind
    sub: Identifier
    job_id: Identifier
    invocation_id: Identifier
    agent_publication_id: Identifier
    application_publication_id: Identifier
    request_digest: Sha256Digest
    iat: int
    nbf: int
    exp: int
    jti: Identifier


class Usage(TypedDict):
    input_tokens: int | None
    output_tokens: int | None
    cache_read_input_tokens: int | None
    cache_creation_input_tokens: int | None


class McpConnectionStatus(TypedDict):
    server_code: Identifier
    status: Literal["CONNECTED", "FAILED", "DISCONNECTED", "UNKNOWN"]


class RuntimeInitialization(TypedDict):
    model_id: str
    mcp_servers: list[McpConnectionStatus]


class ModelCall(TypedDict):
    model_call_id: Identifier
    provider_request_id: str | None
    provider_message_id: str | None
    model_id: str
    status: Literal["SUCCEEDED", "FAILED"]
    started_at: str | None
    completed_at: str
    duration_ms: int | None
    duration_source: Literal["SDK_OBSERVED", "UNAVAILABLE"]
    usage: Usage
    stop_reason: str | None
    error_code: str | None
    error_summary: str | None


class ApiRetry(TypedDict):
    attempt: int
    max_retries: int
    retry_delay_ms: int
    error_status: int | None
    error_code: str


class ModelUsageEntry(TypedDict):
    model_id: str
    canonical_model: str | None
    provider: str | None
    usage: Usage
    estimated_cost_usd: float | None


class ExecutionAccounting(TypedDict):
    status: Literal["COMPLETE", "PARTIAL", "UNAVAILABLE"]
    duration_ms: int | None
    duration_api_ms: int | None
    num_turns: int | None
    usage: Usage
    model_usage: list[ModelUsageEntry]
    estimated_cost_usd: float | None
    permission_denials_count: int


class RuntimeProvenance(TypedDict):
    runtime_kind: RuntimeKind
    runtime_version: str
    protocol_version: Literal["1.3"]
    sdk_version: str
    cli_version: str
    model_connection_revision_id: Identifier
    model_connection_config_hash: Sha256Digest


class RuntimeFailure(TypedDict):
    code: Identifier
    retry_class: Literal["NEVER", "TRANSIENT", "CONFIGURATION"]
    safe_message: SafeMessage


class ToolEvent(TypedDict):
    tool_call_id: Identifier
    tool_origin: Literal["mcp", "sdk_builtin", "sdk_custom", "unknown"]
    server_code: Identifier | None
    mcp_call_id: Identifier | None
    persisted_tool_call_id: Identifier | None
    tool_name: Identifier
    status: Literal["STARTED", "SUCCEEDED", "FAILED", "DENIED"]
    request_summary: JsonSummary
    response_summary: JsonSummary
    duration_ms: int
    failure: NotRequired[RuntimeFailure]


class TerminalResult(TypedDict):
    protocol_version: Literal["1.3"]
    invocation_id: Identifier
    request_digest: Sha256Digest
    last_sequence: int
    status: Literal["SUCCEEDED", "FAILED", "CANCELLED"]
    final_answer: NotRequired[str]
    failure: NotRequired[RuntimeFailure]
    usage: Usage
    accounting: ExecutionAccounting
    runtime_provenance: RuntimeProvenance


class CancelRequest(TypedDict):
    protocol_version: Literal["1.3"]
    invocation_id: Identifier
    request_digest: Sha256Digest
    reason: Literal["JOB_CANCELLED", "WORKER_TIMEOUT", "CLIENT_DISCONNECTED", "WORKER_SHUTDOWN"]


def validate_contract(definition_name: str, payload: object) -> None:
    schema = json.loads(CONTRACT_SCHEMA_PATH.read_text(encoding="utf-8"))
    definition = schema.get("$defs", {}).get(definition_name)
    if definition is None:
        raise ValueError(f"unknown runtime contract: {definition_name}")
    validator = Draft202012Validator(
        {"$ref": f"#/$defs/{definition_name}", "$defs": schema["$defs"]}
    )
    errors = sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
    if errors:
        detail = "; ".join(error.message for error in errors[:8])
        raise ValueError(f"invalid {definition_name}: {detail}")
