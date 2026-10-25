"""Durable execution identity. No network calls and no business-result writes here."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from app.modules.agent.infrastructure.runtime_protocol import validate_execution_request
from app.shared.database import Database

LEASE_SECONDS = 30
RENEW_SECONDS = 5
ADMISSION_SECONDS = 3600


class RuntimePoolError(RuntimeError):
    def __init__(self, code: str, *, status: int = 409) -> None:
        super().__init__(code)
        self.code = code
        self.error_code = code
        self.safe_message = "Runtime 执行控制状态不允许此操作"
        self.status = status


def database_now(database: Database) -> datetime:
    # PostgreSQL's clock_timestamp, unlike current_timestamp, advances while a
    # transaction waits for a row lock. SQLite serializes its short transactions.
    sql = (
        "select clock_timestamp() as now"
        if database.engine == "postgres"
        else "select strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now') as now"
    )
    row = database.execute_one(sql)
    assert row is not None
    value = row["now"]
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return result.astimezone(UTC)


def timestamp(value: datetime) -> str:
    return value.isoformat(timespec="microseconds")


class RuntimePoolStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    def get(self, invocation_id: str, *, lock: bool = False) -> dict[str, Any] | None:
        suffix = " for update" if lock and self.database.engine == "postgres" else ""
        if lock and self.database.current_unit_of_work is None:
            raise RuntimeError("Invocation lock requires a transaction")
        return self.database.execute_one(
            "select * from agent_runtime_invocation where invocation_id = ?" + suffix,
            (invocation_id,),
        )

    def require(self, invocation_id: str, digest: str, *, lock: bool = False) -> dict[str, Any]:
        row = self.get(invocation_id, lock=lock)
        if row is None:
            raise RuntimePoolError("runtime_invocation_not_found", status=404)
        if row["request_digest"] != digest:
            raise RuntimePoolError("runtime_request_digest_mismatch")
        return row

    def prepare(self, request: dict[str, Any], *, attempt: int, admission_deadline_at: str) -> None:
        validate_execution_request(request)
        encoded = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self.database.unit_of_work():
            now = timestamp(database_now(self.database))
            self.database.execute(
                """
                insert into agent_runtime_invocation
                  (invocation_id, job_id, attempt, request_digest, protocol_version,
                   app_user_id, agent_publication_id, application_publication_id,
                   timeout_seconds, state, created_at, admission_deadline_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PREPARED', ?, ?)
                on conflict(invocation_id) do nothing
                """,
                (
                    request["invocation_id"],
                    request["job_id"],
                    attempt,
                    request["request_digest"],
                    request["protocol_version"],
                    request["app_user_id"],
                    request["agent_publication_id"],
                    request["application_publication_id"],
                    request["limits"]["timeout_seconds"],
                    now,
                    admission_deadline_at,
                ),
            )
            row = self.require(request["invocation_id"], request["request_digest"], lock=True)
            if row["state"] != "PREPARED":
                raise RuntimePoolError("runtime_invocation_already_admitted")
            self.database.execute(
                """
                insert into agent_runtime_request_snapshot
                  (invocation_id, request_digest, request_json, created_at)
                values (?, ?, ?, ?) on conflict(invocation_id) do nothing
                """,
                (request["invocation_id"], request["request_digest"], encoded, now),
            )
            if self.request(request["invocation_id"]) != request:
                raise RuntimePoolError("runtime_request_digest_mismatch")

    def request(self, invocation_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select request_json, request_digest from agent_runtime_request_snapshot "
            "where invocation_id = ?",
            (invocation_id,),
        )
        if row is None:
            raise RuntimePoolError("runtime_recovery_expired", status=410)
        request: dict[str, Any] = json.loads(str(row["request_json"]))
        validate_execution_request(request)
        self.require(invocation_id, str(request["request_digest"]))
        if (
            request["invocation_id"] != invocation_id
            or request["request_digest"] != row["request_digest"]
        ):
            raise RuntimePoolError("runtime_request_digest_mismatch")
        return request

    def admit(self, invocation_id: str, digest: str, node_id: str, instance_id: str) -> bool:
        with self.database.unit_of_work():
            row = self.require(invocation_id, digest, lock=True)
            now = database_now(self.database)
            if row["state"] != "PREPARED":
                return False
            if row["cancel_requested_at"] is not None:
                raise RuntimePoolError("runtime_cancel_requested")
            if row["admission_deadline_at"] <= timestamp(now):
                raise RuntimePoolError("runtime_admission_timeout")
            self.request(invocation_id)
            deadline = now + timedelta(seconds=int(row["timeout_seconds"]))
            self.database.execute(
                """
                update agent_runtime_invocation set state = 'RUNNING', node_id = ?,
                  instance_id = ?, accepted_at = ?, execution_deadline_at = ?, lease_until = ?
                where invocation_id = ? and state = 'PREPARED'
                """,
                (
                    node_id,
                    instance_id,
                    timestamp(now),
                    timestamp(deadline),
                    timestamp(now + timedelta(seconds=LEASE_SECONDS)),
                    invocation_id,
                ),
            )
            return True

    def require_owner(
        self, invocation_id: str, digest: str, node_id: str, instance_id: str
    ) -> dict[str, Any]:
        row = self.require(invocation_id, digest, lock=True)
        if (row["node_id"], row["instance_id"]) != (node_id, instance_id):
            raise RuntimePoolError("runtime_invocation_owner_mismatch")
        if row["state"] != "RUNNING" or row["lease_until"] <= timestamp(
            database_now(self.database)
        ):
            raise RuntimePoolError("runtime_execution_lease_lost")
        return row

    def renew(self, invocation_id: str, digest: str, node_id: str, instance_id: str) -> bool:
        with self.database.unit_of_work():
            row = self.require_owner(invocation_id, digest, node_id, instance_id)
            if row["cancel_requested_at"] is not None:
                return False
            now = database_now(self.database)
            if row["execution_deadline_at"] <= timestamp(now):
                return False
            self.database.execute(
                "update agent_runtime_invocation set lease_until = ? where invocation_id = ?",
                (timestamp(now + timedelta(seconds=LEASE_SECONDS)), invocation_id),
            )
            return True

    def request_cancel(self, invocation_id: str, digest: str, reason: str) -> str:
        with self.database.unit_of_work():
            row = self.require(invocation_id, digest, lock=True)
            if row["state"] == "TERMINAL":
                return "already_terminal"
            now = timestamp(database_now(self.database))
            self.database.execute(
                """
                update agent_runtime_invocation set cancel_requested_at = coalesce(cancel_requested_at, ?),
                  cancel_reason = coalesce(cancel_reason, ?) where invocation_id = ?
                """,
                (now, reason, invocation_id),
            )
            if row["state"] == "PREPARED":
                self.database.execute(
                    """
                    update agent_runtime_invocation set state = 'TERMINAL', terminal_at = ?,
                      terminal_code = 'runtime_cancelled', execution_quiesced_at = ?
                    where invocation_id = ? and state = 'PREPARED'
                    """,
                    (now, now, invocation_id),
                )
                return "cancelled"
            return "cancel_requested"

    def quiesce(self, invocation_id: str, node_id: str, instance_id: str) -> None:
        # A stopped owner may record stop evidence even after its write lease
        # expired. This cannot change ownership, the outcome, or a terminal.
        self.database.execute(
            """
            update agent_runtime_invocation set execution_quiesced_at = coalesce(execution_quiesced_at, ?)
            where invocation_id = ? and node_id = ? and instance_id = ?
            """,
            (timestamp(database_now(self.database)), invocation_id, node_id, instance_id),
        )

    def expire(self, *, limit: int = 100) -> int:
        now = timestamp(database_now(self.database))
        candidates = self.database.execute(
            """
            select invocation_id from agent_runtime_invocation
            where (state = 'RUNNING' and lease_until <= ?)
               or (state = 'PREPARED' and admission_deadline_at <= ?)
            order by created_at limit ?
            """,
            (now, now, min(max(limit, 1), 100)),
        )
        count = 0
        for candidate in candidates:
            with self.database.unit_of_work():
                row = self.get(candidate["invocation_id"], lock=True)
                if row is None or row["state"] == "TERMINAL":
                    continue
                cutoff = (
                    row["lease_until"]
                    if row["state"] == "RUNNING"
                    else row["admission_deadline_at"]
                )
                if cutoff > timestamp(database_now(self.database)):
                    continue
                code = (
                    "runtime_invocation_outcome_unknown"
                    if row["state"] == "RUNNING"
                    else "runtime_admission_timeout"
                )
                self.database.execute(
                    """
                    update agent_runtime_invocation set state = 'TERMINAL', terminal_code = ?,
                      terminal_at = ?, execution_quiesced_at = case when accepted_at is null
                        then ? else execution_quiesced_at end where invocation_id = ?
                    """,
                    (code, now, now, row["invocation_id"]),
                )
                count += 1
        return count

    def record_replacement(self, node_id: str, instance_id: str) -> None:
        """Only after verifying a fixed single-container Compose service's boot identity."""
        self.database.execute(
            """
            update agent_runtime_invocation set execution_quiesced_at = ?
            where node_id = ? and instance_id <> ? and execution_quiesced_at is null
              and state = 'TERMINAL'
            """,
            (timestamp(database_now(self.database)), node_id, instance_id),
        )

    def prune_body(self, invocation_id: str) -> bool:
        # Called by authorized maintenance, never by an unauthenticated read.
        # Identity remains as a permanent no-reexecution tombstone with the Job.
        with self.database.unit_of_work():
            job = self.database.execute_one(
                "select j.status from agent_job j join agent_runtime_invocation i on i.job_id = j.id "
                "where i.invocation_id = ?",
                (invocation_id,),
            )
            row = self.get(invocation_id, lock=True)
            if not row or not job or job["status"] not in {"SUCCEEDED", "FAILED", "TIMEOUT"}:
                return False
            if row["state"] != "TERMINAL" or row["execution_quiesced_at"] is None:
                return False
            for table in (
                "agent_runtime_request_snapshot",
                "agent_runtime_invocation_event",
                "agent_runtime_terminal_ledger",
            ):
                self.database.execute(
                    f"delete from {table} where invocation_id = ?", (invocation_id,)
                )
            return True

    def finish(
        self, invocation_id: str, digest: str, node_id: str, instance_id: str, code: str
    ) -> None:
        if self.database.current_unit_of_work is None:
            raise RuntimeError("Terminal and ledger must share a transaction")
        row = self.require_owner(invocation_id, digest, node_id, instance_id)
        if row["cancel_requested_at"] is not None and code != "runtime_cancelled":
            raise RuntimePoolError("runtime_cancel_requested")
        if row["execution_quiesced_at"] is None:
            raise RuntimePoolError("runtime_execution_not_quiesced")
        self.database.execute(
            """
            update agent_runtime_invocation set state = 'TERMINAL', terminal_at = ?, terminal_code = ?
            where invocation_id = ?
            """,
            (timestamp(database_now(self.database)), code, invocation_id),
        )

    @staticmethod
    def grant_binding(row: dict[str, Any]) -> dict[str, Any]:
        return {
            key: row[key]
            for key in (
                "invocation_id",
                "job_id",
                "request_digest",
                "protocol_version",
                "app_user_id",
                "agent_publication_id",
                "application_publication_id",
            )
        } | {"runtime_kind": "python-v1", "limits": {"timeout_seconds": row["timeout_seconds"]}}
