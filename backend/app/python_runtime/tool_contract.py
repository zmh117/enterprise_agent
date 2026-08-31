from __future__ import annotations

from typing import Any

from app.modules.agent.domain.runtime import AgentExecutionContext
from app.shared.build_identity import BuildIdentity
from app.shared.mcp_server_policy import FILE_MCP_SERVER_CODE
from app.shared.tool_contract import canonical_json_sha256, tool_schema_hash

from .file_mcp_bridge import LOCAL_FILE_OUTPUT_TOOL
from .job_sandbox import FILE_TOOL_NAMES
from .log_evidence_scanner import LOG_EVIDENCE_INPUT_SCHEMA, LOG_EVIDENCE_TOOL


PROMPT_TEMPLATE_VERSION = "agent-system-prompt-v4"
_SELECT_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["relative_path"],
    "properties": {"relative_path": {"type": "string", "minLength": 1, "maxLength": 240}},
}
_SDK_BUILTIN_SCHEMAS: dict[str, dict[str, Any]] = {
    name: {"type": "object", "runtime_policy": f"sandbox-v2/{name}"} for name in FILE_TOOL_NAMES
}


def build_tool_contract_observation(
    context: AgentExecutionContext,
    *,
    file_live: dict[str, Any] | None,
    runtime_build_identity: BuildIdentity,
) -> dict[str, Any]:
    frozen = [
        {
            "server_code": item.server_code,
            "tool_name": item.tool_name,
            "schema_hash": item.tool_schema_hash,
        }
        for item in sorted(
            context.mcp_bindings,
            key=lambda value: (value.server_code, value.tool_name),
        )
    ]
    live = dict(file_live or {"status": "NOT_OBSERVED", "tools": []})
    live_by_name = {
        str(item["tool_name"]): item for item in live.get("tools") or [] if isinstance(item, dict)
    }
    effective: list[dict[str, Any]] = []
    rows: list[dict[str, str]] = []
    frozen_names = {item.tool_name for item in context.mcp_bindings}
    for stale_name in sorted(set(context.allowed_tools) - frozen_names):
        rows.append(
            {
                "server_code": "runtime-config",
                "tool_name": stale_name,
                "status": "UNAUTHORIZED_EFFECTIVE",
            }
        )
    file_job = any(item.server_code == FILE_MCP_SERVER_CODE for item in context.mcp_bindings)
    for item in sorted(
        context.mcp_bindings,
        key=lambda value: (value.server_code, value.tool_name),
    ):
        status = "MATCH"
        if item.server_code == FILE_MCP_SERVER_CODE:
            observed = live_by_name.get(item.tool_name)
            if observed is None:
                status = (
                    "REMOTE_NOT_OBSERVED" if live.get("status") != "OBSERVED" else "MISSING_REMOTE"
                )
            elif str(observed.get("schema_hash") or "") != item.tool_schema_hash:
                status = "SCHEMA_MISMATCH"
        rows.append(
            {
                "server_code": item.server_code,
                "tool_name": item.tool_name,
                "status": status,
            }
        )
        if status != "MATCH":
            continue
        alias = item.server_code.replace("-", "_")
        effective.append(
            {
                "server_code": item.server_code,
                "tool_name": item.tool_name,
                "sdk_tool_name": f"mcp__{alias}__{item.tool_name}",
                "origin": "frozen_mcp",
                "schema_hash": item.tool_schema_hash,
                "authorization_status": "ALLOWED",
            }
        )
    for item in live.get("tools") or []:
        if isinstance(item, dict) and item.get("status") == "EXTRA_REMOTE_IGNORED":
            rows.append(
                {
                    "server_code": FILE_MCP_SERVER_CODE,
                    "tool_name": str(item["tool_name"]),
                    "status": "EXTRA_REMOTE_IGNORED",
                }
            )
    commit_effective = any(
        item["server_code"] == FILE_MCP_SERVER_CODE
        and item["tool_name"] == "file_create_commit_intent"
        and item["authorization_status"] == "ALLOWED"
        for item in effective
    )
    materialize_effective = any(
        item["server_code"] == FILE_MCP_SERVER_CODE
        and item["tool_name"] == "file_prepare_materialization"
        and item["authorization_status"] == "ALLOWED"
        for item in effective
    )
    if materialize_effective:
        effective.append(
            {
                "server_code": FILE_MCP_SERVER_CODE,
                "tool_name": LOG_EVIDENCE_TOOL,
                "sdk_tool_name": f"mcp__file_service__{LOG_EVIDENCE_TOOL}",
                "origin": "runtime_derived",
                "schema_hash": tool_schema_hash(LOG_EVIDENCE_INPUT_SCHEMA),
                "authorization_status": "ALLOWED",
                "dependency_tool_name": "file_prepare_materialization",
            }
        )
        rows.append(
            {
                "server_code": FILE_MCP_SERVER_CODE,
                "tool_name": LOG_EVIDENCE_TOOL,
                "status": "RUNTIME_DERIVED",
            }
        )
    if commit_effective:
        effective.append(
            {
                "server_code": FILE_MCP_SERVER_CODE,
                "tool_name": LOCAL_FILE_OUTPUT_TOOL,
                "sdk_tool_name": f"mcp__file_service__{LOCAL_FILE_OUTPUT_TOOL}",
                "origin": "runtime_derived",
                "schema_hash": tool_schema_hash(_SELECT_OUTPUT_SCHEMA),
                "authorization_status": "ALLOWED",
                "dependency_tool_name": "file_create_commit_intent",
            }
        )
        rows.append(
            {
                "server_code": FILE_MCP_SERVER_CODE,
                "tool_name": LOCAL_FILE_OUTPUT_TOOL,
                "status": "RUNTIME_DERIVED",
            }
        )
    if file_job:
        for name in FILE_TOOL_NAMES:
            effective.append(
                {
                    "server_code": FILE_MCP_SERVER_CODE,
                    "tool_name": name,
                    "sdk_tool_name": name,
                    "origin": "sdk_builtin",
                    "schema_hash": tool_schema_hash(_SDK_BUILTIN_SCHEMAS[name]),
                    "authorization_status": "ALLOWED",
                }
            )
    effective.sort(key=lambda item: str(item["sdk_tool_name"]))
    declared_tools = [
        str(item["sdk_tool_name"])
        for item in effective
        if item["authorization_status"] == "ALLOWED"
    ]
    prompt_payload = {
        "template_version": PROMPT_TEMPLATE_VERSION,
        "declared_tools": declared_tools,
    }
    prompt = {
        **prompt_payload,
        "contract_hash": canonical_json_sha256(prompt_payload),
    }
    identities = [
        dict(context.control_plane_build_identity),
        # Worker identity is transported in the request context by the Runtime adapter.
        dict(context.worker_build_identity),
        runtime_build_identity.to_dict(),
    ]
    file_identity = live.get("build_identity")
    if isinstance(file_identity, dict):
        identities.append(dict(file_identity))
    release_keys = {
        (str(item.get("source_revision") or ""), str(item.get("build_id") or ""))
        for item in identities
    }
    drift_statuses = {
        "MISSING_REMOTE",
        "SCHEMA_MISMATCH",
        "REMOTE_NOT_OBSERVED",
        "UNAUTHORIZED_EFFECTIVE",
        "PROMPT_OVERCLAIM",
    }
    status = "DRIFT" if any(row["status"] in drift_statuses for row in rows) else "MATCH"
    if file_job and live.get("status") != "OBSERVED":
        status = "DRIFT"
    if len(release_keys) != 1:
        status = "DRIFT"
    observation = {
        "snapshot_hash": context.job_tool_snapshot_hash,
        "status": status,
        "frozen_tools": frozen,
        "file_mcp_live": live,
        "effective_tools": effective,
        "prompt": prompt,
        "rows": sorted(rows, key=lambda item: (item["server_code"], item["tool_name"])),
        "component_build_identities": identities,
    }
    return {
        "observation_hash": canonical_json_sha256(observation),
        **observation,
    }
