from __future__ import annotations

import asyncio
import importlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from functools import lru_cache
from urllib.parse import urlsplit

from app.modules.agent.domain.runtime import (
    AgentExecutionContext,
    AgentRunRequest,
    AgentRunResult,
)
from app.modules.model_connection.domain import (
    ANTHROPIC_COMPATIBLE_PROTOCOL,
    ModelRuntimeBinding,
)
from app.shared.config import ExecutionSettings
from app.shared.database import assert_external_io_allowed
from app.shared.exceptions import (
    DiagnosticLoopExhausted,
    NonRetryableExecutionError,
    RetryableExecutionError,
    ToolPolicyError,
)
from app.python_runtime.job_sandbox import JobSandbox, JobSandboxManager

if TYPE_CHECKING:
    from app.modules.agent.infrastructure.mcp_tool_registry import ToolRegistry
    from app.modules.job.infrastructure.repositories import AgentRepository


@dataclass(frozen=True)
class ClaudeSdk:
    query: Callable[..., AsyncIterator[Any]]
    options: Any
    tool: Callable[..., Any]
    create_sdk_mcp_server: Callable[..., Any]
    tool_annotations: Any | None
    permission_allow: Any | None = None
    permission_deny: Any | None = None


async def _streaming_user_prompt(content: str) -> AsyncIterator[dict[str, Any]]:
    """Emit one SDK streaming input message so can_use_tool remains available."""
    yield {
        "type": "user",
        "session_id": "",
        "message": {"role": "user", "content": content},
        "parent_tool_use_id": None,
    }


class _SdkAuditNormalizer:
    """Projects only bounded SDK metadata; never message content or raw payloads."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.accounting: dict[str, Any] = _unavailable_accounting()
        self._request_started_at: float | None = None
        self._request_started_wall: str | None = None
        self._observed_model_call_ids: set[str] = set()
        self._next_model_call_ordinal = 1

    def consume(self, message: Any) -> None:
        message_type = _sdk_message_type(message)
        subtype = str(_value(message, "subtype") or "")
        data = _value(message, "data")
        source = data if isinstance(data, dict) else message
        if message_type == "system" and subtype == "status":
            if _value(source, "status") == "requesting" and self._request_started_at is None:
                self._request_started_at = time.monotonic()
                self._request_started_wall = _utc_now()
            return
        if message_type == "system" and subtype == "init":
            servers = []
            raw_servers = _value(source, "mcp_servers") or []
            if isinstance(raw_servers, list):
                for item in raw_servers[:32]:
                    name = _value(item, "name")
                    server_code = _safe_server_code(name)
                    if server_code:
                        servers.append(
                            {
                                "server_code": server_code,
                                "status": _safe_mcp_status(_value(item, "status")),
                            }
                        )
            self.events.append(
                {
                    "event_type": "runtime_initialized",
                    "payload": {
                        "model_id": _bounded_identifier_text(
                            _value(source, "model") or "unknown-model", 200
                        ),
                        "mcp_servers": servers,
                    },
                }
            )
            return
        if message_type == "system" and subtype == "api_retry":
            self.events.append(
                {
                    "event_type": "api_retry",
                    "payload": {
                        "attempt": _bounded_int(_value(source, "attempt"), 1, 32, 1),
                        "max_retries": _bounded_int(_value(source, "max_retries"), 1, 32, 1),
                        "retry_delay_ms": _bounded_int(
                            _value(source, "retry_delay_ms"), 0, 1_800_000, 0
                        ),
                        "error_status": _http_status_or_none(_value(source, "error_status")),
                        "error_code": _bounded_identifier_text(
                            _value(source, "error") or "unknown", 128
                        ),
                    },
                }
            )
            return
        if message_type == "assistant":
            body = _value(message, "message") or message
            completed_monotonic = time.monotonic()
            completed_wall = _utc_now()
            started = self._request_started_at
            stable_message_id = _identifier_or_none(
                _value(body, "id") or _value(body, "message_id") or _value(message, "uuid")
            )
            if stable_message_id is not None:
                if stable_message_id in self._observed_model_call_ids:
                    self._request_started_at = None
                    self._request_started_wall = None
                    return
                self._observed_model_call_ids.add(stable_message_id)
                message_id = stable_message_id
            else:
                message_id = f"model-call-{self._next_model_call_ordinal}"
                self._next_model_call_ordinal += 1
            error_code = _identifier_or_none(_value(message, "error"))
            self.events.append(
                {
                    "event_type": "model_call",
                    "payload": {
                        "model_call_id": message_id,
                        "provider_request_id": _bounded_optional_text(
                            _value(message, "request_id"), 200
                        ),
                        "provider_message_id": _bounded_optional_text(
                            _value(body, "id") or _value(body, "message_id"), 200
                        ),
                        "model_id": _bounded_identifier_text(
                            _value(body, "model") or "unknown-model", 200
                        ),
                        "status": "FAILED" if error_code else "SUCCEEDED",
                        "started_at": self._request_started_wall if started is not None else None,
                        "completed_at": completed_wall,
                        "duration_ms": (
                            max(0, int((completed_monotonic - started) * 1000))
                            if started is not None
                            else None
                        ),
                        "duration_source": (
                            "SDK_OBSERVED" if started is not None else "UNAVAILABLE"
                        ),
                        "usage": _nullable_usage(_value(body, "usage")),
                        "stop_reason": _bounded_optional_text(_value(body, "stop_reason"), 128),
                        "error_code": error_code,
                        "error_summary": ("模型响应失败" if error_code else None),
                    },
                }
            )
            self._request_started_at = None
            self._request_started_wall = None
            return
        if message_type == "result":
            self.accounting = _result_accounting(message)


def _sdk_message_type(message: Any) -> str:
    explicit = _value(message, "type")
    if isinstance(explicit, str):
        return explicit
    name = message.__class__.__name__.lower()
    if name.endswith("message"):
        name = name.removesuffix("message")
    return {"system": "system", "assistant": "assistant", "result": "result"}.get(name, name)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _bounded_optional_text(value: Any, maximum: int) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return _redact_sensitive_text(value)[:maximum]


def _bounded_identifier_text(value: Any, maximum: int) -> str:
    text = _redact_sensitive_text(str(value or "unknown"))[:maximum]
    return text or "unknown"


def _bounded_int(value: Any, minimum: int, maximum: int, fallback: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(number, maximum))


def _non_negative_or_none(value: Any) -> int | float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0 or number != number or number in {float("inf"), float("-inf")}:
        return None
    return int(number) if number.is_integer() else number


def _token_or_none(source: dict[str, Any], *names: str) -> int | None:
    for name in names:
        if name in source:
            value = _non_negative_or_none(source[name])
            return int(value) if value is not None else None
    return None


def _nullable_usage(value: Any) -> dict[str, int | None]:
    source = value if isinstance(value, dict) else {}
    return {
        "input_tokens": _token_or_none(source, "input_tokens", "inputTokens"),
        "output_tokens": _token_or_none(source, "output_tokens", "outputTokens"),
        "cache_read_input_tokens": _token_or_none(
            source, "cache_read_input_tokens", "cacheReadInputTokens"
        ),
        "cache_creation_input_tokens": _token_or_none(
            source, "cache_creation_input_tokens", "cacheCreationInputTokens"
        ),
    }


def _unavailable_accounting() -> dict[str, Any]:
    return {
        "status": "UNAVAILABLE",
        "duration_ms": None,
        "duration_api_ms": None,
        "num_turns": None,
        "usage": _nullable_usage(None),
        "model_usage": [],
        "estimated_cost_usd": None,
        "permission_denials_count": 0,
    }


def _result_accounting(message: Any) -> dict[str, Any]:
    raw_models = _value(message, "modelUsage") or _value(message, "model_usage") or {}
    models: list[dict[str, Any]] = []
    if isinstance(raw_models, dict):
        for model_id, item in list(raw_models.items())[:64]:
            if not isinstance(item, dict):
                continue
            models.append(
                {
                    "model_id": _bounded_identifier_text(model_id, 200),
                    "canonical_model": _bounded_optional_text(
                        item.get("canonicalModel") or item.get("canonical_model"), 200
                    ),
                    "provider": _bounded_optional_text(item.get("provider"), 64),
                    "usage": _nullable_usage(item),
                    "estimated_cost_usd": _non_negative_or_none(
                        item.get("costUSD", item.get("cost_usd"))
                    ),
                }
            )
    raw_usage = _value(message, "usage")
    return {
        "status": "COMPLETE"
        if models
        else "PARTIAL"
        if isinstance(raw_usage, dict)
        else "UNAVAILABLE",
        "duration_ms": _non_negative_or_none(_value(message, "duration_ms")),
        "duration_api_ms": _non_negative_or_none(_value(message, "duration_api_ms")),
        "num_turns": _non_negative_or_none(_value(message, "num_turns")),
        "usage": _nullable_usage(raw_usage),
        "model_usage": models,
        "estimated_cost_usd": _non_negative_or_none(_value(message, "total_cost_usd")),
        "permission_denials_count": min(len(_value(message, "permission_denials") or []), 1024),
    }


def _safe_server_code(value: Any) -> str | None:
    if value in {"tools", "tool_mcp"}:
        return "tool-mcp"
    if value in {"ones", "ones_mcp"}:
        return "ones-mcp"
    return _identifier_or_none(value)


def _safe_mcp_status(value: Any) -> str:
    return {
        "connected": "CONNECTED",
        "failed": "FAILED",
        "disconnected": "DISCONNECTED",
    }.get(str(value or "").lower(), "UNKNOWN")


def _http_status_or_none(value: Any) -> int | None:
    try:
        status = int(value)
    except (TypeError, ValueError):
        return None
    return status if 100 <= status <= 599 else None


class RealClaudeCodeAgentClient:
    def __init__(
        self,
        *,
        model: str,
        tool_registry: ToolRegistry,
        limits: ExecutionSettings,
        api_key: str,
        base_url: str = "",
        sdk_loader: Callable[[], ClaudeSdk] | None = None,
        secret_resolver: Callable[[str], str] | None = None,
        agent_repository: AgentRepository | None = None,
        sandbox_manager: JobSandboxManager | None = None,
        cancellation_event: threading.Event | None = None,
    ) -> None:
        self.model = model
        del tool_registry
        self.limits = limits
        self.api_key = api_key
        self.base_url = base_url
        self.sdk_loader = sdk_loader or load_claude_agent_sdk
        self.secret_resolver = secret_resolver
        self.agent_repository = agent_repository
        self.sandbox_manager = sandbox_manager or JobSandboxManager(
            Path(tempfile.gettempdir()) / "enterprise-agent-python-runtime-sandboxes"
        )
        self._sandbox: ContextVar[JobSandbox | None] = ContextVar(
            f"python_runtime_sandbox_{id(self)}",
            default=None,
        )
        self.cancellation_event = cancellation_event
        self.last_runtime_events: list[dict[str, Any]] = []
        self.last_accounting: dict[str, Any] = _unavailable_accounting()

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        assert_external_io_allowed("model.run")
        binding = request.context.model_runtime_binding or self._legacy_binding(
            request.context.model
        )
        api_key = self._resolve_api_key(binding)
        if not api_key:
            raise NonRetryableExecutionError(
                "ANTHROPIC_API_KEY is required when FEATURE_REAL_CLAUDE=true",
                safe_message="尚未配置 Claude 运行时 API Key",
            )
        if _looks_placeholder_api_key(api_key):
            raise NonRetryableExecutionError(
                "ANTHROPIC_API_KEY is still a placeholder value",
                safe_message="Claude 运行时 API Key 仍为占位值，请在 .env 中配置真实的 DeepSeek API Key",
            )
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._run_async(request, binding, api_key))
        result: AgentRunResult | None = None
        error: BaseException | None = None

        def runner() -> None:
            nonlocal result, error
            try:
                result = asyncio.run(self._run_async(request, binding, api_key))
            except BaseException as exc:
                error = exc

        thread = threading.Thread(target=runner, name="claude-agent-sdk-runner")
        thread.start()
        thread.join()
        if error is not None:
            raise error
        if result is None:
            raise RetryableExecutionError(
                "Claude runtime did not return a result",
                safe_message="Claude 运行时没有返回结果",
            )
        return result

    async def _run_async(
        self,
        request: AgentRunRequest,
        binding: ModelRuntimeBinding,
        api_key: str,
    ) -> AgentRunResult:
        sandbox = self.sandbox_manager.create(request.job_id)
        token = self._sandbox.set(sandbox)
        try:
            return await self._run_in_sandbox_async(request, binding, api_key)
        finally:
            try:
                await self._close_mcp_server()
            finally:
                self._sandbox.reset(token)
                sandbox.cleanup()

    async def _run_in_sandbox_async(
        self,
        request: AgentRunRequest,
        binding: ModelRuntimeBinding,
        api_key: str,
    ) -> AgentRunResult:
        sdk = self._load_sdk()
        tool_events: list[dict[str, Any]] = []
        mcp_server = await self._open_mcp_server(request, sdk)
        cli_stderr: list[str] = []
        runtime_context = await self._prepare_context(request.context)
        options = self._build_options(sdk, runtime_context, mcp_server, cli_stderr, binding)
        prompt = _streaming_user_prompt(request.context.user_question)
        assistant_texts: list[str] = []
        parsed_tool_events: list[dict[str, Any]] = []
        parsed_tool_calls: dict[str, dict[str, Any]] = {}
        final_answer = ""
        audit = _SdkAuditNormalizer()
        self.last_runtime_events = []
        self.last_accounting = _unavailable_accounting()

        async def consume() -> None:
            nonlocal final_answer
            async for message in sdk.query(prompt=prompt, options=options):
                if request.context.runtime_protocol_version == "1.2":
                    audit.consume(message)
                    self.last_runtime_events = list(audit.events)
                    self.last_accounting = dict(audit.accounting)
                error_result = _result_error_details(message)
                if error_result is not None:
                    detail, inconsistent = error_result
                    error_code = (
                        "claude_inconsistent_result" if inconsistent else "claude_error_result"
                    )
                    raise RetryableExecutionError(
                        detail,
                        safe_message=(
                            "模型运行返回了不一致的失败结果，系统将按重试策略处理。"
                            if inconsistent
                            else "模型运行失败，系统将按重试策略处理。"
                        ),
                        tool_events=tool_events,
                        error_code=error_code,
                        diagnostics=self._safe_runtime_diagnostics(
                            RuntimeError(detail), cli_stderr, binding
                        ),
                    )
                assistant_texts.extend(_extract_text_blocks(message))
                parsed_tool_events.extend(
                    _extract_tool_events(message, self.limits, parsed_tool_calls)
                )
                result_text = _extract_result_text(message)
                if result_text:
                    final_answer = result_text

        try:
            with _temporary_claude_env(api_key, binding):
                await self._consume_with_cancellation(
                    consume(),
                    timeout_seconds=request.context.timeout_seconds,
                )
        except asyncio.TimeoutError as exc:
            raise RetryableExecutionError(
                "Claude Agent SDK execution timed out",
                safe_message="Claude 运行超时",
                tool_events=tool_events,
                error_code="runtime_timeout",
            ) from exc
        except Exception as exc:
            self._raise_mapped_sdk_error(exc, cli_stderr, tool_events, binding)

        if not final_answer:
            final_answer = "\n".join(text for text in assistant_texts if text).strip()
        if not final_answer:
            raise RetryableExecutionError(
                "Claude Agent SDK completed without a final answer",
                safe_message="Claude 运行结束，但没有生成最终回答",
            )
        return AgentRunResult(
            final_answer=final_answer,
            tool_events=tool_events if tool_events else parsed_tool_events,
        )

    async def _consume_with_cancellation(
        self,
        consume: Any,
        *,
        timeout_seconds: int,
    ) -> None:
        execution = asyncio.create_task(consume)
        cancellation: asyncio.Task[None] | None = None
        if self.cancellation_event is not None:

            async def wait_for_cancellation() -> None:
                while not self.cancellation_event.is_set():
                    await asyncio.sleep(0.05)

            cancellation = asyncio.create_task(wait_for_cancellation())
        try:
            watched = {execution, *([cancellation] if cancellation is not None else [])}
            completed, _pending = await asyncio.wait(
                watched,
                timeout=timeout_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if execution in completed:
                await execution
                return
            execution.cancel()
            try:
                await execution
            except asyncio.CancelledError:
                pass
            if self.cancellation_event is not None and self.cancellation_event.is_set():
                raise NonRetryableExecutionError(
                    "Claude Agent SDK execution was cancelled",
                    safe_message="Agent 执行已取消",
                    error_code="runtime_cancelled",
                )
            raise asyncio.TimeoutError
        finally:
            if cancellation is not None:
                cancellation.cancel()
                try:
                    await cancellation
                except asyncio.CancelledError:
                    pass

    def test_connection(
        self,
        binding: ModelRuntimeBinding,
        api_key: str,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        assert_external_io_allowed("model.test_connection")
        if _looks_placeholder_api_key(api_key):
            raise NonRetryableExecutionError(
                "Model connection credential is missing or placeholder",
                safe_message="尚未配置模型连接凭据",
                error_code="model_connection_credential_unavailable",
            )

        async def probe() -> dict[str, Any]:
            sdk = self._load_sdk()
            stderr: list[str] = []
            with tempfile.TemporaryDirectory(prefix="enterprise-agent-model-probe-") as workspace:
                options = sdk.options(
                    model=binding.model,
                    system_prompt=(
                        "You are performing an administrator-requested connection test. "
                        "Return only OK. Do not use tools, files, skills, or external context."
                    ),
                    mcp_servers={},
                    strict_mcp_config=True,
                    tools=[],
                    allowed_tools=[],
                    disallowed_tools=[
                        "Bash",
                        "Write",
                        "Edit",
                        "NotebookEdit",
                        "WebFetch",
                        "WebSearch",
                        "Shell",
                    ],
                    permission_mode="dontAsk",
                    max_turns=1,
                    cwd=workspace,
                    setting_sources=[],
                    skills=[],
                    effort=binding.effort_level,
                    stderr=lambda line: _append_cli_stderr(
                        stderr, line, self.limits.max_tool_response_chars
                    ),
                )
                received = False

                async def consume() -> None:
                    nonlocal received
                    async for message in sdk.query(prompt="Reply OK.", options=options):
                        error_result = _result_error_details(message)
                        if error_result is not None:
                            raise RetryableExecutionError(
                                error_result[0],
                                safe_message="模型提供方拒绝了连接测试",
                                error_code="model_connection_provider_rejected",
                            )
                        if _extract_result_text(message) or _extract_text_blocks(message):
                            received = True

                try:
                    with _temporary_claude_env(api_key, binding):
                        await asyncio.wait_for(consume(), timeout=timeout_seconds)
                except asyncio.TimeoutError as exc:
                    raise RetryableExecutionError(
                        "Model connection test timed out",
                        safe_message="模型连接测试超时",
                        error_code="model_connection_test_timeout",
                    ) from exc
                except Exception as exc:
                    self._raise_mapped_sdk_error(exc, stderr, [], binding)
            if not received:
                raise RetryableExecutionError(
                    "Model connection test returned no content",
                    safe_message="模型连接测试没有返回内容",
                    error_code="model_connection_empty_result",
                )
            return {"detail": "连接成功"}

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(probe())
        result: dict[str, Any] | None = None
        error: BaseException | None = None

        def runner() -> None:
            nonlocal result, error
            try:
                result = asyncio.run(probe())
            except BaseException as exc:
                error = exc

        thread = threading.Thread(target=runner, name="model-connection-test")
        thread.start()
        thread.join()
        if error is not None:
            raise error
        return result or {"detail": "连接成功"}

    def _resolve_api_key(self, binding: ModelRuntimeBinding) -> str:
        if binding.legacy:
            return self.api_key
        if self.secret_resolver is None:
            raise NonRetryableExecutionError(
                "Model connection secret resolver is unavailable",
                safe_message="模型运行凭据解析器不可用",
                error_code="model_connection_credential_unavailable",
            )
        return self.secret_resolver(binding.secret_ref)

    def _legacy_binding(self, context_model: str) -> ModelRuntimeBinding:
        model = context_model or self.model
        return ModelRuntimeBinding(
            protocol=ANTHROPIC_COMPATIBLE_PROTOCOL,
            base_url=self.base_url,
            model=model,
            default_opus_model=os.getenv("ANTHROPIC_DEFAULT_OPUS_MODEL", model) or model,
            default_sonnet_model=(os.getenv("ANTHROPIC_DEFAULT_SONNET_MODEL", model) or model),
            default_haiku_model=os.getenv("ANTHROPIC_DEFAULT_HAIKU_MODEL", model) or model,
            subagent_model=os.getenv("CLAUDE_CODE_SUBAGENT_MODEL", model) or model,
            effort_level=os.getenv("CLAUDE_CODE_EFFORT_LEVEL", "max") or "max",
            legacy=True,
        )

    def _load_sdk(self) -> ClaudeSdk:
        try:
            return self.sdk_loader()
        except ModuleNotFoundError as exc:
            raise NonRetryableExecutionError(
                "Claude Agent SDK dependency is not installed",
                safe_message="尚未安装 Claude 运行时依赖",
                error_code="claude_sdk_unavailable",
            ) from exc

    def _build_mcp_server(self, request: AgentRunRequest) -> Any | None:
        if request.context.allowed_tools:
            raise NonRetryableExecutionError(
                "Python Runtime requires the deployment-fixed standard MCP server",
                safe_message="Python Runtime 的标准 MCP 工具服务未配置",
                error_code="mcp_tool_server_required",
            )
        return None

    async def _open_mcp_server(self, request: AgentRunRequest, sdk: ClaudeSdk) -> Any:
        del sdk
        return self._build_mcp_server(request)

    async def _close_mcp_server(self) -> None:
        return None

    async def _prepare_context(
        self,
        context: AgentExecutionContext,
    ) -> AgentExecutionContext:
        return context

    def _build_options(
        self,
        sdk: ClaudeSdk,
        context: AgentExecutionContext,
        server: Any,
        cli_stderr: list[str],
        binding: ModelRuntimeBinding,
    ) -> Any:
        exact_tools = [f"mcp__tool_mcp__{tool_name}" for tool_name in context.allowed_tools]
        sandbox = self._sandbox.get()
        if sandbox is None:
            raise NonRetryableExecutionError(
                "Python Runtime Job Sandbox is unavailable",
                safe_message="当前任务沙盒不可用",
                error_code="runtime_sandbox_unavailable",
            )
        return sdk.options(
            model=binding.model,
            system_prompt=_build_system_prompt(context),
            mcp_servers={"tool_mcp": server} if server is not None else {},
            strict_mcp_config=True,
            tools=[],
            allowed_tools=exact_tools,
            disallowed_tools=[
                "Bash",
                "Write",
                "Edit",
                "WebFetch",
                "WebSearch",
                "NotebookEdit",
            ],
            permission_mode="dontAsk",
            max_turns=context.max_turns,
            cwd=sandbox.path,
            setting_sources=[],
            skills=[],
            stderr=lambda line: _append_cli_stderr(
                cli_stderr,
                line,
                self.limits.max_tool_response_chars,
            ),
        )

    def _raise_mapped_sdk_error(
        self,
        exc: Exception,
        cli_stderr: list[str],
        tool_events: list[dict[str, Any]] | None = None,
        binding: ModelRuntimeBinding | None = None,
    ) -> None:
        tool_events = tool_events or []
        if isinstance(exc, (RetryableExecutionError, NonRetryableExecutionError)):
            raise exc
        if isinstance(exc, ToolPolicyError):
            raise NonRetryableExecutionError(
                str(exc),
                safe_message=exc.safe_message,
                tool_events=tool_events,
                error_code="tool_policy_error",
            ) from exc
        name = exc.__class__.__name__
        message = _sdk_error_message(exc, cli_stderr)
        diagnostics = self._safe_runtime_diagnostics(exc, cli_stderr, binding)
        if _looks_inconsistent_result(message):
            raise RetryableExecutionError(
                message,
                safe_message="模型运行返回了不一致的失败结果，系统将按重试策略处理。",
                tool_events=tool_events,
                error_code="claude_inconsistent_result",
                diagnostics=diagnostics,
            ) from exc
        if _looks_max_turns_exhausted(message):
            raise DiagnosticLoopExhausted(
                message,
                safe_message=_safe_sdk_error_message("Claude 运行失败", message),
                tool_events=tool_events,
                error_code="max_turns_exhausted",
                diagnostics=diagnostics,
            ) from exc
        if name in {"CLINotFoundError", "CLIConnectionError"}:
            raise NonRetryableExecutionError(
                message,
                safe_message=_safe_sdk_error_message("Claude Code CLI 运行时不可用", message),
                tool_events=tool_events,
                error_code="claude_cli_unavailable",
                diagnostics=diagnostics,
            ) from exc
        if _looks_invalid_model(message):
            raise NonRetryableExecutionError(
                message,
                safe_message="模型配置无效，请联系管理员检查 Agent 的模型策略。",
                tool_events=tool_events,
                error_code="claude_invalid_model",
                diagnostics=diagnostics,
            ) from exc
        if name in {"ProcessError", "CLIJSONDecodeError"} or _looks_transient(message):
            raise RetryableExecutionError(
                message,
                safe_message=_safe_sdk_error_message("Claude 运行时发生暂时性错误", message),
                tool_events=tool_events,
                error_code="claude_transient_error",
                diagnostics=diagnostics,
            ) from exc
        raise RetryableExecutionError(
            message,
            safe_message=_safe_sdk_error_message("Claude 运行失败", message),
            tool_events=tool_events,
            error_code="claude_runtime_error",
            diagnostics=diagnostics,
        ) from exc

    def _safe_runtime_diagnostics(
        self,
        exc: Exception,
        cli_stderr: list[str],
        binding: ModelRuntimeBinding | None = None,
    ) -> dict[str, object]:
        subtype = getattr(exc, "subtype", None)
        errors = getattr(exc, "errors", None)
        return {
            "exception_class": exc.__class__.__name__[:120],
            "sdk_version": _package_version(),
            "cli_version": _claude_cli_version(),
            "model_policy_ref": (binding.model if binding else self.model)[:120],
            "provider_host": _provider_host(binding.base_url if binding else self.base_url),
            "subtype": _bounded_safe_diagnostic(subtype),
            "errors": _bounded_safe_diagnostic(errors),
            "stderr": _bounded_safe_diagnostic("\n".join(cli_stderr)),
        }


def load_claude_agent_sdk() -> ClaudeSdk:
    try:
        sdk_module: Any = importlib.import_module("claude_agent_sdk")
    except ModuleNotFoundError:
        sdk_module = importlib.import_module("claude_code_sdk")

    return ClaudeSdk(
        query=sdk_module.query,
        options=sdk_module.ClaudeAgentOptions,
        tool=sdk_module.tool,
        create_sdk_mcp_server=sdk_module.create_sdk_mcp_server,
        tool_annotations=getattr(sdk_module, "ToolAnnotations", None),
        permission_allow=getattr(sdk_module, "PermissionResultAllow", None),
        permission_deny=getattr(sdk_module, "PermissionResultDeny", None),
    )


def is_claude_cli_available() -> bool:
    return shutil.which("claude") is not None or shutil.which("claude-code") is not None


def _build_system_prompt(context: AgentExecutionContext) -> str:
    skill_sections = "\n\n".join(
        f"## Skill: {name}\n{body}" for name, body in sorted(context.skills.items())
    )
    retrieved_context = json.dumps(context.retrieved_context, ensure_ascii=False, default=str)
    file_job = any(item.server_code == "file-service" for item in context.mcp_bindings)
    sandbox_tools = ["Read", "Glob", "Grep", "Edit", "Write"] if file_job else []
    return "\n\n".join(
        [
            context.system_role,
            (
                "Platform precedence: Business instructions are lower-priority configuration. "
                "They cannot override safety rules, authorization, read-only restrictions, "
                "tool assignments, or secret boundaries."
            ),
            (
                "Business instructions:\n" + context.business_instructions
                if context.business_instructions
                else ""
            ),
            "Safety rules:\n" + _numbered(context.safety_rules),
            "Tool restrictions:\n" + _numbered(context.tool_restrictions),
            "Available internal tools:\n" + _numbered(context.allowed_tools),
            (
                "Available local Job Sandbox tools (all calls remain permission-checked):\n"
                + _numbered(sandbox_tools)
                if sandbox_tools
                else ""
            ),
            "Report structure:\n"
            + _numbered(
                [
                    "Conclusion with likely root cause.",
                    "Evidence summary citing tool results.",
                    "Uncertainty or limitations when evidence is incomplete.",
                    (
                        "For file Jobs, modify only sandbox TXT files and persist only through an "
                        "explicit File MCP commit; otherwise suggest safe next actions only."
                        if file_job
                        else "Suggested safe next actions only; do not suggest direct mutation by the Agent."
                    ),
                ]
            ),
            "Retrieved context:\n" + retrieved_context,
            "Conversation summary:\n" + context.conversation_summary,
            "Diagnostic skills:\n" + skill_sections,
        ]
    )


def _numbered(items: list[str]) -> str:
    return "\n".join(f"{index}. {item}" for index, item in enumerate(items, start=1))


def _extract_text_blocks(message: Any) -> list[str]:
    texts = []
    for block in _content_blocks(message):
        block_type = _value(block, "type")
        text = _value(block, "text")
        if block_type == "text" and isinstance(text, str):
            texts.append(text)
    return texts


def _extract_result_text(message: Any) -> str:
    result = _value(message, "result")
    if isinstance(result, str):
        return result
    if _value(message, "type") == "result":
        content = _value(message, "content")
        return content if isinstance(content, str) else ""
    return ""


def _extract_tool_events(
    message: Any,
    limits: ExecutionSettings,
    calls: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    call_index = calls if calls is not None else {}
    events = []
    metadata = _platform_tool_metadata(message)
    for block in _content_blocks(message):
        block_type = _value(block, "type")
        if block_type not in {"tool_use", "tool_result"}:
            continue
        tool_call_id = str(_value(block, "id") or _value(block, "tool_use_id") or "")
        if not tool_call_id:
            continue
        if block_type == "tool_use":
            tool_name = str(_value(block, "name") or _value(block, "tool_name") or "unknown_tool")
            request_payload = _safe_file_tool_request(tool_name, _value(block, "input") or {})
            call_index[tool_call_id] = {
                "tool_name": tool_name,
                "request_payload": request_payload,
            }
            status = "STARTED"
        else:
            started = call_index.pop(tool_call_id, {})
            tool_name = str(started.get("tool_name") or "unknown_tool")
            request_payload = started.get("request_payload") or {}
            status = "FAILED" if _value(block, "is_error") is True else "SUCCEEDED"
        response = (
            {"file_tool_result": "omitted"}
            if tool_name in {"Read", "Grep", "Write", "Edit"}
            else _value(block, "content") or _value(block, "result") or {}
        )
        events.append(
            {
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "request_payload": _bounded_payload(
                    request_payload, limits.max_tool_response_chars
                ),
                "response_summary": _bounded_payload(response, limits.max_tool_response_chars),
                "status": status,
                "duration_ms": 0,
                "risk_level": _risk_level(tool_name),
                "mcp_call_id": metadata["mcp_call_id"],
                "persisted_tool_call_id": metadata["persisted_tool_call_id"],
            }
        )
    return events


def _safe_file_tool_request(tool_name: str, value: Any) -> Any:
    if tool_name not in {"Read", "Grep", "Write", "Edit"} or not isinstance(value, dict):
        return value
    path = value.get("file_path", value.get("path"))
    result: dict[str, Any] = {}
    if isinstance(path, str):
        result["relative_path"] = path[:240]
    if tool_name == "Write" and isinstance(value.get("content"), str):
        result["content_bytes"] = len(value["content"].encode("utf-8"))
    if tool_name == "Edit":
        if isinstance(value.get("old_string"), str):
            result["old_string_bytes"] = len(value["old_string"].encode("utf-8"))
        if isinstance(value.get("new_string"), str):
            result["new_string_bytes"] = len(value["new_string"].encode("utf-8"))
        if isinstance(value.get("replace_all"), bool):
            result["replace_all"] = value["replace_all"]
    if tool_name == "Read":
        for field in ("offset", "limit"):
            if isinstance(value.get(field), int) and not isinstance(value.get(field), bool):
                result[field] = value[field]
    if tool_name == "Grep" and isinstance(value.get("pattern"), str):
        result["pattern_chars"] = len(value["pattern"])
    return result


def _platform_tool_metadata(message: Any) -> dict[str, str | None]:
    result = _value(message, "tool_use_result")
    if not isinstance(result, dict):
        return {"mcp_call_id": None, "persisted_tool_call_id": None}
    metadata = result.get("_meta")
    if not isinstance(metadata, dict):
        return {"mcp_call_id": None, "persisted_tool_call_id": None}
    return {
        "mcp_call_id": _identifier_or_none(metadata.get("enterprise-agent/mcp-call-id")),
        "persisted_tool_call_id": _identifier_or_none(
            metadata.get("enterprise-agent/agent-tool-call-id")
        ),
    }


def _identifier_or_none(value: Any) -> str | None:
    if not isinstance(value, str) or not 1 <= len(value) <= 128:
        return None
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", value):
        return None
    return value


def _content_blocks(message: Any) -> list[Any]:
    content = _value(message, "content")
    if isinstance(content, list):
        return content
    return []


def _value(source: Any, key: str) -> Any:
    if isinstance(source, dict):
        return source.get(key)
    return getattr(source, key, None)


def _bounded_payload(payload: Any, max_chars: int) -> dict[str, Any]:
    serialized = json.dumps(payload, ensure_ascii=False, default=str)
    truncated = len(serialized) > max_chars
    if truncated:
        serialized = serialized[:max_chars]
    return {"payload": serialized, "truncated": truncated}


def _risk_level(tool_name: str) -> str:
    if tool_name.startswith("get_") or tool_name.startswith("diagnose_loki"):
        return "low"
    return "low" if tool_name == "query_loki" else "medium"


def _looks_transient(message: str) -> bool:
    lower = message.lower()
    return any(
        item in lower
        for item in (
            "timeout",
            "timed out",
            "temporarily",
            "rate limit",
            "overloaded",
            "529",
            "503",
            "502",
            "connection",
            "transport",
            "json",
        )
    )


def _looks_inconsistent_result(message: str) -> bool:
    lower = message.lower()
    return "error result: success" in lower or ("is_error=true" in lower and "success" in lower)


def _looks_invalid_model(message: str) -> bool:
    lower = message.lower()
    return any(
        marker in lower
        for marker in (
            "model not found",
            "invalid model",
            "unknown model",
            "does not exist or you do not have access to it",
        )
    )


def _result_error_details(message: Any) -> tuple[str, bool] | None:
    is_error = _value(message, "is_error")
    if is_error is not True:
        return None
    subtype = _value(message, "subtype")
    errors = _value(message, "errors")
    result = _value(message, "result")
    detail = _compact_error_detail(
        json.dumps(
            {"subtype": subtype, "errors": errors, "result": result},
            ensure_ascii=False,
            default=str,
        )
    )
    inconsistent = str(result).strip().lower() == "success" or (
        not errors and str(subtype or "").lower() in {"success", "completed"}
    )
    return detail or "Claude runtime returned an error result", inconsistent


def _looks_max_turns_exhausted(message: str) -> bool:
    lower = message.lower()
    return "maximum number of turns" in lower or "max turns" in lower


def _append_cli_stderr(lines: list[str], line: str, max_chars: int) -> None:
    text = _redact_sensitive_text(str(line)).strip()
    if not text:
        return
    lines.append(text)
    total = sum(len(item) for item in lines)
    while lines and total > max_chars:
        removed = lines.pop(0)
        total -= len(removed)


def _sdk_error_message(exc: Exception, cli_stderr: list[str]) -> str:
    message = _redact_sensitive_text(str(exc)).strip()
    stderr = "\n".join(cli_stderr).strip()
    if stderr and stderr not in message:
        if message:
            return f"{message}\nCLI stderr:\n{stderr}"
        return stderr
    return message or exc.__class__.__name__


def _safe_sdk_error_message(prefix: str, detail: str) -> str:
    compact = _compact_error_detail(detail)
    return f"{prefix}: {compact}" if compact else prefix


def _compact_error_detail(detail: str, max_chars: int = 500) -> str:
    text = _redact_sensitive_text(detail)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _redact_sensitive_text(text: str) -> str:
    patterns = (
        (r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+", r"\1<redacted>"),
        (r"(?i)(x-api-key\s*[:=]\s*)[^\s,;]+", r"\1<redacted>"),
        (r"(?i)(anthropic_api_key\s*[:=]\s*)[^\s,;]+", r"\1<redacted>"),
        (r"(?i)(anthropic_auth_token\s*[:=]\s*)[^\s,;]+", r"\1<redacted>"),
        (r"(?i)(api[_-]?key\s*[:=]\s*)[^\s,;]+", r"\1<redacted>"),
        (r"(?i)https?://[^\s\]\[\)\(\}\{\"']+", "<redacted-url>"),
    )
    redacted = text
    for pattern, replacement in patterns:
        redacted = re.sub(pattern, replacement, redacted)
    return redacted


def _bounded_safe_diagnostic(value: Any, max_chars: int = 500) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, default=str)
    return _compact_error_detail(text, max_chars=max_chars)


def _provider_host(base_url: str) -> str:
    if not base_url:
        return "default"
    try:
        return (urlsplit(base_url).hostname or "invalid").lower()[:255]
    except ValueError:
        return "invalid"


@lru_cache(maxsize=1)
def _package_version() -> str:
    for package in ("claude-agent-sdk", "claude-code-sdk"):
        try:
            return importlib.metadata.version(package)[:80]
        except importlib.metadata.PackageNotFoundError:
            continue
    return "unknown"


@lru_cache(maxsize=1)
def _claude_cli_version() -> str:
    executable = shutil.which("claude") or shutil.which("claude-code")
    if not executable:
        return "unavailable"
    try:
        completed = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return _compact_error_detail(completed.stdout or completed.stderr, max_chars=80) or "unknown"


def _looks_placeholder_api_key(value: str) -> bool:
    normalized = value.strip().strip("\"'").lower()
    return (
        not normalized
        or normalized.startswith("<")
        or normalized.startswith("your-")
        or normalized.startswith("your_")
        or normalized in {"your-key", "your-api-key", "test-key", "replace-me"}
        or "你的" in normalized
        or "api key" in normalized
        or "api-key" in normalized
    )


_CLAUDE_ENV_LOCK = threading.RLock()


@contextmanager
def _temporary_claude_env(api_key: str, binding: ModelRuntimeBinding) -> Iterator[None]:
    values = {
        "ANTHROPIC_API_KEY": api_key,
        "ANTHROPIC_AUTH_TOKEN": api_key,
        "ANTHROPIC_BASE_URL": binding.base_url,
        "ANTHROPIC_MODEL": binding.model,
        "CLAUDE_MODEL": binding.model,
        "ANTHROPIC_DEFAULT_OPUS_MODEL": binding.default_opus_model,
        "ANTHROPIC_DEFAULT_SONNET_MODEL": binding.default_sonnet_model,
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": binding.default_haiku_model,
        "CLAUDE_CODE_SUBAGENT_MODEL": binding.subagent_model,
        "CLAUDE_CODE_EFFORT_LEVEL": binding.effort_level,
    }
    with _CLAUDE_ENV_LOCK:
        previous = {name: os.environ.get(name) for name in values}
        for name, value in values.items():
            if value:
                os.environ[name] = value
            else:
                os.environ.pop(name, None)
        try:
            yield
        finally:
            for name, previous_value in previous.items():
                _restore_env(name, previous_value)


def _restore_env(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value
