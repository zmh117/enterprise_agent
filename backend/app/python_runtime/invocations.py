from __future__ import annotations

import json
import time
import threading
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any, Callable, Protocol

from app.modules.agent.infrastructure.runtime_protocol import validate_runtime_contract
from app.shared.build_identity import BuildIdentity, build_identity_from_environment
from app.shared.database import Database

from app.modules.agent.infrastructure.runtime_pool_store import (
    RuntimePoolStore,
    RuntimePoolError,
    database_now,
    timestamp,
)

from .execution_slot import ExecutionSlot, ExecutionWatchdog
from .claude_client import claude_cli_version, claude_sdk_version
from .executor import PythonExecutionOutcome, agent_request_from_runtime_request
from .run_audit import encode_audit_chunks
from .tool_contract import build_tool_contract_observation


class InvocationSecretContextPort(Protocol):
    @property
    def mcp_principal_tokens(self) -> Mapping[str, str]: ...

    @property
    def file_principal_token(self) -> str: ...


class PythonRuntimeExecutor(Protocol):
    def execute(
        self,
        request: dict[str, Any],
        cancel_event: threading.Event,
        secret_context: InvocationSecretContextPort,
        tool_contract_observer: Callable[[dict[str, Any]], None] | None = None,
    ) -> PythonExecutionOutcome: ...


@dataclass(frozen=True)
class InvocationSecretContext:
    mcp_principal_tokens: Mapping[str, str] = field(default_factory=dict, repr=False)
    file_principal_token: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "mcp_principal_tokens",
            MappingProxyType(dict(self.mcp_principal_tokens)),
        )

    def __repr__(self) -> str:
        return "InvocationSecretContext(principal_tokens=<hidden>)"


class InvocationConflictError(RuntimeError):
    code = "runtime_invocation_conflict"


class TerminalLedgerConflictError(RuntimeError):
    code = "runtime_terminal_ledger_conflict"


@dataclass(frozen=True)
class PersistedTerminal:
    request_digest: str
    events: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class PersistedClaim:
    status: str
    events: tuple[dict[str, Any], ...]


class PythonTerminalLedger:
    def __init__(
        self,
        database: Database,
        *,
        ttl_seconds: int = 3600,
    ) -> None:
        self.database = database
        self.ttl_seconds = ttl_seconds
        self.pool = RuntimePoolStore(database)
        self.node_id = ""
        self.instance_id = ""

    def load(self, invocation_id: str) -> PersistedTerminal | None:
        row = self.database.execute_one(
            "select request_digest, events_json from agent_runtime_terminal_ledger "
            "where invocation_id = ?",
            (invocation_id,),
        )
        if not row:
            return None
        try:
            raw_events = json.loads(str(row["events_json"]))
            if not isinstance(raw_events, list) or not raw_events:
                raise ValueError("empty terminal ledger")
            events = tuple(dict(item) for item in raw_events)
            for event in events:
                validate_runtime_contract("RuntimeEvent", event)
            if events[-1]["event_type"] != "terminal":
                raise ValueError("terminal event missing")
        except (TypeError, ValueError) as exc:
            raise TerminalLedgerConflictError("Persisted terminal is invalid") from exc
        return PersistedTerminal(
            request_digest=str(row["request_digest"]),
            events=events,
        )

    def append(self, request: dict[str, Any], event: dict[str, Any]) -> None:
        with self.database.unit_of_work():
            self.pool.require_owner(
                request["invocation_id"],
                request["request_digest"],
                self.node_id,
                self.instance_id,
            )
            self._append(request, event)

    def _append(self, request: dict[str, Any], event: dict[str, Any]) -> None:
        validate_runtime_contract("RuntimeEvent", event)
        if (
            event["event_type"] == "terminal"
            or event["invocation_id"] != request["invocation_id"]
            or event["request_digest"] != request["request_digest"]
        ):
            raise TerminalLedgerConflictError("Invocation event conflicts")
        now = datetime.now(UTC)
        encoded = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        self.database.execute(
            """
            insert into agent_runtime_invocation_event
              (invocation_id, request_digest, sequence, event_json,
               created_at, expires_at)
            values (?, ?, ?, ?, ?, ?)
            on conflict(invocation_id, sequence) do nothing
            """,
            (
                request["invocation_id"],
                request["request_digest"],
                event["sequence"],
                encoded,
                now.isoformat(),
                (now + timedelta(seconds=self.ttl_seconds)).isoformat(),
            ),
        )
        persisted = self.database.execute_one(
            """
            select request_digest, event_json
              from agent_runtime_invocation_event
             where invocation_id = ? and sequence = ?
            """,
            (request["invocation_id"], event["sequence"]),
        )
        if (
            not persisted
            or persisted["request_digest"] != request["request_digest"]
            or persisted["event_json"] != encoded
        ):
            raise TerminalLedgerConflictError("Persisted invocation event conflicts")

    def save(self, request: dict[str, Any], events: tuple[dict[str, Any], ...]) -> None:
        with self.database.unit_of_work():
            terminal = events[-1]["payload"]
            code = str(terminal.get("failure", {}).get("code") or "runtime_succeeded")
            self.pool.finish(
                request["invocation_id"],
                request["request_digest"],
                self.node_id,
                self.instance_id,
                code,
            )
            self._save(request, events)

    def _save(self, request: dict[str, Any], events: tuple[dict[str, Any], ...]) -> None:
        if not events or events[-1]["event_type"] != "terminal":
            raise TerminalLedgerConflictError("Terminal event missing")
        for event in events:
            validate_runtime_contract("RuntimeEvent", event)
        now = datetime.now(UTC)
        encoded = json.dumps(events, ensure_ascii=False, separators=(",", ":"))
        self.database.execute(
            """
            insert into agent_runtime_terminal_ledger
              (invocation_id, request_digest, events_json, terminal_at, expires_at)
            values (?, ?, ?, ?, ?)
            on conflict(invocation_id) do nothing
            """,
            (
                request["invocation_id"],
                request["request_digest"],
                encoded,
                now.isoformat(),
                (now + timedelta(seconds=self.ttl_seconds)).isoformat(),
            ),
        )
        persisted = self.database.execute_one(
            """
            select request_digest, events_json
              from agent_runtime_terminal_ledger
             where invocation_id = ?
            """,
            (request["invocation_id"],),
        )
        if (
            not persisted
            or persisted["request_digest"] != request["request_digest"]
            or persisted["events_json"] != encoded
        ):
            raise TerminalLedgerConflictError("Persisted terminal conflicts")


class RuntimeInvocation:
    def __init__(
        self,
        request: dict[str, Any],
        *,
        secret_context: InvocationSecretContext | None = None,
        persisted_events: tuple[dict[str, Any], ...] = (),
    ) -> None:
        self.request = request
        self.secret_context = secret_context or InvocationSecretContext()
        self.cancel_event = threading.Event()
        self._events = list(persisted_events)
        self._terminal = bool(
            persisted_events and persisted_events[-1].get("event_type") == "terminal"
        )
        self._persisted = self._terminal
        self._stream_failed = False
        self._condition = threading.Condition()

    @property
    def is_terminal(self) -> bool:
        with self._condition:
            return self._terminal

    def prepare_event(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._condition:
            if self._terminal:
                raise InvocationConflictError("Invocation already reached terminal")
            sequence = len(self._events) + 1
            event = {
                "protocol_version": self.request["protocol_version"],
                "invocation_id": self.request["invocation_id"],
                "request_digest": self.request["request_digest"],
                "sequence": sequence,
                "event_type": event_type,
                "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "payload": payload,
            }
            validate_runtime_contract("RuntimeEvent", event)
            return event

    def commit_event(self, event: dict[str, Any]) -> None:
        with self._condition:
            if self._terminal or int(event["sequence"]) != len(self._events) + 1:
                raise InvocationConflictError("Invocation event sequence conflict")
            self._events.append(event)
            self._terminal = event["event_type"] == "terminal"
            self._condition.notify_all()

    def cancel(self) -> bool:
        with self._condition:
            if self._terminal:
                return False
            self.cancel_event.set()
            self._condition.notify_all()
            return True

    def mark_persisted(self) -> None:
        with self._condition:
            self._persisted = True
            self._condition.notify_all()

    def fail_stream(self) -> None:
        with self._condition:
            self._stream_failed = True
            self._condition.notify_all()

    def events(self) -> tuple[dict[str, Any], ...]:
        with self._condition:
            return tuple(self._events)

    def terminal(self) -> dict[str, Any] | None:
        with self._condition:
            if not self._terminal:
                return None
            return dict(self._events[-1]["payload"])

    def stream(self) -> Iterator[dict[str, Any]]:
        offset = 0
        while True:
            with self._condition:
                while (
                    offset >= len(self._events) and not self._terminal and not self._stream_failed
                ):
                    self._condition.wait(timeout=1.0)
                if self._stream_failed:
                    raise RuntimePoolError("runtime_pool_unavailable", status=503)
                while self._terminal and not self._persisted:
                    self._condition.wait(timeout=1.0)
                pending = self._events[offset:]
                terminal = self._terminal
            for event in pending:
                offset += 1
                yield dict(event)
            if terminal and offset >= len(self._events):
                return


class PythonInvocationRegistry:
    def __init__(
        self,
        executor: PythonRuntimeExecutor,
        ledger: PythonTerminalLedger,
        *,
        owner_instance_id: str | None = None,
        node_id: str = "runtime-local",
    ) -> None:
        self._executor = executor
        self._ledger = ledger
        self._owner_instance_id = owner_instance_id or str(uuid.uuid4())
        self.node_id = node_id
        self.instance_id = self._owner_instance_id
        self.slot = ExecutionSlot()
        self._ledger.node_id = node_id
        self._ledger.instance_id = self.instance_id
        self.pool = ledger.pool
        self._invocations: dict[str, RuntimeInvocation] = {}
        self._lock = threading.Lock()

    def acquire(
        self,
        request: dict[str, Any],
        secret_context: InvocationSecretContext | None = None,
    ) -> RuntimeInvocation:
        invocation_id = str(request["invocation_id"])
        with self._lock:
            row = self.pool.require(invocation_id, request["request_digest"])
            existing = self._invocations.get(invocation_id)
            if existing and row["state"] == "RUNNING":
                if existing.request["request_digest"] != request["request_digest"]:
                    raise InvocationConflictError("Invocation digest conflict")
                return existing
            persisted = self._ledger.load(invocation_id)
            if persisted:
                if persisted.request_digest != request["request_digest"]:
                    raise InvocationConflictError("Invocation digest conflict")
                invocation = RuntimeInvocation(
                    request,
                    secret_context=secret_context,
                    persisted_events=persisted.events,
                )
                return invocation
            if row["state"] == "TERMINAL":
                if row["terminal_code"] in {
                    "runtime_cancelled",
                    "runtime_admission_timeout",
                    "runtime_invocation_outcome_unknown",
                }:
                    raise RuntimePoolError(str(row["terminal_code"]))
                raise RuntimePoolError("runtime_recovery_expired", status=410)
            if row["state"] == "RUNNING":
                raise RuntimePoolError("runtime_invocation_owner_mismatch")
            self.slot.acquire()
            try:
                if not self.pool.admit(
                    invocation_id, request["request_digest"], self.node_id, self.instance_id
                ):
                    raise RuntimePoolError("runtime_invocation_owner_mismatch")
                invocation = RuntimeInvocation(request, secret_context=secret_context)
                self._invocations[invocation_id] = invocation
                threading.Thread(
                    target=self._run_owned,
                    args=(invocation,),
                    name=f"python-runtime-{invocation_id[:48]}",
                    daemon=True,
                ).start()
            except BaseException:
                self.slot.release()
                raise
            return invocation

    def recover(self, invocation_id: str, digest: str) -> RuntimeInvocation:
        row = self.pool.require(invocation_id, digest)
        existing = self.get(invocation_id)
        if existing and row["state"] == "RUNNING":
            return existing
        persisted = self._ledger.load(invocation_id)
        if persisted:
            # Only binding metadata is needed for replay; no credentials or
            # current business context are reconstructed.
            return RuntimeInvocation(
                self.pool.grant_binding(row), persisted_events=persisted.events
            )
        if row["state"] == "TERMINAL":
            raise RuntimePoolError("runtime_recovery_expired", status=410)
        raise RuntimePoolError("runtime_invocation_owner_mismatch")

    def _run_owned(self, invocation: RuntimeInvocation) -> None:
        request = invocation.request
        watchdog = ExecutionWatchdog(
            invocation.cancel_event,
            lambda: self.pool.renew(
                request["invocation_id"], request["request_digest"], self.node_id, self.instance_id
            ),
            remaining_seconds=float(request["limits"]["timeout_seconds"]),
        )
        watchdog.start()
        try:
            row = self.pool.require(request["invocation_id"], request["request_digest"])
            remaining = (
                datetime.fromisoformat(row["execution_deadline_at"])
                - database_now(self.pool.database)
            ).total_seconds()
            watchdog.deadline = min(watchdog.deadline, time.monotonic() + max(0.0, remaining))
            self._run(invocation)
        except Exception:
            invocation.fail_stream()
        finally:
            watchdog.stopped.set()
            # _run returns only after the synchronous SDK wrapper and its
            # subprocess cleanup returned. An unresponsive SDK is contained by
            # the independent watchdog, never by releasing this semaphore.
            try:
                self.pool.quiesce(request["invocation_id"], self.node_id, self.instance_id)
            except Exception:
                # SDK cleanup finished but stop evidence cannot commit. Fail
                # closed; a fresh fixed-node instance will prove containment.
                self.slot.draining = True
                invocation.fail_stream()
                watchdog.terminate(70)
                return
            self.slot.release()
            with self._lock:
                self._invocations.pop(request["invocation_id"], None)

    def get(self, invocation_id: str) -> RuntimeInvocation | None:
        with self._lock:
            return self._invocations.get(invocation_id)

    def _run(self, invocation: RuntimeInvocation) -> None:
        request = invocation.request
        self._persist_and_emit(
            invocation,
            "execution_started",
            _fallback_provenance(request, self._runtime_build_identity()),
        )
        observed_tool_contract: dict[str, Any] | None = None

        def observe_tool_contract(payload: dict[str, Any]) -> None:
            nonlocal observed_tool_contract
            if observed_tool_contract is not None:
                raise InvocationConflictError("Tool contract was observed more than once")
            observed_tool_contract = dict(payload)
            self._persist_and_emit(
                invocation,
                "tool_contract_observed",
                observed_tool_contract,
            )

        try:
            outcome = self._executor.execute(
                request,
                invocation.cancel_event,
                invocation.secret_context,
                observe_tool_contract,
            )
        except Exception:
            outcome = PythonExecutionOutcome(
                status="FAILED",
                usage={"input_tokens": 0, "output_tokens": 0},
                runtime_provenance=_fallback_provenance(
                    request,
                    self._runtime_build_identity(),
                ),
                failure={
                    "code": "runtime_internal_error",
                    "retry_class": "TRANSIENT",
                    "safe_message": "Python Agent Runtime 暂时不可用",
                },
            )
        self.pool.quiesce(request["invocation_id"], self.node_id, self.instance_id)
        if observed_tool_contract is None:
            observation = (
                dict(outcome.tool_contract_observation)
                if outcome.tool_contract_observation
                else self._fallback_tool_contract_observation(request)
            )
            observe_tool_contract(observation)
        elif (
            outcome.tool_contract_observation
            and dict(outcome.tool_contract_observation) != observed_tool_contract
        ):
            outcome = PythonExecutionOutcome(
                status="FAILED",
                usage={"input_tokens": 0, "output_tokens": 0},
                runtime_provenance=_fallback_provenance(
                    request,
                    self._runtime_build_identity(),
                ),
                failure={
                    "code": "runtime_tool_contract_observation_invalid",
                    "retry_class": "NEVER",
                    "safe_message": "Runtime 工具契约观测不一致",
                },
                tool_contract_observation=observed_tool_contract,
            )
        for runtime_event in outcome.runtime_events:
            event_type = str(runtime_event.get("event_type") or "")
            payload = runtime_event.get("payload")
            if event_type not in {"runtime_initialized", "model_call", "api_retry"}:
                continue
            if not isinstance(payload, dict):
                continue
            self._persist_and_emit(invocation, event_type, dict(payload))
        for tool_event in outcome.tool_events:
            self._persist_and_emit(invocation, "tool_event", dict(tool_event))
        audit_sha256 = ""
        audit_chunk_count = 0
        if request["protocol_version"] == "1.5" and outcome.run_audit:
            audit_sha256, audit_chunks = encode_audit_chunks(outcome.run_audit)
            if len(invocation.events()) + len(audit_chunks) + 1 > 2048:
                raise InvocationConflictError(
                    "Complete Agent run audit exceeds the Runtime event boundary"
                )
            for audit_chunk in audit_chunks:
                self._persist_and_emit(invocation, "audit_chunk", audit_chunk)
            audit_chunk_count = len(audit_chunks)
        last_sequence = len(invocation.events()) + 1
        terminal = {
            "protocol_version": request["protocol_version"],
            "invocation_id": request["invocation_id"],
            "request_digest": request["request_digest"],
            "last_sequence": last_sequence,
            "status": outcome.status,
            "usage": _usage_for_protocol(request, outcome.usage),
            "accounting": outcome.accounting or _unavailable_accounting(),
            "runtime_provenance": outcome.runtime_provenance,
        }
        if audit_sha256:
            terminal["audit_sha256"] = audit_sha256
            terminal["audit_chunk_count"] = audit_chunk_count
        if outcome.status == "SUCCEEDED":
            terminal["final_answer"] = outcome.final_answer
        else:
            terminal["failure"] = outcome.failure or {
                "code": "runtime_internal_error",
                "retry_class": "TRANSIENT",
                "safe_message": "Python Agent Runtime 暂时不可用",
            }
        self._commit_terminal(invocation, terminal)

    def _commit_terminal(self, invocation: RuntimeInvocation, terminal: dict[str, Any]) -> None:
        request = invocation.request
        with self.pool.database.unit_of_work():
            row = self.pool.require(request["invocation_id"], request["request_digest"], lock=True)
            if row["cancel_requested_at"] is not None:
                terminal.pop("final_answer", None)
                terminal["status"] = "FAILED"
                terminal["failure"] = {
                    "code": "runtime_cancelled",
                    "retry_class": "NEVER",
                    "safe_message": "Agent 执行已取消",
                }
            elif row["execution_deadline_at"] <= timestamp(database_now(self.pool.database)):
                terminal.pop("final_answer", None)
                terminal["status"] = "TIMEOUT"
                terminal["failure"] = {
                    "code": "runtime_timeout",
                    "retry_class": "NEVER",
                    "safe_message": "Agent 执行超时",
                }
            event = invocation.prepare_event("terminal", terminal)
            self._ledger.save(request, (*invocation.events(), event))
        invocation.commit_event(event)
        invocation.mark_persisted()

    def _runtime_build_identity(self) -> BuildIdentity:
        value = getattr(self._executor, "build_identity", None)
        if isinstance(value, BuildIdentity):
            return value
        return build_identity_from_environment("python-runtime")

    def _fallback_tool_contract_observation(
        self,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        context = agent_request_from_runtime_request(request, None).context
        return build_tool_contract_observation(
            context,
            file_live=None,
            runtime_build_identity=self._runtime_build_identity(),
        )

    def _persist_and_emit(
        self,
        invocation: RuntimeInvocation,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        event = invocation.prepare_event(event_type, payload)
        self._ledger.append(invocation.request, event)
        invocation.commit_event(event)


def _fallback_provenance(
    request: dict[str, Any],
    runtime_build_identity: BuildIdentity,
) -> dict[str, Any]:
    return {
        "runtime_kind": "python-v1",
        "runtime_version": "0.1.0",
        "protocol_version": request["protocol_version"],
        "sdk_version": claude_sdk_version(),
        "cli_version": claude_cli_version(),
        "runtime_build_identity": runtime_build_identity.to_dict(),
        "model_connection_revision_id": request["model_connection"]["revision_id"],
        "model_connection_config_hash": request["model_connection"]["config_hash"],
    }


def _usage_for_protocol(
    request: dict[str, Any], usage: dict[str, int | None]
) -> dict[str, int | None]:
    return {
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
        "cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
    }


def _unavailable_accounting() -> dict[str, Any]:
    return {
        "status": "UNAVAILABLE",
        "duration_ms": None,
        "duration_api_ms": None,
        "num_turns": None,
        "usage": {
            "input_tokens": None,
            "output_tokens": None,
            "cache_read_input_tokens": None,
            "cache_creation_input_tokens": None,
        },
        "model_usage": [],
        "estimated_cost_usd": None,
        "permission_denials_count": 0,
    }
