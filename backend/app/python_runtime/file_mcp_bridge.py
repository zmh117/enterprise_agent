from __future__ import annotations

import asyncio
import json
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
    # MCP 2.x uses float seconds while the MCP 1.x bundled with the current
    # Claude Agent SDK still requires datetime.timedelta.
    if getattr(streamable_http_module, "httpx2", None) is not None:
        return seconds
    return timedelta(seconds=seconds)


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
                                "Select one existing writable work/ or outputs/ text file as "
                                "the exact file for a later commit intent. LOG is read-only. "
                                "Returns metadata and an opaque handle, never file content."
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
        return PreparedFileMaterialization(
            file_id=file_id,
            version_id=version_id,
            expected_size_bytes=int(control["expected_size_bytes"]),
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
            await session.initialize()
        except Exception:
            await stack.aclose()
            raise
        self._stack = stack
        self._session = session

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
