"""网页、CLI 与执行器共享的持久任务；不执行外部命令。"""

from datetime import date, datetime
import json
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.modules.knowledge.domain.collection_window import validate_backfill
from app.modules.knowledge.domain.identity import now
from app.modules.knowledge.domain.operations import (
    ACTIVE_STATES,
    DEPLOY_ACTIONS,
    EVENT_CODES,
    SAFE_ID,
    SERVICES,
    SYNC_ACTIONS,
    fresh,
    invalid,
    safe_details,
)
from app.modules.knowledge.infrastructure.incremental_repository import IncrementalSyncRepository
from app.modules.knowledge.infrastructure.storage import insert, table
from app.shared.database import Database


class OperationsRepository:
    def __init__(self, database: Database):
        self.database = database

    def t(self, name: str) -> str:
        return table(self.database, name)

    def gate(self) -> None:
        insert(
            self.database,
            "ops_runtime",
            {
                "id": "deployment",
                "snapshot_json": {},
                "heartbeat_at": now(),
            },
            conflict="on conflict(id) do nothing",
        )
        suffix = " for update" if self.database.engine == "postgres" else ""
        self.database.execute_one(
            f"select id from {self.t('ops_runtime')} where id='deployment'{suffix}"
        )

    def operation(self, identifier: str) -> dict[str, Any]:
        row = self.database.execute_one(
            f"select * from {self.t('ops_operation')} where id=?", (identifier,)
        )
        if not row:
            raise invalid("knowledge_ops_not_found")
        row["parameters"] = json.loads(row.pop("parameters_json"))
        return row

    def history(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.database.execute(
            f"select id from {self.t('ops_operation')} order by created_at desc,id desc limit ?",
            (limit,),
        )
        return [self.operation(row["id"]) for row in rows]

    def submit(
        self,
        *,
        kind: str,
        request_key: str,
        actor_id: str,
        binding_id: str | None = None,
        first_day: str | None = None,
        last_day: str | None = None,
        automatic: bool = False,
    ) -> dict[str, Any]:
        if (
            kind not in DEPLOY_ACTIONS | SYNC_ACTIONS
            or not isinstance(request_key, str)
            or not SAFE_ID.fullmatch(request_key)
        ):
            raise invalid()
        with self.database.unit_of_work():
            self.gate()
            prior = self.database.execute_one(
                f"select id from {self.t('ops_operation')} where request_key=?", (request_key,)
            )
            if prior:
                old = self.operation(prior["id"])
                if (
                    old["kind"],
                    old["binding_id"],
                    old["parameters"].get("first_day"),
                    old["parameters"].get("last_day"),
                    old["actor_id"],
                ) != (
                    kind,
                    binding_id,
                    first_day,
                    last_day,
                    actor_id,
                ):
                    raise invalid("knowledge_ops_idempotency_conflict")
                return old
            parameters = self._parameters(kind, binding_id, first_day, last_day)
            self._check_queue(kind, binding_id, automatic)
            identifier = uuid4().hex
            insert(
                self.database,
                "ops_operation",
                {
                    "id": identifier,
                    "request_key": request_key,
                    "kind": kind,
                    "binding_id": binding_id,
                    "parameters_json": parameters,
                    "actor_id": actor_id,
                    "state": "QUEUED",
                    "stage": "queued",
                    "created_at": now(),
                    "updated_at": now(),
                },
            )
            self.event(identifier, "sync" if binding_id else "controller", "queued")
        return self.operation(identifier)

    def _parameters(
        self, kind: str, binding_id: str | None, first: str | None, last: str | None
    ) -> dict[str, Any]:
        if kind in DEPLOY_ACTIONS:
            if any(value is not None for value in (binding_id, first, last)):
                raise invalid()
            return {}
        if not isinstance(binding_id, str):
            raise invalid()
        repo = IncrementalSyncRepository(self.database)
        binding = repo.binding(binding_id)
        if not binding["enabled"] or not binding["configuration_json"].get("collector"):
            raise invalid("knowledge_collection_disabled")
        parameters: dict[str, Any] = {"binding_revision": binding["configuration_revision"]}
        if kind == "sync":
            if first is not None or last is not None:
                raise invalid()
            return parameters
        try:
            begin, end = date.fromisoformat(first or ""), date.fromisoformat(last or "")
        except (TypeError, ValueError):
            raise invalid() from None
        validate_backfill(
            begin,
            end,
            date.fromisoformat(binding["configuration_json"]["collector"]["first_date"]),
            datetime.now(ZoneInfo("Asia/Shanghai")).date(),
        )
        # 沿用当前合同：首次全量完成前不启动独立日期补采。
        prior = self.database.execute_one(
            f"select id from {self.t('sync_run')} where binding_id=? and phase='ACTIVATED' and incremental=1 limit 1",
            (binding_id,),
        )
        if not prior:
            raise invalid("knowledge_collection_backfill_requires_baseline")
        return {**parameters, "first_day": begin.isoformat(), "last_day": end.isoformat()}

    def _check_queue(self, kind: str, binding_id: str | None, automatic: bool) -> None:
        pending = self.database.execute_one(
            f"select count(*) as n from {self.t('ops_operation')} where state in ('QUEUED','RUNNING','RETRY_WAIT')"
        )
        if pending and pending["n"] >= 50:
            raise invalid("knowledge_ops_queue_full")
        if kind in DEPLOY_ACTIONS:
            active = self.database.execute_one(
                f"select id from {self.t('ops_operation')} where binding_id is null and state in ('QUEUED','RUNNING','RETRY_WAIT') limit 1"
            )
            if active:
                raise invalid("knowledge_ops_busy")
        elif not automatic:
            active = self.database.execute_one(
                f"select id from {self.t('ops_operation')} where binding_id=? and state in ('PARTIAL','FAILED','INTERRUPTED') and run_id in (select id from {self.t('sync_run')} where active=1) limit 1",
                (binding_id,),
            )
            if active:
                raise invalid("knowledge_ops_retry_required")

    def update(
        self,
        identifier: str,
        *,
        state: str | None = None,
        stage: str | None = None,
        error_code: str | None = None,
        run_id: str | None = None,
        retry_at: str | None = None,
    ) -> None:
        old = self.operation(identifier)
        selected = state or old["state"]
        self.database.execute(
            f"update {self.t('ops_operation')} set state=?,stage=?,error_code=?,run_id=?,retry_at=?,updated_at=?,finished_at=? where id=?",
            (
                selected,
                stage or old["stage"],
                error_code,
                run_id or old["run_id"],
                retry_at,
                now(),
                None if selected in ACTIVE_STATES else now(),
                identifier,
            ),
        )

    def start(self, identifier: str) -> dict[str, Any]:
        with self.database.unit_of_work():
            self.gate()
            row = self.operation(identifier)
            if row["state"] not in ACTIVE_STATES:
                raise invalid("knowledge_ops_state_conflict")
            self.database.execute(
                f"update {self.t('ops_operation')} set state='RUNNING',stage='started',attempts=attempts+1,started_at=?,updated_at=?,error_code=NULL,retry_at=NULL,finished_at=NULL where id=?",
                (now(), now(), identifier),
            )
            self.event(identifier, "sync" if row["binding_id"] else "controller", "started")
        return self.operation(identifier)

    def retry(self, identifier: str) -> dict[str, Any]:
        with self.database.unit_of_work():
            self.gate()
            row = self.operation(identifier)
            if row["state"] not in {"FAILED", "PARTIAL", "INTERRUPTED"}:
                raise invalid("knowledge_ops_state_conflict")
            if row["binding_id"]:
                binding = IncrementalSyncRepository(self.database).binding(row["binding_id"])
                if (
                    not binding["enabled"]
                    or binding["configuration_revision"] != row["parameters"]["binding_revision"]
                ):
                    raise invalid("knowledge_sync_configuration_changed")
                self._check_queue(row["kind"], row["binding_id"], True)
            else:
                self._check_queue(row["kind"], None, False)
            self.database.execute(
                f"update {self.t('ops_operation')} set state='QUEUED',stage='queued',attempts=0,error_code=NULL,retry_at=NULL,finished_at=NULL,updated_at=? where id=?",
                (now(), identifier),
            )
            self.event(identifier, "sync" if row["binding_id"] else "controller", "queued")
        return self.operation(identifier)

    def event(
        self,
        operation_id: str | None,
        service: str,
        code: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        if code not in EVENT_CODES or service not in {
            *SERVICES,
            "controller",
            "sync",
            "knowledge-model-prepare",
            "knowledge-reranker-prepare",
            "knowledge-check",
        }:
            raise invalid()
        insert(
            self.database,
            "ops_event",
            {
                "id": uuid4().hex,
                "operation_id": operation_id,
                "service": service,
                "code": code,
                "details_json": safe_details(details or {}),
                "created_at": now(),
            },
        )

    def events(
        self,
        *,
        operation_id: str | None = None,
        service: str | None = None,
        after: str | None = None,
    ) -> dict[str, Any]:
        clauses, values = [], []
        for name, value in (("operation_id", operation_id), ("service", service)):
            if value:
                clauses.append(f"{name}=?")
                values.append(value)
        if after:
            stamp, sep, identifier = after.partition("|")
            if not sep or len(stamp) > 40 or not SAFE_ID.fullmatch(identifier):
                raise invalid()
            clauses.append("(created_at>? or (created_at=? and id>?))")
            values.extend((stamp, stamp, identifier))
        where = " where " + " and ".join(clauses) if clauses else ""
        order = "asc" if after else "desc"
        rows = self.database.execute(
            f"select * from {self.t('ops_event')}{where} order by created_at {order},id {order} limit 200",
            tuple(values),
        )
        if not after:
            rows.reverse()
        for row in rows:
            row["details"] = json.loads(row.pop("details_json"))
        return {
            "events": rows,
            "cursor": f"{rows[-1]['created_at']}|{rows[-1]['id']}" if rows else after,
        }

    def heartbeat(self, role: str, snapshot: dict[str, Any]) -> None:
        insert(
            self.database,
            "ops_runtime",
            {"id": role, "snapshot_json": snapshot, "heartbeat_at": now()},
            conflict="on conflict(id) do update set snapshot_json=excluded.snapshot_json,heartbeat_at=excluded.heartbeat_at",
        )

    def runtime(self, role: str) -> dict[str, Any]:
        row = self.database.execute_one(
            f"select * from {self.t('ops_runtime')} where id=?", (role,)
        )
        return {
            "online": bool(row and fresh(row["heartbeat_at"])),
            "observed_at": row["heartbeat_at"] if row else None,
            "snapshot": json.loads(row["snapshot_json"]) if row else {},
        }

    def waiting(self, sync: bool) -> list[dict[str, Any]]:
        null = "not null" if sync else "null"
        rows = self.database.execute(
            f"select id from {self.t('ops_operation')} where binding_id is {null} and state in ('QUEUED','RUNNING','RETRY_WAIT') order by created_at,id limit 50"
        )
        return [self.operation(row["id"]) for row in rows]
