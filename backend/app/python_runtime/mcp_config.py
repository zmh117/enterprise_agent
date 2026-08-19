from __future__ import annotations

import re
import threading
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit

from app.modules.agent.domain.runtime import AgentExecutionContext, AgentRunRequest
from app.shared.mcp_server_policy import (
    FILE_MCP_SERVER_CODE,
    MCP_SERVER_POLICIES,
    ONES_MCP_SERVER_CODE,
    TOOL_MCP_SERVER_CODE,
    McpServerAuthMode,
    McpServerPolicy,
    mcp_sdk_server_alias,
    require_mcp_server_policy,
    validate_mcp_server_policies,
)
from app.python_runtime.claude_client import (
    ClaudeSdkClient,
    build_system_prompt,
)
from app.python_runtime.error_mapper import append_cli_stderr
from app.python_runtime.file_mcp_bridge import (
    LOCAL_FILE_OUTPUT_TOOL,
    PythonRuntimeFileBridge,
    PythonRuntimeFileBridgeFactory,
    create_python_runtime_file_bridge,
)
from app.python_runtime.file_transfer import FileTransferBoundaryError, FileTransferContext
from app.python_runtime.job_sandbox import (
    ALLOWED_FILE_TOOLS,
    FILE_TOOL_NAMES,
    JobSandboxError,
    JobSandboxManager,
)
from app.python_runtime.tool_policy import contains_forbidden_tool_input
from app.shared.config import ExecutionSettings
from app.shared.exceptions import NonRetryableExecutionError


_OPAQUE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _is_aware_rfc3339(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


class FixedMcpClaudeSdkClient(ClaudeSdkClient):
    """Python SDK adapter with deployment-fixed MCP and a Runtime-local file bridge."""

    def __init__(
        self,
        *,
        limits: ExecutionSettings,
        api_key: str,
        mcp_server_url: str,
        business_mcp_server_urls: Mapping[str, str] | None = None,
        mcp_principal_tokens: Mapping[str, str] | None = None,
        file_mcp_server_url: str = "http://file-service:9105/mcp",
        file_principal_token: str = "",
        server_policies: Mapping[str, McpServerPolicy] | None = None,
        sandbox_manager: JobSandboxManager | None = None,
        cancellation_event: threading.Event | None = None,
        file_bridge_factory: PythonRuntimeFileBridgeFactory = (create_python_runtime_file_bridge),
    ) -> None:
        super().__init__(
            model="",
            limits=limits,
            api_key="",
            secret_resolver=lambda _ref: api_key,
            sandbox_manager=sandbox_manager,
            cancellation_event=cancellation_event,
        )
        self._mcp_server_url = mcp_server_url
        self._server_policies = MappingProxyType(
            dict(MCP_SERVER_POLICIES if server_policies is None else server_policies)
        )
        validate_mcp_server_policies(self._server_policies)
        raw_business_urls = (
            {ONES_MCP_SERVER_CODE: "http://ones-mcp:9104/mcp"}
            if business_mcp_server_urls is None
            else dict(business_mcp_server_urls)
        )
        for server_code in raw_business_urls:
            policy = require_mcp_server_policy(
                server_code,
                policies=self._server_policies,
            )
            if policy.auth_mode is not McpServerAuthMode.BUSINESS_PRINCIPAL_JWT:
                raise ValueError("Business MCP URL configured for a non-business Server")
        self._business_mcp_server_urls = MappingProxyType(
            {
                server_code: fixed_mcp_server_url(url, server_code=server_code)
                for server_code, url in raw_business_urls.items()
            }
        )
        raw_principal_tokens = dict(mcp_principal_tokens or {})
        for server_code in raw_principal_tokens:
            policy = require_mcp_server_policy(
                server_code,
                policies=self._server_policies,
            )
            if policy.auth_mode is not McpServerAuthMode.BUSINESS_PRINCIPAL_JWT:
                raise ValueError("Business Principal Token configured for a non-business Server")
        self._mcp_principal_tokens = MappingProxyType(raw_principal_tokens)
        self._file_mcp_server_url = file_mcp_server_url
        self._file_principal_token = file_principal_token
        self._file_bridge_factory = file_bridge_factory
        self._file_bridge: PythonRuntimeFileBridge | None = None

    @staticmethod
    def _shared_headers(request: AgentRunRequest) -> dict[str, str]:
        return {
            "X-Correlation-Id": f"job:{request.job_id}",
            "X-Job-Id": request.job_id,
            "X-App-User-Id": request.user_id,
            "X-Project-Code": request.project_code,
            "X-Invocation-Id": request.invocation_id,
            "X-Agent-Publication-Id": request.context.publication_id,
            "X-Application-Publication-Id": (request.context.application_publication_id),
        }

    def _build_mcp_server(self, request: AgentRunRequest) -> dict[str, dict[str, Any]]:
        shared_headers = self._shared_headers(request)
        servers: dict[str, dict[str, Any]] = {}
        server_codes = {binding.server_code for binding in request.context.mcp_bindings} or (
            {TOOL_MCP_SERVER_CODE} if request.context.allowed_tools else set()
        )
        for server_code in sorted(server_codes):
            try:
                policy = require_mcp_server_policy(
                    server_code,
                    policies=self._server_policies,
                )
            except ValueError as exc:
                raise NonRetryableExecutionError(
                    "Python Runtime MCP Server policy is unavailable",
                    safe_message="当前任务的 MCP Server 策略不可用",
                    error_code="runtime_mcp_server_policy_invalid",
                ) from exc
            alias = mcp_sdk_server_alias(server_code, policies=self._server_policies)
            if policy.auth_mode is McpServerAuthMode.JOB_CONTEXT:
                if server_code != TOOL_MCP_SERVER_CODE:
                    raise NonRetryableExecutionError(
                        "Python Runtime Job-context MCP Server is unsupported",
                        safe_message="当前任务的 MCP Server 策略不可用",
                        error_code="runtime_mcp_server_policy_invalid",
                    )
                servers[alias] = {
                    "type": "http",
                    "url": self._mcp_server_url,
                    "headers": dict(shared_headers),
                }
                continue
            if policy.auth_mode is McpServerAuthMode.BUSINESS_PRINCIPAL_JWT:
                token = self._mcp_principal_tokens.get(server_code, "")
                url = self._business_mcp_server_urls.get(server_code, "")
                if not token or not url:
                    raise NonRetryableExecutionError(
                        "Python Runtime Business MCP configuration is missing",
                        safe_message="当前调用缺少平台身份凭证或固定服务配置",
                        error_code="runtime_principal_token_missing",
                    )
                servers[alias] = {
                    "type": "http",
                    "url": url,
                    "headers": {
                        **shared_headers,
                        "Authorization": f"Bearer {token}",
                    },
                }
                continue
            if policy.auth_mode is McpServerAuthMode.FILE_PRINCIPAL_JWT:
                if server_code != FILE_MCP_SERVER_CODE:
                    raise NonRetryableExecutionError(
                        "Python Runtime File Principal MCP Server is unsupported",
                        safe_message="当前任务的 MCP Server 策略不可用",
                        error_code="runtime_mcp_server_policy_invalid",
                    )
                if not self._file_principal_token:
                    raise NonRetryableExecutionError(
                        "Python Runtime File MCP Principal Token is missing",
                        safe_message="当前调用缺少平台文件身份凭证",
                        error_code="runtime_file_principal_token_missing",
                    )
                continue
            raise NonRetryableExecutionError(
                "Python Runtime MCP Server authentication mode is unsupported",
                safe_message="当前任务的 MCP Server 策略不可用",
                error_code="runtime_mcp_server_policy_invalid",
            )
        return servers

    async def _open_mcp_server(self, request: AgentRunRequest, sdk: Any) -> dict[str, Any]:
        servers: dict[str, Any] = self._build_mcp_server(request)
        file_bindings = tuple(
            item.tool_name
            for item in request.context.mcp_bindings
            if item.server_code == FILE_MCP_SERVER_CODE
        )
        if not file_bindings:
            return servers
        sandbox = self._sandbox.get()
        if sandbox is None:
            raise NonRetryableExecutionError(
                "Python Runtime Job Sandbox is unavailable",
                safe_message="当前任务沙盒不可用",
                error_code="runtime_sandbox_unavailable",
            )
        bridge = self._file_bridge_factory(
            sdk=sdk,
            mcp_server_url=self._file_mcp_server_url,
            headers={
                **self._shared_headers(request),
                "Authorization": f"Bearer {self._file_principal_token}",
            },
            frozen_tool_names=file_bindings,
            context=FileTransferContext(
                job_id=request.job_id,
                workspace_path=sandbox.path,
                principal_token=self._file_principal_token,
                file_format_policy_version=request.context.file_format_policy_version,
            ),
            timeout_seconds=float(request.context.timeout_seconds),
        )
        await bridge.connect()
        self._file_bridge = bridge
        servers[mcp_sdk_server_alias(FILE_MCP_SERVER_CODE)] = bridge.server
        return servers

    async def _close_mcp_server(self) -> None:
        bridge = self._file_bridge
        self._file_bridge = None
        if bridge is not None:
            try:
                await bridge.close()
            except Exception:
                pass

    async def _prepare_context(
        self,
        context: AgentExecutionContext,
    ) -> AgentExecutionContext:
        bridge = self._file_bridge
        if bridge is None:
            return context
        manifest = context.retrieved_context.get("file_manifest")
        schema_version = manifest.get("schema_version") if isinstance(manifest, dict) else None
        if not isinstance(manifest, dict) or schema_version not in {1, 2, 3, 4}:
            raise NonRetryableExecutionError(
                "Runtime Job File Manifest is missing or invalid",
                safe_message="任务文件清单无效",
                error_code="file_manifest_runtime_invalid",
            )
        if schema_version in {2, 3, 4} and not _is_aware_rfc3339(manifest.get("observed_at")):
            raise NonRetryableExecutionError(
                "Runtime Job File Manifest observation time is invalid",
                safe_message="任务文件清单无效",
                error_code="file_manifest_runtime_invalid",
            )
        items = manifest.get("items")
        if not isinstance(items, list) or len(items) > 20:
            raise NonRetryableExecutionError(
                "Runtime Job File Manifest items are invalid",
                safe_message="任务文件清单无效",
                error_code="file_manifest_runtime_invalid",
            )
        materialized: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in items:
            if not isinstance(item, dict):
                raise NonRetryableExecutionError(
                    "Runtime Job File Manifest item is invalid",
                    safe_message="任务文件清单无效",
                    error_code="file_manifest_runtime_invalid",
                )
            source_received_at = item.get("source_received_at")
            version_created_at = item.get("version_created_at")
            representation_id = item.get("representation_id")
            if schema_version in {2, 3, 4} and (
                (source_received_at is not None and not _is_aware_rfc3339(source_received_at))
                or not _is_aware_rfc3339(version_created_at)
                or (
                    representation_id is not None
                    and not _is_aware_rfc3339(item.get("representation_created_at"))
                )
            ):
                raise NonRetryableExecutionError(
                    "Runtime Job File Manifest item time is invalid",
                    safe_message="任务文件清单无效",
                    error_code="file_manifest_runtime_invalid",
                )
            if not item.get("auto_materialize"):
                continue
            file_id = item.get("file_id")
            version_id = item.get("version_id")
            display_name = item.get("display_name")
            actions = item.get("allowed_actions")
            format_code = item.get("format_code", "TXT")
            has_representation = schema_version == 4 and representation_id is not None
            if (
                not isinstance(file_id, str)
                or _OPAQUE_IDENTIFIER.fullmatch(file_id) is None
                or not isinstance(version_id, str)
                or _OPAQUE_IDENTIFIER.fullmatch(version_id) is None
                or not isinstance(display_name, str)
                or not 1 <= len(display_name) <= 255
                or not isinstance(actions, list)
                or (
                    not has_representation
                    and (
                        "MATERIALIZE" not in actions
                        or format_code not in {"TXT", "LOG", "MARKDOWN"}
                    )
                )
                or (
                    has_representation
                    and (
                        not isinstance(representation_id, str)
                        or _OPAQUE_IDENTIFIER.fullmatch(representation_id) is None
                        or item.get("representation_kind") != "MARKDOWN"
                        or item.get("representation_format_code") != "MARKDOWN"
                        or not isinstance(item.get("representation_size_bytes"), int)
                        or int(item["representation_size_bytes"]) < 1
                        or not isinstance(item.get("representation_sha256"), str)
                        or len(str(item["representation_sha256"])) != 64
                    )
                )
            ):
                raise NonRetryableExecutionError(
                    "Runtime Job File Manifest item is invalid",
                    safe_message="任务文件清单无效",
                    error_code="file_manifest_runtime_invalid",
                )
            identity = (file_id, version_id)
            if identity in seen:
                continue
            seen.add(identity)
            try:
                result = await bridge.materialize(
                    file_id=file_id,
                    version_id=version_id,
                )
            except FileTransferBoundaryError as exc:
                raise NonRetryableExecutionError(
                    f"Runtime automatic materialization failed: {exc.code}",
                    safe_message="附件无法安全物化到任务沙盒",
                    error_code="file_auto_materialization_failed",
                ) from exc
            materialized.append(
                {
                    "file_id": file_id,
                    "version_id": version_id,
                    "display_name": (
                        f"{display_name.rsplit('.', 1)[0]}.md"
                        if has_representation
                        else display_name
                    ),
                    "format_code": "MARKDOWN" if has_representation else str(format_code),
                    "allowed_actions": (["MATERIALIZE"] if has_representation else list(actions)),
                    "relative_path": str(result["relative_path"]),
                    "sandbox_entry_handle": str(result["sandbox_entry_handle"]),
                    "size_bytes": int(result["size_bytes"]),
                    "sha256": str(result["sha256"]),
                    "source_received_at": source_received_at,
                    "version_created_at": str(version_created_at or ""),
                    **(
                        {
                            "source_display_name": display_name,
                            "source_format_code": str(format_code),
                            "representation_id": str(representation_id),
                            "representation_kind": "MARKDOWN",
                            "representation_created_at": str(item["representation_created_at"]),
                        }
                        if has_representation
                        else {}
                    ),
                }
            )
        return replace(
            context,
            retrieved_context={
                **context.retrieved_context,
                "runtime_materialized_files": materialized,
            },
        )

    def _build_options(
        self,
        sdk: Any,
        context: AgentExecutionContext,
        server: Any,
        cli_stderr: list[str],
        binding: Any,
    ) -> Any:
        exact_tools = []
        for item in context.mcp_bindings:
            alias = mcp_sdk_server_alias(
                item.server_code,
                policies=self._server_policies,
            )
            exact_tools.append(f"mcp__{alias}__{item.tool_name}")
        if not context.mcp_bindings:
            exact_tools = [f"mcp__tool_mcp__{name}" for name in context.allowed_tools]
        if self._file_bridge is not None and LOCAL_FILE_OUTPUT_TOOL in (
            self._file_bridge.local_tool_names
        ):
            exact_tools.append(f"mcp__file_service__{LOCAL_FILE_OUTPUT_TOOL}")
        exact_tool_set = frozenset(exact_tools)
        file_job = any(item.server_code == FILE_MCP_SERVER_CODE for item in context.mcp_bindings)
        sandbox = self._sandbox.get()
        if sandbox is None:
            raise NonRetryableExecutionError(
                "Python Runtime Job Sandbox is unavailable",
                safe_message="当前任务沙盒不可用",
                error_code="runtime_sandbox_unavailable",
            )
        attempted = 0

        def allow(updated_input: dict[str, Any]) -> Any:
            if sdk.permission_allow is not None:
                return sdk.permission_allow(updated_input=updated_input)
            return {"behavior": "allow", "updated_input": updated_input}

        def deny() -> Any:
            if sdk.permission_deny is not None:
                return sdk.permission_deny(
                    message="Tool is not authorized for this Job",
                    interrupt=False,
                )
            return {
                "behavior": "deny",
                "message": "Tool is not authorized for this Job",
                "interrupt": False,
            }

        async def can_use_tool(
            tool_name: str,
            tool_input: dict[str, Any],
            _permission_context: Any,
        ) -> Any:
            nonlocal attempted
            attempted += 1
            if attempted > context.max_tool_calls:
                return deny()
            if tool_name in exact_tool_set:
                return (
                    deny() if contains_forbidden_tool_input(tool_input) else allow(dict(tool_input))
                )
            if file_job and tool_name in ALLOWED_FILE_TOOLS:
                try:
                    return allow(sandbox.authorize_tool(tool_name, tool_input))
                except JobSandboxError:
                    return deny()
            return deny()

        return sdk.options(
            model=binding.model,
            system_prompt=build_system_prompt(context),
            mcp_servers=server,
            strict_mcp_config=True,
            tools=list(FILE_TOOL_NAMES) if file_job else [],
            allowed_tools=[],
            disallowed_tools=[
                tool
                for tool in (
                    "Bash",
                    "Write",
                    "Edit",
                    "WebFetch",
                    "WebSearch",
                    "NotebookEdit",
                    "Shell",
                )
                if not file_job or tool not in ALLOWED_FILE_TOOLS
            ],
            permission_mode="default",
            max_turns=context.max_turns,
            cwd=sandbox.path,
            setting_sources=[],
            skills=[],
            can_use_tool=can_use_tool,
            stderr=lambda line: append_cli_stderr(
                cli_stderr,
                line,
                self.limits.max_tool_response_chars,
            ),
        )


def fixed_mcp_server_url(raw: str, *, server_code: str = "tool-mcp") -> str:
    parsed = urlsplit(raw.strip())
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme not in {"http", "https"}
        or host not in {server_code, "localhost", "127.0.0.1", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != "/mcp"
    ):
        raise ValueError("MCP Tool Server URL is outside the fixed deployment boundary")
    return raw.strip().rstrip("/")
