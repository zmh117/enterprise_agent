from __future__ import annotations

import asyncio
import re
import threading
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from types import MappingProxyType
from typing import Any, Callable
from urllib.parse import urlsplit

from app.modules.agent.domain.runtime import (
    AgentExecutionContext,
    AgentRunRequest,
    ToolCallBudget,
)
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.shared.mcp_server_policy import (
    FILE_MCP_SERVER_CODE,
    DINGTALK_MCP_SERVER_CODE,
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
    CLAUDE_SDK_MAX_BUFFER_SIZE_BYTES,
    ClaudeSdkClient,
    build_system_prompt,
)
from app.python_runtime.error_mapper import append_cli_stderr
from app.python_runtime.file_mcp_bridge import (
    PreparedFileMaterialization,
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
from app.shared.build_identity import BuildIdentity, build_identity_from_environment
from app.shared.exceptions import ExecutionPolicyExceeded, NonRetryableExecutionError
from app.python_runtime.tool_contract import build_tool_contract_observation


_OPAQUE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _is_aware_rfc3339(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _validated_runtime_manifest_items(
    items: list[object], *, schema_version: int
) -> list[dict[str, Any]]:
    """Validate the complete immutable input set before reserving Sandbox budget."""

    validated: list[dict[str, Any]] = []
    for value in items:
        if not isinstance(value, dict):
            raise NonRetryableExecutionError(
                "Runtime Job File Manifest item is invalid",
                safe_message="任务文件清单无效",
                error_code="file_manifest_runtime_invalid",
            )
        item = dict(value)
        source_received_at = item.get("source_received_at")
        version_created_at = item.get("version_created_at")
        representation_id = item.get("representation_id")
        if schema_version == 5 and (
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
            validated.append(item)
            continue
        file_id = item.get("file_id")
        version_id = item.get("version_id")
        display_name = item.get("display_name")
        actions = item.get("allowed_actions")
        format_code = item.get("format_code", "TXT")
        has_representation = representation_id is not None
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
                and ("MATERIALIZE" not in actions or format_code not in {"TXT", "LOG", "MARKDOWN"})
            )
            or (
                has_representation
                and (
                    not isinstance(representation_id, str)
                    or _OPAQUE_IDENTIFIER.fullmatch(representation_id) is None
                    or item.get("representation_kind") != "MARKDOWN"
                    or item.get("representation_format_code") != "MARKDOWN"
                    or not isinstance(item.get("representation_size_bytes"), int)
                    or isinstance(item.get("representation_size_bytes"), bool)
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
        validated.append(item)
    return validated


def _declared_mcp_input_fields(
    context: AgentExecutionContext,
    *,
    server_policies: Mapping[str, McpServerPolicy],
) -> dict[str, frozenset[str]]:
    declared: dict[str, frozenset[str]] = {}
    for binding in context.mcp_bindings:
        definition = MCP_TOOL_MANIFEST.get(binding.tool_name)
        if (
            definition is None
            or definition.server_code != binding.server_code
            or definition.schema_hash != binding.tool_schema_hash
        ):
            continue
        properties = definition.input_schema.get("properties")
        if not isinstance(properties, dict):
            continue
        sdk_name = (
            f"mcp__{mcp_sdk_server_alias(binding.server_code, policies=server_policies)}"
            f"__{binding.tool_name}"
        )
        fields = frozenset(str(value) for value in properties)
        declared[sdk_name] = (
            declared[sdk_name].intersection(fields) if sdk_name in declared else fields
        )
    return declared


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
        runtime_build_identity: BuildIdentity | None = None,
        tool_contract_observer: Callable[[dict[str, Any]], None] | None = None,
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
            {
                ONES_MCP_SERVER_CODE: "http://ones-mcp:9104/mcp",
                DINGTALK_MCP_SERVER_CODE: "http://dingtalk-mcp:9107/mcp",
            }
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
        self._runtime_build_identity = runtime_build_identity or build_identity_from_environment(
            "python-runtime"
        )
        self.last_tool_contract_observation: dict[str, Any] = {}
        self._tool_contract_observer = tool_contract_observer
        self._tool_contract_observed = False
        self._effective_context: AgentExecutionContext | None = None

    def observe_tool_contract(self, request: AgentRunRequest) -> dict[str, Any]:
        """Run the production MCP preflight without starting a model request."""

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._observe_tool_contract_async(request))
        result: dict[str, Any] | None = None
        error: BaseException | None = None

        def runner() -> None:
            nonlocal result, error
            try:
                result = asyncio.run(self._observe_tool_contract_async(request))
            except BaseException as exc:
                error = exc

        thread = threading.Thread(target=runner, name="file-mcp-contract-observer")
        thread.start()
        thread.join()
        if error is not None:
            raise error
        if result is None:
            raise NonRetryableExecutionError(
                "Runtime Tool contract observation did not return a result",
                safe_message="Runtime 工具契约观测无效",
                error_code="runtime_tool_contract_observation_invalid",
            )
        return result

    async def _observe_tool_contract_async(self, request: AgentRunRequest) -> dict[str, Any]:
        sandbox = self.sandbox_manager.create(request.job_id)
        token = self._sandbox.set(sandbox)
        try:
            await self._open_mcp_server(request, self._load_sdk())
            return dict(self.last_tool_contract_observation)
        finally:
            try:
                await self._close_mcp_server()
            finally:
                self._sandbox.reset(token)
                sandbox.cleanup()

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
            self._set_tool_contract_observation(request, None)
            self._require_matching_tool_contract()
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
            frozen_tool_schema_hashes={
                item.tool_name: item.tool_schema_hash
                for item in request.context.mcp_bindings
                if item.server_code == FILE_MCP_SERVER_CODE
            },
            context=FileTransferContext(
                job_id=request.job_id,
                workspace_path=sandbox.path,
                principal_token=self._file_principal_token,
                sandbox=sandbox,
            ),
            timeout_seconds=float(request.context.timeout_seconds),
            cancellation_event=self.cancellation_event,
        )
        self._file_bridge = bridge
        try:
            await bridge.connect()
        except FileTransferBoundaryError as exc:
            self._set_tool_contract_observation(request, bridge)
            raise NonRetryableExecutionError(
                f"File MCP tool-contract preflight failed: {exc.code}",
                safe_message="当前 Job 的文件工具契约与运行时不一致",
                error_code=exc.code,
            ) from exc
        self._set_tool_contract_observation(request, bridge)
        self._require_matching_tool_contract()
        servers[mcp_sdk_server_alias(FILE_MCP_SERVER_CODE)] = bridge.server
        return servers

    def _require_matching_tool_contract(self) -> None:
        if self.last_tool_contract_observation.get("status") != "MATCH":
            status_codes = {
                "MISSING_REMOTE": "runtime_tool_contract_missing_remote",
                "SCHEMA_MISMATCH": "runtime_tool_contract_schema_mismatch",
                "REMOTE_NOT_OBSERVED": "runtime_tool_contract_remote_not_observed",
                "UNAUTHORIZED_EFFECTIVE": "runtime_tool_contract_unauthorized_effective",
                "PROMPT_OVERCLAIM": "runtime_tool_contract_prompt_overclaim",
            }
            row_statuses = {
                str(row.get("status") or "")
                for row in self.last_tool_contract_observation.get("rows") or []
                if isinstance(row, dict)
            }
            error_code = next(
                (status_codes[status] for status in status_codes if status in row_statuses),
                "runtime_tool_contract_build_mismatch",
            )
            raise NonRetryableExecutionError(
                "Runtime component or Tool contract drift detected",
                safe_message="当前 Job 的工具或组件版本契约不一致",
                error_code=error_code,
            )

    def _set_tool_contract_observation(
        self,
        request: AgentRunRequest,
        bridge: PythonRuntimeFileBridge | None,
    ) -> None:
        observation = build_tool_contract_observation(
            request.context,
            file_live=(bridge.live_observation if bridge is not None else None),
            runtime_build_identity=self._runtime_build_identity,
        )
        self.last_tool_contract_observation = observation
        prompt = dict(observation["prompt"])
        self._effective_context = replace(
            request.context,
            prompt_template_version=str(prompt["template_version"]),
            effective_tool_names=tuple(str(value) for value in prompt["declared_tools"]),
            prompt_contract_hash=str(prompt["contract_hash"]),
        )
        if self._tool_contract_observed:
            raise NonRetryableExecutionError(
                "Runtime Tool contract observation was emitted more than once",
                safe_message="Runtime 工具契约观测无效",
                error_code="runtime_tool_contract_observation_invalid",
            )
        self._tool_contract_observed = True
        if self._tool_contract_observer is not None:
            self._tool_contract_observer(dict(observation))

    async def _close_mcp_server(self) -> None:
        bridge = self._file_bridge
        self._file_bridge = None
        self._effective_context = None
        if bridge is not None:
            try:
                await bridge.close()
            except Exception:
                pass

    async def _prepare_context(
        self,
        context: AgentExecutionContext,
    ) -> AgentExecutionContext:
        context = self._effective_context or context
        bridge = self._file_bridge
        if bridge is None:
            return context
        manifest = context.retrieved_context.get("file_manifest")
        schema_version = manifest.get("schema_version") if isinstance(manifest, dict) else None
        if (
            not isinstance(manifest, dict)
            or schema_version != 5
            or not isinstance(manifest.get("workspace_catalog_revision_id"), str)
            or not manifest.get("workspace_catalog_revision_id")
        ):
            raise NonRetryableExecutionError(
                "Runtime Job File Manifest is missing or invalid",
                safe_message="任务文件清单无效",
                error_code="file_manifest_runtime_invalid",
            )
        if not _is_aware_rfc3339(manifest.get("observed_at")):
            raise NonRetryableExecutionError(
                "Runtime Job File Manifest observation time is invalid",
                safe_message="任务文件清单无效",
                error_code="file_manifest_runtime_invalid",
            )
        items = manifest.get("items")
        if not isinstance(items, list) or len(items) > 40:
            raise NonRetryableExecutionError(
                "Runtime Job File Manifest items are invalid",
                safe_message="任务文件清单无效",
                error_code="file_manifest_runtime_invalid",
            )
        items = _validated_runtime_manifest_items(items, schema_version=schema_version)
        materialized: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        automatic_identities: list[tuple[str, str]] = []
        prepared_materializations: dict[tuple[str, str], PreparedFileMaterialization] = {}
        sandbox = self._sandbox.get()
        automatic_items = [item for item in items if item.get("auto_materialize")]
        if automatic_items:
            if sandbox is None:
                raise NonRetryableExecutionError(
                    "Runtime Job Sandbox is unavailable",
                    safe_message="当前任务沙盒不可用",
                    error_code="runtime_sandbox_unavailable",
                )
            reservations: list[tuple[tuple[str, str], int]] = []
            try:
                for candidate in automatic_items:
                    identity = (str(candidate["file_id"]), str(candidate["version_id"]))
                    if identity in prepared_materializations:
                        continue
                    prepared = await bridge.prepare_materialization(
                        file_id=identity[0],
                        version_id=identity[1],
                    )
                    prepared_materializations[identity] = prepared
                    automatic_identities.append(identity)
                    reservations.append((identity, prepared.expected_size_bytes))
                sandbox.reserve_input_batch(reservations)
            except FileTransferBoundaryError as exc:
                sandbox.rollback_inputs(automatic_identities)
                raise NonRetryableExecutionError(
                    f"Runtime automatic input preparation failed: {exc.code}",
                    safe_message="附件无法安全准备到任务沙盒",
                    error_code="file_auto_materialization_failed",
                ) from exc
            except JobSandboxError as exc:
                raise NonRetryableExecutionError(
                    f"Runtime automatic input preflight failed: {exc.code}",
                    safe_message="任务输入超过沙盒预算，请缩小工作集",
                    error_code="file_auto_materialization_preflight_failed",
                ) from exc
        for item in items:
            source_received_at = item.get("source_received_at")
            version_created_at = item.get("version_created_at")
            representation_id = item.get("representation_id")
            if not item.get("auto_materialize"):
                continue
            file_id = str(item["file_id"])
            version_id = str(item["version_id"])
            display_name = str(item["display_name"])
            actions = list(item["allowed_actions"])
            format_code = item.get("format_code", "TXT")
            has_representation = representation_id is not None
            identity = (file_id, version_id)
            if identity in seen:
                continue
            seen.add(identity)
            try:
                result = await bridge.materialize_prepared(
                    prepared_materializations[identity],
                )
            except FileTransferBoundaryError as exc:
                if sandbox is not None:
                    sandbox.rollback_inputs(automatic_identities)
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
        *,
        tool_call_budget: ToolCallBudget | None = None,
    ) -> Any:
        exact_tool_set = frozenset(
            name for name in context.effective_tool_names if name not in FILE_TOOL_NAMES
        )
        declared_input_fields = _declared_mcp_input_fields(
            context,
            server_policies=self._server_policies,
        )
        file_job = any(name in FILE_TOOL_NAMES for name in context.effective_tool_names)
        sandbox = self._sandbox.get()
        if sandbox is None:
            raise NonRetryableExecutionError(
                "Python Runtime Job Sandbox is unavailable",
                safe_message="当前任务沙盒不可用",
                error_code="runtime_sandbox_unavailable",
            )
        budget = tool_call_budget or ToolCallBudget(maximum=context.max_tool_calls)

        def allow(updated_input: dict[str, Any]) -> Any:
            if sdk.permission_allow is not None:
                return sdk.permission_allow(updated_input=updated_input)
            return {"behavior": "allow", "updated_input": updated_input}

        def deny(
            *,
            message: str = "Tool is not authorized for this Job",
            interrupt: bool = False,
        ) -> Any:
            if sdk.permission_deny is not None:
                return sdk.permission_deny(
                    message=message,
                    interrupt=interrupt,
                )
            return {
                "behavior": "deny",
                "message": message,
                "interrupt": interrupt,
            }

        async def can_use_tool(
            tool_name: str,
            tool_input: dict[str, Any],
            _permission_context: Any,
        ) -> Any:
            try:
                budget.consume()
            except ExecutionPolicyExceeded as exc:
                return deny(message=exc.safe_message, interrupt=True)
            if tool_name in exact_tool_set:
                return (
                    deny()
                    if contains_forbidden_tool_input(
                        tool_input,
                        declared_root_fields=declared_input_fields.get(
                            tool_name, frozenset()
                        ),
                    )
                    else allow(dict(tool_input))
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
            tools=[name for name in FILE_TOOL_NAMES if name in context.effective_tool_names],
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
            max_buffer_size=CLAUDE_SDK_MAX_BUFFER_SIZE_BYTES,
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
