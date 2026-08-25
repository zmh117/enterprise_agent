from __future__ import annotations

import asyncio
import json
import logging
import re
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Callable, Protocol

import httpx
from mcp import ClientSession, types
from mcp.client import streamable_http as streamable_http_module
from mcp.server import Server

from app.modules.file_workspace.contracts import FILE_TOOL_MANIFEST
from app.shared.build_identity import BuildIdentity, BuildIdentityError
from app.shared.tool_contract import (
    MAX_TOOL_CONTRACT_ITEMS,
    ToolContractValueError,
    canonical_json_sha256,
    tool_schema_hash,
)
from app.python_runtime.file_transfer import (
    FileTransferBoundaryError,
    FileTransferContext,
    FileTransferCoordinator,
    parse_file_transfer_control,
)
from app.python_runtime.file_transfer_http import HttpFileTransferPort


LOCAL_FILE_OUTPUT_TOOL = "select_sandbox_output"
_MATERIALIZE_TOOL = "file_prepare_materialization"
_COMMIT_TOOL = "file_create_commit_intent"
_MCP_CALL_ID_META_KEY = "enterprise-agent/mcp-call-id"
_AGENT_TOOL_CALL_ID_META_KEY = "enterprise-agent/agent-tool-call-id"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_BUILD_IDENTITY_CAPABILITY = "enterprise-agent/build-identity-v1"
_MISSING_MCP_FIELD = object()
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedFileMaterialization:
    file_id: str
    version_id: str
    expected_size_bytes: int
    control_result: dict[str, Any] = field(repr=False)


class PythonRuntimeFileBridge(Protocol):
    @property
    def server(self) -> Any: ...

    @property
    def local_tool_names(self) -> tuple[str, ...]: ...

    @property
    def live_observation(self) -> dict[str, Any]: ...

    async def connect(self) -> None: ...

    async def materialize(
        self,
        *,
        file_id: str,
        version_id: str,
    ) -> dict[str, Any]: ...

    async def prepare_materialization(
        self,
        *,
        file_id: str,
        version_id: str,
    ) -> PreparedFileMaterialization: ...

    async def materialize_prepared(
        self,
        prepared: PreparedFileMaterialization,
    ) -> dict[str, Any]: ...

    async def close(self) -> None: ...


PythonRuntimeFileBridgeFactory = Callable[..., PythonRuntimeFileBridge]


def _safe_meta(result: types.CallToolResult) -> dict[str, Any] | None:
    source = result.meta if isinstance(result.meta, dict) else {}
    retained = {
        key: value
        for key in (_MCP_CALL_ID_META_KEY, _AGENT_TOOL_CALL_ID_META_KEY)
        if isinstance((value := source.get(key)), str) and _IDENTIFIER.fullmatch(value)
    }
    return retained or None


def _call_tool_result(
    *,
    content: list[Any],
    is_error: bool = False,
    structured_content: Any | None = None,
    meta: dict[str, Any] | None = None,
) -> types.CallToolResult:
    payload: dict[str, Any] = {"content": content, "isError": is_error}
    if structured_content is not None:
        payload["structuredContent"] = structured_content
    if meta is not None:
        payload["_meta"] = meta
    return types.CallToolResult.model_validate(payload)


def _result_is_error(result: types.CallToolResult) -> bool:
    return bool(getattr(result, "is_error", getattr(result, "isError", False)))


def _result_structured_content(result: types.CallToolResult) -> Any | None:
    return getattr(
        result,
        "structured_content",
        getattr(result, "structuredContent", None),
    )


def _session_timeout(seconds: float) -> Any:
    # MCP 2.x uses float seconds while legacy MCP 1.x requires
    # datetime.timedelta; tolerate mixed-version rollout windows.
    if getattr(streamable_http_module, "httpx2", None) is not None:
        return seconds
    return timedelta(seconds=seconds)


def _mcp_tool_input_schema(tool: Any) -> Any:
    # MCP 1.x Pydantic models expose JSON aliases, while MCP 2.x exposes
    # snake_case attributes. Keep the Runtime tolerant of mixed-version rollout
    # windows even though its image is pinned to the governed MCP 2.x line.
    value = getattr(tool, "input_schema", _MISSING_MCP_FIELD)
    if value is _MISSING_MCP_FIELD:
        value = getattr(tool, "inputSchema", _MISSING_MCP_FIELD)
    if value is _MISSING_MCP_FIELD:
        raise ToolContractValueError("MCP Tool input schema field is missing")
    return value


def _mcp_list_tools_next_cursor(page: Any) -> str:
    value = getattr(page, "next_cursor", _MISSING_MCP_FIELD)
    if value is _MISSING_MCP_FIELD:
        value = getattr(page, "nextCursor", _MISSING_MCP_FIELD)
    if value is _MISSING_MCP_FIELD or (value is not None and not isinstance(value, str)):
        raise FileTransferBoundaryError(
            "runtime_tool_contract_observation_invalid",
            "File MCP tools/list pagination is invalid",
        )
    return value or ""


def _safe_error(code: str) -> types.CallToolResult:
    return _call_tool_result(
        content=[
            types.TextContent(
                type="text",
                text=json.dumps(
                    {"error": "文件桥处理失败", "error_code": code},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
        ],
        is_error=True,
    )


class ClaudePythonFileBridge:
    def __init__(
        self,
        *,
        sdk: Any,
        mcp_server_url: str,
        headers: dict[str, str],
        frozen_tool_names: tuple[str, ...],
        frozen_tool_schema_hashes: dict[str, str] | None = None,
        context: FileTransferContext,
        timeout_seconds: float,
        async_client_factory: Callable[..., Any] | None = None,
        transfer_port: Any | None = None,
        remote_session: Any | None = None,
    ) -> None:
        frozen = tuple(dict.fromkeys(frozen_tool_names))
        unknown = [name for name in frozen if name not in FILE_TOOL_MANIFEST]
        if unknown:
            raise FileTransferBoundaryError(
                "file_tool_not_supported",
                "Runtime File MCP bridge received an unsupported frozen tool",
            )
        self._mcp_server_url = mcp_server_url
        self._headers = dict(headers)
        self._frozen = frozen
        self._frozen_hashes = {
            name: str(
                (frozen_tool_schema_hashes or {}).get(name) or FILE_TOOL_MANIFEST[name].schema_hash
            )
            for name in frozen
        }
        self._context = context
        self._timeout_seconds = timeout_seconds
        self._async_client_factory = async_client_factory
        self._stack: AsyncExitStack | None = None
        self._session: Any | None = remote_session
        self._injected_session = remote_session is not None
        self._coordinator = FileTransferCoordinator(
            transfer_port
            or HttpFileTransferPort(
                mcp_server_url,
                timeout_seconds=timeout_seconds,
            )
        )
        self.local_tool_names = (LOCAL_FILE_OUTPUT_TOOL,) if _COMMIT_TOOL in frozen else ()
        self.live_observation: dict[str, Any] = {
            "status": "NOT_OBSERVED",
            "tools": [],
        }
        self.server = self._build_server(sdk)

    def _build_server(self, sdk: Any) -> Any:
        def visible_tools() -> list[types.Tool]:
            result = [
                types.Tool.model_validate(
                    {
                        "name": name,
                        "description": FILE_TOOL_MANIFEST[name].description,
                        "inputSchema": dict(FILE_TOOL_MANIFEST[name].input_schema),
                    }
                )
                for name in self._frozen
            ]
            if LOCAL_FILE_OUTPUT_TOOL in self.local_tool_names:
                result.append(
                    types.Tool.model_validate(
                        {
                            "name": LOCAL_FILE_OUTPUT_TOOL,
                            "description": (
                                "文件持久化步骤1/2：选择当前Linux容器Job Sandbox中已存在且可写的"
                                "work/或outputs/下TXT或Markdown。relative_path必须是使用/的POSIX"
                                "相对路径（如work/result.md）；即使宿主机是Windows，也不得使用盘符、"
                                "绝对路径或反斜杠。返回SELECTED只表示取得后续提交所需的不透明"
                                "sandbox_entry_handle，不等于已保存、已提交或已交付；成功后必须继续调用"
                                "file_create_commit_intent。LOG只读；不返回正文。"
                            ),
                            "inputSchema": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["relative_path"],
                                "properties": {
                                    "relative_path": {
                                        "type": "string",
                                        "minLength": 1,
                                        "maxLength": 240,
                                    }
                                },
                            },
                        }
                    )
                )
            return result

        async def execute_tool(
            name: str,
            arguments: dict[str, Any],
        ) -> types.CallToolResult:
            try:
                if name == LOCAL_FILE_OUTPUT_TOOL:
                    if name not in self.local_tool_names or set(arguments) != {"relative_path"}:
                        return _safe_error("file_transfer_control_invalid")
                    relative_path = arguments.get("relative_path")
                    if not isinstance(relative_path, str):
                        return _safe_error("file_transfer_path_invalid")
                    selected = await asyncio.to_thread(
                        self._coordinator.select_sandbox_output,
                        relative_path=relative_path,
                        context=self._context,
                    )
                    return _call_tool_result(
                        content=[
                            types.TextContent(
                                type="text",
                                text=json.dumps(
                                    {"runtime_file_bridge": selected},
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                ),
                            )
                        ]
                    )
                if name not in self._frozen:
                    return _safe_error("file_tool_not_frozen")
                remote, bridge_result = await self._forward_remote(name, arguments)
                if _result_is_error(remote) or bridge_result is None:
                    return _call_tool_result(
                        content=list(remote.content),
                        structured_content=_result_structured_content(remote),
                        is_error=_result_is_error(remote),
                        meta=_safe_meta(remote),
                    )
                return _call_tool_result(
                    content=[
                        *remote.content,
                        types.TextContent(
                            type="text",
                            text=json.dumps(
                                {"runtime_file_bridge": bridge_result},
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                        ),
                    ],
                    structured_content=_result_structured_content(remote),
                    is_error=False,
                    meta=_safe_meta(remote),
                )
            except FileTransferBoundaryError as exc:
                return _safe_error(exc.code)

        config = sdk.create_sdk_mcp_server(
            name="enterprise-file-bridge",
            version="0.1.0",
            tools=[],
        )
        sdk_server = config["instance"] if isinstance(config, dict) else config.instance
        if hasattr(sdk_server, "list_tools") and hasattr(sdk_server, "call_tool"):

            @sdk_server.list_tools()  # type: ignore[untyped-decorator]
            async def list_tools_v1() -> list[types.Tool]:
                return visible_tools()

            @sdk_server.call_tool()  # type: ignore[untyped-decorator]
            async def call_tool_v1(
                name: str,
                arguments: dict[str, Any],
            ) -> types.CallToolResult:
                return await execute_tool(name, arguments)

            return config

        async def list_tools_v2(_context: Any, _params: Any) -> types.ListToolsResult:
            return types.ListToolsResult(tools=visible_tools())

        async def call_tool_v2(
            _context: Any,
            params: types.CallToolRequestParams,
        ) -> types.CallToolResult:
            return await execute_tool(params.name, params.arguments or {})

        server = Server(
            "enterprise-file-bridge",
            version="0.1.0",
            instructions="Runtime-local governed File Service bridge.",
            on_list_tools=list_tools_v2,
            on_call_tool=call_tool_v2,
        )
        return {
            "type": "sdk",
            "name": "enterprise-file-bridge",
            "instance": server,
        }

    async def _forward_remote(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> tuple[types.CallToolResult, dict[str, Any] | None]:
        remote = await self._call_remote(name, arguments)
        if _result_is_error(remote) or name not in {_MATERIALIZE_TOOL, _COMMIT_TOOL}:
            return remote, None
        envelope = remote.model_dump(by_alias=True, exclude_none=True)
        bridge_result = await asyncio.to_thread(
            self._coordinator.process_mcp_control_result,
            envelope,
            self._context,
            materialization_identity=(
                (str(arguments["file_id"]), str(arguments["version_id"]))
                if name == _MATERIALIZE_TOOL
                else None
            ),
        )
        return remote, dict(bridge_result)

    async def _call_remote(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> types.CallToolResult:
        if name not in self._frozen:
            raise FileTransferBoundaryError(
                "file_tool_not_frozen",
                "File Tool is not frozen for this Job",
            )
        session = self._session
        if session is None:
            raise FileTransferBoundaryError(
                "file_service_unavailable",
                "File Service is unavailable",
            )
        remote = await session.call_tool(
            name,
            arguments,
            read_timeout_seconds=_session_timeout(self._timeout_seconds),
        )
        if not isinstance(remote, types.CallToolResult):
            raise FileTransferBoundaryError(
                "file_service_unavailable",
                "File Service returned an unsupported result",
            )
        return remote

    async def prepare_materialization(
        self,
        *,
        file_id: str,
        version_id: str,
    ) -> PreparedFileMaterialization:
        remote = await self._call_remote(
            _MATERIALIZE_TOOL,
            {"file_id": file_id, "version_id": version_id},
        )
        if _result_is_error(remote):
            raise FileTransferBoundaryError(
                "file_auto_materialization_denied",
                "File Service rejected automatic materialization",
            )
        envelope = remote.model_dump(by_alias=True, exclude_none=True)
        control = parse_file_transfer_control(envelope)
        if control.get("action") != "MATERIALIZE":
            raise FileTransferBoundaryError(
                "file_transfer_action_unsupported",
                "automatic materialization requires a materialize transfer",
            )
        expected_size_bytes = control.get("expected_size_bytes")
        if not isinstance(expected_size_bytes, int) or isinstance(expected_size_bytes, bool):
            raise FileTransferBoundaryError(
                "file_transfer_control_invalid",
                "automatic materialization expected size is invalid",
            )
        return PreparedFileMaterialization(
            file_id=file_id,
            version_id=version_id,
            expected_size_bytes=expected_size_bytes,
            control_result=envelope,
        )

    async def materialize_prepared(
        self,
        prepared: PreparedFileMaterialization,
    ) -> dict[str, Any]:
        bridge_result = await asyncio.to_thread(
            self._coordinator.process_mcp_control_result,
            prepared.control_result,
            self._context,
            materialization_identity=(prepared.file_id, prepared.version_id),
        )
        return dict(bridge_result)

    async def materialize(
        self,
        *,
        file_id: str,
        version_id: str,
    ) -> dict[str, Any]:
        prepared = await self.prepare_materialization(
            file_id=file_id,
            version_id=version_id,
        )
        return await self.materialize_prepared(prepared)

    async def connect(self) -> None:
        if self._injected_session:
            assert self._session is not None
            await self._observe_live_contract(self._session, initialize=True)
            return
        if self._stack is not None:
            raise RuntimeError("File MCP bridge is already connected")
        stack = AsyncExitStack()
        try:
            client_module = (
                getattr(streamable_http_module, "httpx2", None)
                or getattr(streamable_http_module, "httpx", None)
                or httpx
            )
            client_factory = self._async_client_factory or client_module.AsyncClient
            client = await stack.enter_async_context(
                client_factory(
                    headers=self._headers,
                    timeout=self._timeout_seconds,
                    follow_redirects=False,
                )
            )
            streams = await stack.enter_async_context(
                streamable_http_module.streamable_http_client(
                    self._mcp_server_url,
                    http_client=client,
                    terminate_on_close=False,
                )
            )
            read_stream, write_stream = streams[0], streams[1]
            session = await stack.enter_async_context(
                ClientSession(
                    read_stream,
                    write_stream,
                    read_timeout_seconds=_session_timeout(self._timeout_seconds),
                )
            )
            initialization = await session.initialize()
            await self._observe_live_contract(
                session,
                initialize=False,
                initialization=initialization,
            )
        except Exception:
            await stack.aclose()
            raise
        self._stack = stack
        self._session = session

    async def _observe_live_contract(
        self,
        session: Any,
        *,
        initialize: bool,
        initialization: Any | None = None,
    ) -> None:
        observation_stage = "initialize"
        try:
            if initialize:
                initialization = await session.initialize()
            observation_stage = "build_identity"
            build_identity = self._file_build_identity(initialization)
            cursor: str | None = None
            seen_cursors: set[str] = set()
            live: dict[str, str] = {}
            while True:
                params = types.PaginatedRequestParams(cursor=cursor) if cursor else None
                observation_stage = "list_tools"
                page = await session.list_tools(params=params)
                for tool in page.tools:
                    observation_stage = "tool_name"
                    name = str(tool.name or "")
                    if _IDENTIFIER.fullmatch(name) is None or name in live:
                        raise FileTransferBoundaryError(
                            "runtime_tool_contract_observation_invalid",
                            "File MCP tools/list contains an invalid or duplicate name",
                        )
                    try:
                        observation_stage = "tool_schema"
                        live[name] = tool_schema_hash(_mcp_tool_input_schema(tool))
                    except ToolContractValueError as exc:
                        raise FileTransferBoundaryError(
                            "runtime_tool_contract_observation_invalid",
                            "File MCP tools/list contains an invalid schema",
                        ) from exc
                    if len(live) > MAX_TOOL_CONTRACT_ITEMS:
                        raise FileTransferBoundaryError(
                            "runtime_tool_contract_observation_invalid",
                            "File MCP tools/list exceeds its item boundary",
                        )
                observation_stage = "pagination"
                next_cursor = _mcp_list_tools_next_cursor(page)
                if not next_cursor:
                    break
                if next_cursor in seen_cursors or len(next_cursor) > 256:
                    raise FileTransferBoundaryError(
                        "runtime_tool_contract_observation_invalid",
                        "File MCP tools/list pagination is invalid",
                    )
                seen_cursors.add(next_cursor)
                cursor = next_cursor
            rows: list[dict[str, str]] = []
            for name in sorted(live):
                expected = self._frozen_hashes.get(name)
                status = (
                    "EXTRA_REMOTE_IGNORED"
                    if expected is None
                    else "MATCH"
                    if expected == live[name]
                    else "SCHEMA_MISMATCH"
                )
                rows.append(
                    {
                        "server_code": "file-service",
                        "tool_name": name,
                        "schema_hash": live[name],
                        "status": status,
                    }
                )
            self.live_observation = {
                "status": "OBSERVED",
                "tools": rows,
                "toolset_hash": canonical_json_sha256(
                    [{"tool_name": name, "schema_hash": live[name]} for name in sorted(live)]
                ),
                "build_identity": build_identity.to_dict(),
            }
            missing = sorted(set(self._frozen) - set(live))
            mismatched = sorted(
                name
                for name in set(self._frozen) & set(live)
                if self._frozen_hashes[name] != live[name]
            )
            if missing:
                raise FileTransferBoundaryError(
                    "runtime_tool_contract_missing_remote",
                    "File MCP is missing a frozen Job tool",
                )
            if mismatched:
                raise FileTransferBoundaryError(
                    "runtime_tool_contract_schema_mismatch",
                    "File MCP schema differs from the frozen Job tool",
                )
        except FileTransferBoundaryError as exc:
            logger.warning(
                "File MCP live contract observation rejected stage=%s error_code=%s",
                observation_stage,
                exc.code,
            )
            raise
        except Exception as exc:
            logger.warning(
                "File MCP live contract observation failed stage=%s error_type=%s",
                observation_stage,
                type(exc).__name__,
            )
            raise FileTransferBoundaryError(
                "runtime_tool_contract_remote_not_observed",
                "File MCP live contract could not be observed",
            ) from exc

    @staticmethod
    def _file_build_identity(initialization: Any | None) -> BuildIdentity:
        try:
            capabilities = getattr(initialization, "capabilities", None)
            experimental = getattr(capabilities, "experimental", None)
            value = (
                experimental.get(_BUILD_IDENTITY_CAPABILITY)
                if isinstance(experimental, dict)
                else None
            )
            if not isinstance(value, dict):
                raise BuildIdentityError("File MCP build identity is missing")
            return BuildIdentity.from_dict(value, expected_component="file-service")
        except (BuildIdentityError, ValueError) as exc:
            raise FileTransferBoundaryError(
                "runtime_tool_contract_observation_invalid",
                "File MCP build identity is invalid",
            ) from exc

    async def close(self) -> None:
        if self._injected_session:
            return
        stack = self._stack
        self._stack = None
        self._session = None
        if stack is not None:
            await stack.aclose()


def create_python_runtime_file_bridge(**kwargs: Any) -> PythonRuntimeFileBridge:
    return ClaudePythonFileBridge(**kwargs)
