from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, cast

from app.shared.config import ExecutionSettings
from app.shared.exceptions import NonRetryableExecutionError

EXECUTION_POLICY_SCHEMA_VERSION = 1
MAX_TURNS_RANGE = (1, 100)
TIMEOUT_SECONDS_RANGE = (10, 3600)
MAX_TOOL_CALLS_RANGE = (0, 200)


@dataclass(frozen=True)
class ExecutionPolicyValues:
    max_turns: int
    timeout_seconds: int
    max_tool_calls: int

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, field: str) -> ExecutionPolicyValues:
        if not isinstance(value, Mapping):
            raise _invalid(f"{field} must be an object")
        raw_values = {
            key: value.get(key) for key in ("max_turns", "timeout_seconds", "max_tool_calls")
        }
        if any(type(item) is not int for item in raw_values.values()):
            raise _invalid(f"{field} is missing required strict integer fields")
        result = cls(
            max_turns=cast(int, raw_values["max_turns"]),
            timeout_seconds=cast(int, raw_values["timeout_seconds"]),
            max_tool_calls=cast(int, raw_values["max_tool_calls"]),
        )
        result.validate(field=field)
        return result

    def validate(self, *, field: str) -> None:
        _validate_range(f"{field}.max_turns", self.max_turns, MAX_TURNS_RANGE)
        _validate_range(
            f"{field}.timeout_seconds",
            self.timeout_seconds,
            TIMEOUT_SECONDS_RANGE,
        )
        _validate_range(
            f"{field}.max_tool_calls",
            self.max_tool_calls,
            MAX_TOOL_CALLS_RANGE,
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "max_turns": self.max_turns,
            "timeout_seconds": self.timeout_seconds,
            "max_tool_calls": self.max_tool_calls,
        }


@dataclass(frozen=True)
class JobExecutionPolicySnapshot:
    requested: ExecutionPolicyValues
    effective: ExecutionPolicyValues
    sources: dict[str, str]
    schema_version: int = EXECUTION_POLICY_SCHEMA_VERSION

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> JobExecutionPolicySnapshot:
        if not isinstance(value, Mapping) or not value:
            raise _invalid("execution policy snapshot is required")
        schema_version = value.get("schema_version")
        if type(schema_version) is not int:
            raise _invalid("execution policy schema_version must be an integer")
        if schema_version != EXECUTION_POLICY_SCHEMA_VERSION:
            raise _invalid(f"unsupported execution policy schema_version: {schema_version}")
        requested = ExecutionPolicyValues.from_mapping(
            _mapping(value.get("requested")),
            field="requested",
        )
        effective = ExecutionPolicyValues.from_mapping(
            _mapping(value.get("effective")),
            field="effective",
        )
        sources_value = _mapping(value.get("sources"))
        source_kind = str(sources_value.get("source_kind") or "").strip()
        if source_kind not in {
            "business_application",
            "agent_publication",
            "runtime_default",
        }:
            raise _invalid("execution policy sources.source_kind is invalid")
        sources = {
            str(key): str(item)
            for key, item in sources_value.items()
            if isinstance(key, str) and item is not None
        }
        _validate_sources(source_kind, sources)
        if effective.max_turns > requested.max_turns:
            raise _invalid("effective.max_turns cannot exceed requested.max_turns")
        if effective.timeout_seconds > requested.timeout_seconds:
            raise _invalid("effective.timeout_seconds cannot exceed requested.timeout_seconds")
        if effective.max_tool_calls != requested.max_tool_calls:
            raise _invalid("effective.max_tool_calls must equal requested.max_tool_calls")
        return cls(
            requested=requested,
            effective=effective,
            sources=sources,
            schema_version=schema_version,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "requested": self.requested.to_dict(),
            "effective": self.effective.to_dict(),
            "sources": dict(self.sources),
        }


class EffectiveExecutionPolicyResolver:
    def __init__(self, defaults: ExecutionSettings) -> None:
        self.defaults = defaults

    def resolve(
        self,
        *,
        application_policy: Mapping[str, Any] | None,
        agent_snapshot: Mapping[str, Any] | None,
        sources: Mapping[str, Any] | None = None,
    ) -> JobExecutionPolicySnapshot:
        agent_execution = _mapping(_mapping(agent_snapshot).get("execution"))
        agent_values = ExecutionPolicyValues(
            max_turns=_bounded_or_default(
                agent_execution.get("max_turns"),
                self.defaults.max_turns,
                MAX_TURNS_RANGE,
            ),
            timeout_seconds=_bounded_or_default(
                agent_execution.get("timeout_seconds"),
                self.defaults.timeout_seconds,
                TIMEOUT_SECONDS_RANGE,
            ),
            max_tool_calls=self.defaults.max_tool_calls,
        )
        if application_policy:
            requested = ExecutionPolicyValues.from_mapping(
                application_policy,
                field="requested",
            )
            effective = ExecutionPolicyValues(
                max_turns=min(requested.max_turns, agent_values.max_turns),
                timeout_seconds=min(
                    requested.timeout_seconds,
                    agent_values.timeout_seconds,
                ),
                max_tool_calls=requested.max_tool_calls,
            )
            source_kind = "business_application"
        else:
            requested = agent_values
            effective = agent_values
            source_kind = "agent_publication" if _mapping(agent_snapshot) else "runtime_default"
        normalized_sources = {
            "source_kind": source_kind,
            **{
                str(key): str(item)
                for key, item in _mapping(sources).items()
                if isinstance(key, str) and item is not None and str(item)
            },
        }
        return JobExecutionPolicySnapshot(
            requested=requested,
            effective=effective,
            sources=normalized_sources,
        )


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _bounded_or_default(value: Any, default: int, bounds: tuple[int, int]) -> int:
    if value is None or value == "":
        result = int(default)
    else:
        try:
            result = int(value)
        except (TypeError, ValueError) as exc:
            raise _invalid("agent execution policy contains a non-integer value") from exc
    _validate_range("agent_execution", result, bounds)
    return result


def _validate_range(field: str, value: int, bounds: tuple[int, int]) -> None:
    minimum, maximum = bounds
    if not minimum <= value <= maximum:
        raise _invalid(f"{field} must be between {minimum} and {maximum}")


def _validate_sources(source_kind: str, sources: Mapping[str, str]) -> None:
    required = {
        "business_application": (
            "business_application_publication_id",
            "business_application_config_hash",
            "agent_publication_id",
            "agent_config_hash",
        ),
        "agent_publication": (
            "agent_publication_id",
            "agent_config_hash",
        ),
        "runtime_default": (),
    }[source_kind]
    missing = [key for key in required if not str(sources.get(key) or "")]
    if missing:
        raise _invalid("execution policy sources are missing: " + ", ".join(missing))


def _invalid(message: str) -> NonRetryableExecutionError:
    return NonRetryableExecutionError(
        message,
        safe_message="Agent 执行策略配置无效",
        error_code="execution_policy_integrity_error",
    )
