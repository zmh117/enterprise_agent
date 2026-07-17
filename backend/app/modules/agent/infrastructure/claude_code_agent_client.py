from __future__ import annotations

import asyncio
import importlib
import json
import os
import re
import shutil
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Protocol

from app.modules.agent.domain.runtime import (
    AgentExecutionContext,
    AgentRunRequest,
    AgentRunResult,
)
from app.modules.agent.infrastructure.mcp_tool_registry import ToolRegistry
from app.modules.internal_tools.infrastructure.internal_api_client import ToolResult
from app.shared.config import ExecutionSettings
from app.shared.exceptions import (
    DiagnosticLoopExhausted,
    NonRetryableExecutionError,
    RetryableExecutionError,
    ToolPolicyError,
)


class ClaudeCodeAgentClient(Protocol):
    def run(self, request: AgentRunRequest) -> AgentRunResult: ...


@dataclass(frozen=True)
class ClaudeSdk:
    query: Callable[..., AsyncIterator[Any]]
    options: Any
    tool: Callable[..., Any]
    create_sdk_mcp_server: Callable[..., Any]
    tool_annotations: Any | None


# Structured addressing shared by database/redis/loki tools. Optional for backward
# compatibility with the flat datasource contract; required by the topology-aware platform.
_ADDRESSING_PROPERTIES: dict[str, Any] = {
    "environment": {
        "type": "string",
        "description": "Environment code, e.g. 'sanjiu' or 'mmk'.",
    },
    "base": {
        "type": "string",
        "description": "Base business code, e.g. 'guanlan' (观澜基地).",
    },
    "workshop": {
        "type": "string",
        "description": "Workshop code within a partitioned base, e.g. 'GL001'.",
    },
}

_LOKI_SELECTOR_PROPERTIES: dict[str, Any] = {
    "cluster": {"type": "string"},
    "container": {"type": "string"},
    "region": {"type": "string"},
    "service": {"type": "string"},
    "service_name": {"type": "string"},
    "workshop": {"type": "string"},
}


TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "get_er_context": {
        "description": "Search compact ER graph context for relevant tables, fields, enums, and relationships.",
        "schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    "get_business_flow_context": {
        "description": "Search compact business-flow context for relevant process nodes and flow evidence.",
        "schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    "get_schema_directory": {
        "description": (
            "Return the allowed read-only schema directory for a target environment/base/workshop. "
            "Use this before writing SQL. Only query tables and columns listed by this tool."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Optional table-name filter; leave empty for the bounded directory.",
                },
                "limit": {"type": "integer", "minimum": 1},
                **_ADDRESSING_PROPERTIES,
            },
            "required": ["environment", "base"],
            "additionalProperties": False,
        },
    },
    "query_loki": {
        "description": (
            "Query bounded Loki logs with exact-match label selectors and a small result limit. "
            "Use selector for labels such as cluster, service_name, container, region, or service; "
            "for example {'cluster': 'mes-cluster'}."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "selector": {
                    "type": "object",
                    "properties": _LOKI_SELECTOR_PROPERTIES,
                    "additionalProperties": False,
                    "minProperties": 1,
                },
                "service": {
                    "type": "string",
                    "description": "Backward-compatible shortcut for selector.service.",
                },
                "query": {"type": "string"},
                "minutes": {"type": "integer", "minimum": 1},
                "limit": {"type": "integer", "minimum": 1},
                **_ADDRESSING_PROPERTIES,
            },
            "required": ["selector"],
            "additionalProperties": False,
        },
    },
    "diagnose_loki_labels": {
        "description": (
            "List bounded Loki label names visible for the resolved environment/base/workshop. "
            "Use this when a Loki query returns no logs or the correct service label is unclear."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "minutes": {"type": "integer", "minimum": 1},
                "limit": {"type": "integer", "minimum": 1},
                **_ADDRESSING_PROPERTIES,
            },
            "required": ["environment", "base"],
            "additionalProperties": False,
        },
    },
    "diagnose_loki_label_values": {
        "description": (
            "List bounded values for an allowed Loki label such as service, service_name, "
            "container, cluster, region, or workshop."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "label": {
                    "type": "string",
                    "enum": [
                        "cluster",
                        "container",
                        "region",
                        "service",
                        "service_name",
                        "workshop",
                    ],
                },
                "minutes": {"type": "integer", "minimum": 1},
                "limit": {"type": "integer", "minimum": 1},
                **_ADDRESSING_PROPERTIES,
            },
            "required": ["environment", "base", "label"],
            "additionalProperties": False,
        },
    },
    "diagnose_loki_probe": {
        "description": (
            "Probe a bounded Loki selector and keyword to explain empty results. "
            "Returns stream_count, line_count, and safe empty-result hints."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "selector": {
                    "type": "object",
                    "properties": _LOKI_SELECTOR_PROPERTIES,
                    "additionalProperties": False,
                    "minProperties": 1,
                },
                "query": {"type": "string"},
                "minutes": {"type": "integer", "minimum": 1},
                "limit": {"type": "integer", "minimum": 1},
                **_ADDRESSING_PROPERTIES,
            },
            "required": ["environment", "base", "selector"],
            "additionalProperties": False,
        },
    },
    "query_database": {
        "description": (
            "Run policy-approved read-only SQL through the internal database gateway. "
            "Provide structured addressing (environment/base/workshop) so the platform "
            "routes to the correct base and enforces the workshop table prefix."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "datasource": {"type": "string"},
                "sql": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1},
                **_ADDRESSING_PROPERTIES,
            },
            "required": ["sql"],
            "additionalProperties": False,
        },
    },
    "query_redis_get": {
        "description": "Read one approved Redis key through the internal Redis gateway.",
        "schema": {
            "type": "object",
            "properties": {
                "datasource": {"type": "string"},
                "key": {"type": "string"},
                **_ADDRESSING_PROPERTIES,
            },
            "required": ["key"],
            "additionalProperties": False,
        },
    },
    "query_redis_scan": {
        "description": "Scan approved Redis key prefixes with a bounded limit.",
        "schema": {
            "type": "object",
            "properties": {
                "datasource": {"type": "string"},
                "pattern": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1},
                **_ADDRESSING_PROPERTIES,
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
    },
}


class StubClaudeCodeAgentClient:
    def run(self, request: AgentRunRequest) -> AgentRunResult:
        context = request.context.retrieved_context
        evidence = []
        if "er" in context:
            evidence.append(f"ER context: {context['er']}")
        if "business_flow" in context:
            evidence.append(f"Business flow context: {context['business_flow']}")
        final_answer = "\n".join(
            [
                "Conclusion: read-only diagnostic analysis completed.",
                f"Question: {request.context.user_question}",
                "Evidence:",
                *(f"- {item}" for item in evidence),
                "Uncertainty: runtime used configured read-only tool summaries only.",
                "Suggested next actions: review the cited evidence and perform any mutation manually through approved procedures.",
            ]
        )
        return AgentRunResult(final_answer=final_answer)


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
    ) -> None:
        self.model = model
        self.tool_registry = tool_registry
        self.limits = limits
        self.api_key = api_key
        self.base_url = base_url
        self.sdk_loader = sdk_loader or load_claude_agent_sdk

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        if not self.api_key:
            raise NonRetryableExecutionError(
                "ANTHROPIC_API_KEY is required when FEATURE_REAL_CLAUDE=true",
                safe_message="Claude runtime API key is not configured",
            )
        if _looks_placeholder_api_key(self.api_key):
            raise NonRetryableExecutionError(
                "ANTHROPIC_API_KEY is still a placeholder value",
                safe_message="Claude runtime API key is still a placeholder; set a real DeepSeek API key in .env",
            )
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._run_async(request))
        result: AgentRunResult | None = None
        error: BaseException | None = None

        def runner() -> None:
            nonlocal result, error
            try:
                result = asyncio.run(self._run_async(request))
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
                safe_message="Claude runtime did not return a result",
            )
        return result

    async def _run_async(self, request: AgentRunRequest) -> AgentRunResult:
        sdk = self._load_sdk()
        tool_events: list[dict[str, Any]] = []
        internal_server = self._build_internal_server(sdk, request, tool_events)
        cli_stderr: list[str] = []
        options = self._build_options(sdk, request.context, internal_server, cli_stderr)
        prompt = request.context.user_question
        assistant_texts: list[str] = []
        parsed_tool_events: list[dict[str, Any]] = []
        final_answer = ""

        async def consume() -> None:
            nonlocal final_answer
            async for message in sdk.query(prompt=prompt, options=options):
                assistant_texts.extend(_extract_text_blocks(message))
                parsed_tool_events.extend(_extract_tool_events(message, self.limits))
                result_text = _extract_result_text(message)
                if result_text:
                    final_answer = result_text

        try:
            with _temporary_claude_env(self.api_key, self.base_url):
                await asyncio.wait_for(
                    consume(),
                    timeout=request.context.timeout_seconds or self.limits.timeout_seconds,
                )
        except asyncio.TimeoutError as exc:
            raise RetryableExecutionError(
                "Claude Agent SDK execution timed out",
                safe_message="Claude runtime timed out",
                tool_events=tool_events,
                error_code="runtime_timeout",
            ) from exc
        except Exception as exc:
            self._raise_mapped_sdk_error(exc, cli_stderr, tool_events)

        if not final_answer:
            final_answer = "\n".join(text for text in assistant_texts if text).strip()
        if not final_answer:
            raise RetryableExecutionError(
                "Claude Agent SDK completed without a final answer",
                safe_message="Claude runtime completed without a final answer",
            )
        return AgentRunResult(
            final_answer=final_answer,
            tool_events=tool_events if tool_events else parsed_tool_events,
        )

    def _load_sdk(self) -> ClaudeSdk:
        try:
            return self.sdk_loader()
        except ModuleNotFoundError as exc:
            raise NonRetryableExecutionError(
                "Claude Agent SDK dependency is not installed",
                safe_message="Claude runtime dependency is not installed",
            ) from exc

    def _build_internal_server(
        self,
        sdk: ClaudeSdk,
        request: AgentRunRequest,
        tool_events: list[dict[str, Any]],
    ) -> Any:
        tools = [
            self._build_tool(sdk, request, tool_name, tool_events)
            for tool_name in request.context.allowed_tools
            if tool_name in TOOL_DEFINITIONS
        ]
        return sdk.create_sdk_mcp_server(name="internal", tools=tools)

    def _build_tool(
        self,
        sdk: ClaudeSdk,
        request: AgentRunRequest,
        tool_name: str,
        tool_events: list[dict[str, Any]],
    ) -> Any:
        definition = TOOL_DEFINITIONS[tool_name]

        async def handler(arguments: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
            started = time.monotonic()
            try:
                result = await asyncio.to_thread(
                    self.tool_registry.call,
                    job_id=request.job_id,
                    user_id=request.user_id,
                    project_code=request.project_code,
                    tool_name=tool_name,
                    arguments=arguments,
                    record_tool_call=False,
                )
                event = _tool_event_from_result(
                    tool_name=tool_name,
                    arguments=arguments,
                    result=result,
                    status="SUCCEEDED",
                    duration_ms=int((time.monotonic() - started) * 1000),
                    limits=self.limits,
                )
                tool_events.append(event)
                return _sdk_tool_response(result.summary)
            except Exception as exc:
                safe_message = getattr(exc, "safe_message", str(exc))
                tool_events.append(
                    {
                        "tool_name": tool_name,
                        "request_payload": arguments,
                        "response_summary": {"error": safe_message},
                        "status": "FAILED",
                        "duration_ms": int((time.monotonic() - started) * 1000),
                        "risk_level": _risk_level(tool_name),
                    }
                )
                return _sdk_tool_response({"error": safe_message, "policy": "tool_rejected"})

        decorator = _tool_decorator(
            sdk,
            name=tool_name,
            description=str(definition["description"]),
            schema=dict(definition["schema"]),
        )
        return decorator(handler)

    def _build_options(
        self,
        sdk: ClaudeSdk,
        context: AgentExecutionContext,
        server: Any,
        cli_stderr: list[str],
    ) -> Any:
        return sdk.options(
            model=context.model or self.model,
            system_prompt=_build_system_prompt(context),
            mcp_servers={"internal": server},
            allowed_tools=["mcp__internal__*"],
            permission_mode="dontAsk",
            max_turns=context.max_turns or self.limits.max_turns,
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
        if _looks_max_turns_exhausted(message):
            raise DiagnosticLoopExhausted(
                message,
                safe_message=_safe_sdk_error_message("Claude runtime failed", message),
                tool_events=tool_events,
                error_code="max_turns_exhausted",
            ) from exc
        if name in {"CLINotFoundError", "CLIConnectionError"}:
            raise NonRetryableExecutionError(
                message,
                safe_message=_safe_sdk_error_message(
                    "Claude Code CLI runtime is not available", message
                ),
                tool_events=tool_events,
                error_code="claude_cli_unavailable",
            ) from exc
        if name in {"ProcessError", "CLIJSONDecodeError"} or _looks_transient(message):
            raise RetryableExecutionError(
                message,
                safe_message=_safe_sdk_error_message(
                    "Claude runtime failed with a transient error", message
                ),
                tool_events=tool_events,
                error_code="claude_transient_error",
            ) from exc
        raise RetryableExecutionError(
            message,
            safe_message=_safe_sdk_error_message("Claude runtime failed", message),
            tool_events=tool_events,
            error_code="claude_runtime_error",
        ) from exc


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
    )


def is_claude_cli_available() -> bool:
    return shutil.which("claude") is not None or shutil.which("claude-code") is not None


def _tool_decorator(
    sdk: ClaudeSdk,
    *,
    name: str,
    description: str,
    schema: dict[str, Any],
) -> Any:
    annotations = _read_only_annotations(sdk)
    if annotations is None:
        return sdk.tool(name, description, schema)
    try:
        return sdk.tool(name, description, schema, annotations=annotations)
    except TypeError:
        return sdk.tool(name, description, schema)


def _read_only_annotations(sdk: ClaudeSdk) -> Any | None:
    if sdk.tool_annotations is None:
        return {"readOnlyHint": True}
    for kwargs in ({"readOnlyHint": True}, {"read_only_hint": True}):
        try:
            return sdk.tool_annotations(**kwargs)
        except TypeError:
            continue
    return {"readOnlyHint": True}


def _build_system_prompt(context: AgentExecutionContext) -> str:
    skill_sections = "\n\n".join(
        f"## Skill: {name}\n{body}" for name, body in sorted(context.skills.items())
    )
    retrieved_context = json.dumps(context.retrieved_context, ensure_ascii=False, default=str)
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
            "Report structure:\n"
            + _numbered(
                [
                    "Conclusion with likely root cause.",
                    "Evidence summary citing tool results.",
                    "Uncertainty or limitations when evidence is incomplete.",
                    "Suggested safe next actions only; do not suggest direct mutation by the Agent.",
                ]
            ),
            "Retrieved context:\n" + retrieved_context,
            "Conversation summary:\n" + context.conversation_summary,
            "Diagnostic skills:\n" + skill_sections,
        ]
    )


def _numbered(items: list[str]) -> str:
    return "\n".join(f"{index}. {item}" for index, item in enumerate(items, start=1))


def _sdk_tool_response(payload: Any) -> dict[str, list[dict[str, str]]]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, ensure_ascii=False, default=str),
            }
        ]
    }


def _tool_event_from_result(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    result: ToolResult,
    status: str,
    duration_ms: int,
    limits: ExecutionSettings,
) -> dict[str, Any]:
    return {
        "tool_name": tool_name,
        "request_payload": _bounded_payload(arguments, limits.max_tool_response_chars),
        "response_summary": _bounded_payload(result.summary, limits.max_tool_response_chars),
        "status": status,
        "duration_ms": duration_ms,
        "risk_level": _risk_level(tool_name),
    }


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


def _extract_tool_events(message: Any, limits: ExecutionSettings) -> list[dict[str, Any]]:
    events = []
    for block in _content_blocks(message):
        block_type = _value(block, "type")
        if block_type not in {"tool_use", "tool_result"}:
            continue
        tool_name = str(_value(block, "name") or _value(block, "tool_name") or "unknown")
        status = "SUCCEEDED" if block_type == "tool_result" else "STARTED"
        request_payload = _value(block, "input") or {}
        response = _value(block, "content") or _value(block, "result") or {}
        events.append(
            {
                "tool_name": tool_name,
                "request_payload": _bounded_payload(
                    request_payload, limits.max_tool_response_chars
                ),
                "response_summary": _bounded_payload(response, limits.max_tool_response_chars),
                "status": status,
                "duration_ms": 0,
                "risk_level": _risk_level(tool_name),
            }
        )
    return events


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
    )
    redacted = text
    for pattern, replacement in patterns:
        redacted = re.sub(pattern, replacement, redacted)
    return redacted


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


@contextmanager
def _temporary_claude_env(api_key: str, base_url: str) -> Iterator[None]:
    previous_key = os.environ.get("ANTHROPIC_API_KEY")
    previous_auth_token = os.environ.get("ANTHROPIC_AUTH_TOKEN")
    previous_base_url = os.environ.get("ANTHROPIC_BASE_URL")
    os.environ["ANTHROPIC_API_KEY"] = api_key
    os.environ["ANTHROPIC_AUTH_TOKEN"] = api_key
    if base_url:
        os.environ["ANTHROPIC_BASE_URL"] = base_url
    try:
        yield
    finally:
        _restore_env("ANTHROPIC_API_KEY", previous_key)
        _restore_env("ANTHROPIC_AUTH_TOKEN", previous_auth_token)
        _restore_env("ANTHROPIC_BASE_URL", previous_base_url)


def _restore_env(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value
