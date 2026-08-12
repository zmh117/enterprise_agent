from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from app.modules.agent.infrastructure.generated_runtime_contracts import validate_contract
from app.shared.database import Database

from .sdk_executor import PythonExecutionOutcome


class InvocationSecretContextPort(Protocol):
    @property
    def principal_token(self) -> str: ...


class PythonRuntimeExecutor(Protocol):
    def execute(
        self,
        request: dict[str, Any],
        cancel_event: threading.Event,
        secret_context: InvocationSecretContextPort,
    ) -> PythonExecutionOutcome: ...


@dataclass(frozen=True)
class InvocationSecretContext:
    principal_token: str = ""

    def __repr__(self) -> str:
        return "InvocationSecretContext(principal_token=<hidden>)"


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

    def load(self, invocation_id: str) -> PersistedTerminal | None:
        now = datetime.now(UTC).isoformat()
        self.database.execute(
            "delete from agent_runtime_terminal_ledger where expires_at < ?",
            (now,),
        )
        row = self.database.execute_one(
            """
            select request_digest, events_json
              from agent_runtime_terminal_ledger
             where invocation_id = ? and expires_at >= ?
            """,
            (invocation_id, now),
        )
        if not row:
            return None
        try:
            raw_events = json.loads(str(row["events_json"]))
            if not isinstance(raw_events, list) or not raw_events:
                raise ValueError("empty terminal ledger")
            events = tuple(dict(item) for item in raw_events)
            for event in events:
                validate_contract("RuntimeEvent", event)
            if events[-1]["event_type"] != "terminal":
                raise ValueError("terminal event missing")
        except (TypeError, ValueError) as exc:
            raise TerminalLedgerConflictError("Persisted terminal is invalid") from exc
        return PersistedTerminal(
            request_digest=str(row["request_digest"]),
            events=events,
        )

    def claim(self, request: dict[str, Any], owner_instance_id: str) -> PersistedClaim:
        now = datetime.now(UTC)
        self.database.execute(
            "delete from agent_runtime_invocation_claim where expires_at < ?",
            (now.isoformat(),),
        )
        self.database.execute(
            """
            insert into agent_runtime_invocation_claim
              (invocation_id, request_digest, runtime_kind, owner_instance_id,
               claimed_at, expires_at)
            values (?, ?, ?, ?, ?, ?)
            on conflict(invocation_id) do nothing
            """,
            (
                request["invocation_id"],
                request["request_digest"],
                request["runtime_kind"],
                owner_instance_id,
                now.isoformat(),
                (now + timedelta(seconds=self.ttl_seconds)).isoformat(),
            ),
        )
        persisted = self.database.execute_one(
            """
            select request_digest, runtime_kind, owner_instance_id
              from agent_runtime_invocation_claim
             where invocation_id = ?
            """,
            (request["invocation_id"],),
        )
        if (
            not persisted
            or persisted["request_digest"] != request["request_digest"]
            or persisted["runtime_kind"] != request["runtime_kind"]
        ):
            raise TerminalLedgerConflictError("Persisted invocation claim conflicts")
        rows = self.database.execute(
            """
            select request_digest, sequence, event_json
              from agent_runtime_invocation_event
             where invocation_id = ?
             order by sequence
            """,
            (request["invocation_id"],),
        )
        events: list[dict[str, Any]] = []
        try:
            for index, row in enumerate(rows, start=1):
                event = json.loads(str(row["event_json"]))
                validate_contract("RuntimeEvent", event)
                if (
                    row["request_digest"] != request["request_digest"]
                    or int(row["sequence"]) != index
                    or event["event_type"] == "terminal"
                    or event["invocation_id"] != request["invocation_id"]
                    or event["request_digest"] != request["request_digest"]
                    or int(event["sequence"]) != index
                ):
                    raise ValueError("Invocation event prefix conflicts")
                events.append(dict(event))
        except (TypeError, ValueError) as exc:
            raise TerminalLedgerConflictError(
                "Persisted invocation event prefix conflicts"
            ) from exc
        return PersistedClaim(
            status=(
                "CLAIMED" if persisted["owner_instance_id"] == owner_instance_id else "ORPHANED"
            ),
            events=tuple(events),
        )

    def append(self, request: dict[str, Any], event: dict[str, Any]) -> None:
        validate_contract("RuntimeEvent", event)
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
        if not events or events[-1]["event_type"] != "terminal":
            raise TerminalLedgerConflictError("Terminal event missing")
        for event in events:
            validate_contract("RuntimeEvent", event)
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
        self.database.execute(
            """
            delete from agent_runtime_invocation_claim
             where invocation_id = ? and request_digest = ?
            """,
            (request["invocation_id"], request["request_digest"]),
        )
        self.database.execute(
            """
            delete from agent_runtime_invocation_event
             where invocation_id = ? and request_digest = ?
            """,
            (request["invocation_id"], request["request_digest"]),
        )


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
                "protocol_version": "1.0",
                "invocation_id": self.request["invocation_id"],
                "request_digest": self.request["request_digest"],
                "sequence": sequence,
                "event_type": event_type,
                "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "payload": payload,
            }
            validate_contract("RuntimeEvent", event)
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
                while offset >= len(self._events) and not self._terminal:
                    self._condition.wait(timeout=1.0)
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
    ) -> None:
        self._executor = executor
        self._ledger = ledger
        self._owner_instance_id = owner_instance_id or str(uuid.uuid4())
        self._invocations: dict[str, RuntimeInvocation] = {}
        self._lock = threading.Lock()

    def acquire(
        self,
        request: dict[str, Any],
        secret_context: InvocationSecretContext | None = None,
    ) -> RuntimeInvocation:
        invocation_id = str(request["invocation_id"])
        with self._lock:
            existing = self._invocations.get(invocation_id)
            if existing:
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
                self._invocations[invocation_id] = invocation
                return invocation
            claim = self._ledger.claim(request, self._owner_instance_id)
            if claim.status == "ORPHANED":
                invocation = RuntimeInvocation(
                    request,
                    secret_context=secret_context,
                    persisted_events=claim.events,
                )
                self._invocations[invocation_id] = invocation
                self._fail_orphaned(invocation)
                return invocation
            invocation = RuntimeInvocation(request, secret_context=secret_context)
            self._invocations[invocation_id] = invocation
            threading.Thread(
                target=self._run,
                args=(invocation,),
                name=f"python-runtime-{invocation_id[:48]}",
                daemon=True,
            ).start()
            return invocation

    def _fail_orphaned(self, invocation: RuntimeInvocation) -> None:
        request = invocation.request
        terminal = {
            "protocol_version": "1.0",
            "invocation_id": request["invocation_id"],
            "request_digest": request["request_digest"],
            "last_sequence": 1,
            "status": "FAILED",
            "failure": {
                "code": "runtime_orphaned_invocation",
                "retry_class": "NEVER",
                "safe_message": ("Agent Runtime 在执行中重启；为避免重复模型调用，本次执行已失败"),
            },
            "usage": {"input_tokens": 0, "output_tokens": 0},
            "runtime_provenance": _fallback_provenance(request),
        }
        invocation.commit_event(invocation.prepare_event("terminal", terminal))
        self._ledger.save(request, invocation.events())
        invocation.mark_persisted()

    def get(self, invocation_id: str) -> RuntimeInvocation | None:
        with self._lock:
            return self._invocations.get(invocation_id)

    def _run(self, invocation: RuntimeInvocation) -> None:
        request = invocation.request
        self._persist_and_emit(invocation, "execution_started", _fallback_provenance(request))
        try:
            outcome = self._executor.execute(
                request,
                invocation.cancel_event,
                invocation.secret_context,
            )
        except Exception:
            outcome = PythonExecutionOutcome(
                status="FAILED",
                usage={"input_tokens": 0, "output_tokens": 0},
                runtime_provenance=_fallback_provenance(request),
                failure={
                    "code": "runtime_internal_error",
                    "retry_class": "TRANSIENT",
                    "safe_message": "Python Agent Runtime 暂时不可用",
                },
            )
        for tool_event in outcome.tool_events:
            self._persist_and_emit(invocation, "tool_event", dict(tool_event))
        last_sequence = len(invocation.events()) + 1
        terminal = {
            "protocol_version": "1.0",
            "invocation_id": request["invocation_id"],
            "request_digest": request["request_digest"],
            "last_sequence": last_sequence,
            "status": outcome.status,
            "usage": outcome.usage,
            "runtime_provenance": outcome.runtime_provenance,
        }
        if outcome.status == "SUCCEEDED":
            terminal["final_answer"] = outcome.final_answer
        else:
            terminal["failure"] = outcome.failure or {
                "code": "runtime_internal_error",
                "retry_class": "TRANSIENT",
                "safe_message": "Python Agent Runtime 暂时不可用",
            }
        invocation.commit_event(invocation.prepare_event("terminal", terminal))
        self._ledger.save(request, invocation.events())
        invocation.mark_persisted()

    def _persist_and_emit(
        self,
        invocation: RuntimeInvocation,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        event = invocation.prepare_event(event_type, payload)
        self._ledger.append(invocation.request, event)
        invocation.commit_event(event)


def _fallback_provenance(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "runtime_kind": "python-v1",
        "runtime_version": "0.1.0",
        "protocol_version": "1.0",
        "sdk_version": "0.2.134",
        "cli_version": "2.1.226",
        "model_connection_revision_id": request["model_connection"]["revision_id"],
        "model_connection_config_hash": request["model_connection"]["config_hash"],
    }
