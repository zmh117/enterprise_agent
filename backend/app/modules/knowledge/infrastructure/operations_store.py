"""运维控制面：持久任务、采集计划及有界运行投影。"""

from datetime import date
from contextlib import AbstractContextManager
from typing import Any

from app.modules.knowledge.domain.identity import now, stable_id
from app.modules.knowledge.domain.operations import invalid
from app.modules.knowledge.infrastructure.incremental_repository import IncrementalSyncRepository
from app.modules.knowledge.infrastructure.operations_repository import OperationsRepository
from app.shared.database import Database


class OperationsStore:
    def __init__(self, database: Database):
        self.database = database
        self.operations = OperationsRepository(self.database)
        self.sync = IncrementalSyncRepository(self.database)

    def transaction(self) -> AbstractContextManager[Any]:
        return self.database.unit_of_work()

    def submit(self, **values: Any) -> dict[str, Any]:
        return self.operations.submit(**values)

    def retry(self, operation_id: str) -> dict[str, Any]:
        return self.operations.retry(operation_id)

    def events(self, **values: Any) -> dict[str, Any]:
        return self.operations.events(**values)

    def schedule(self, *, binding_id: str, enabled: bool, expected_revision: int) -> dict[str, Any]:
        if type(enabled) is not bool or type(expected_revision) is not int:
            raise invalid()
        with self.database.unit_of_work():
            binding = self.sync.binding(binding_id, lock=True)
            if binding["configuration_revision"] != expected_revision:
                raise invalid("knowledge_sync_configuration_changed")
            if enabled and not binding["enabled"]:
                self.sync.set_collection_enabled(
                    binding_id, enabled=True, expected_revision=expected_revision
                )
            self.database.execute(
                f"update {self.sync.t('sync_binding')} set schedule_enabled=?,next_run_at=case when ?=1 then ? else next_run_at end,updated_at=? where id=?",
                (int(enabled), int(enabled), now(), now(), binding_id),
            )
            self.operations.event(None, "sync", "schedule_changed", {"binding_id": binding_id})
        return self.plan(binding_id)

    def configure(
        self,
        *,
        code: str,
        source_code: str,
        configuration: dict[str, Any],
        expected_revision: int,
    ) -> dict[str, Any]:
        binding = self.sync.configure(
            code=code,
            source_code=source_code,
            configuration=configuration,
            expected_revision=expected_revision,
        )
        return self.plan(binding["id"])

    def configuration(self, *, binding_id: str) -> dict[str, Any]:
        binding = self.sync.binding(binding_id)
        source = self.database.execute_one(
            f"select code from {self.sync.t('source')} where id=?", (binding["source_id"],)
        )
        return {
            "code": binding["code"],
            "source_code": source["code"] if source else "",
            "expected_revision": binding["configuration_revision"],
            "configuration": binding["configuration_json"],
        }

    def snapshot(self) -> dict[str, Any]:
        rows = self.database.execute(
            f"select id from {self.sync.t('sync_binding')} order by code limit 100"
        )
        return {
            "controller": self.operations.runtime("controller"),
            "sync_worker": self.operations.runtime("sync"),
            "deployment": self.operations.runtime("deployment"),
            "plans": [self.plan(row["id"]) for row in rows],
            "operations": self.operations.history(),
        }

    def plan(self, binding_id: str) -> dict[str, Any]:
        binding = self.sync.binding(binding_id)
        latest = self.database.execute_one(
            f"select id from {self.sync.t('sync_run')} where binding_id=? order by created_at desc,id desc limit 1",
            (binding_id,),
        )
        success = self.database.execute_one(
            f"select updated_at from {self.sync.t('sync_run')} where binding_id=? and phase='ACTIVATED' order by updated_at desc limit 1",
            (binding_id,),
        )
        result = {
            "id": binding_id,
            "code": binding["code"],
            "revision": binding["configuration_revision"],
            "enabled": bool(binding["enabled"]),
            "schedule_enabled": bool(binding["schedule_enabled"]),
            "interval_seconds": binding["interval_seconds"],
            "next_run_at": binding["next_run_at"] if binding["schedule_enabled"] else None,
            "last_success_at": success["updated_at"] if success else None,
            "first_day": binding["configuration_json"].get("collector", {}).get("first_date"),
            "run": self.run_progress(latest["id"]) if latest else None,
            "bases": [],
        }
        for kind, code in binding["configuration_json"]["base_codes"].items():
            metrics = self._metrics(latest["id"], kind) if latest else None
            result["bases"].append(
                {
                    "kind": kind,
                    "code": code,
                    "knowledge_base_id": stable_id("base", code),
                    "metrics": metrics,
                }
            )
        return result

    def run_progress(self, run_id: str) -> dict[str, Any]:
        summary = self.sync.summary(run_id)
        run = self.sync.run(run_id)
        summary["active"] = bool(run["active"])
        collection = summary.get("collection")
        if collection:
            first, last = (
                date.fromisoformat(collection["first_day"]),
                date.fromisoformat(collection["last_day"]),
            )
            total = (last - first).days + 1
            next_day = (
                date.fromisoformat(collection["next_day"]) if collection.get("next_day") else first
            )
            collection["total_days"] = total
            collection["completed_days"] = min(total, max(0, (next_day - first).days))
            if run["phase"] != "COLLECTING":
                collection["completed_days"] = total
        return summary

    def _metrics(self, run_id: str, kind: str) -> dict[str, int]:
        rows = self.database.execute(
            f"select outcome,processing_step,processing_error,count(*) as n from {self.sync.t('sync_candidate')} where run_id=? and (candidate_kind=? or baseline_kind=?) group by outcome,processing_step,processing_error",
            (run_id, kind, kind),
        )
        metrics = dict(created=0, revised=0, unchanged=0, stale=0, completed=0, failed=0, total=0)
        for row in rows:
            outcome, count = row["outcome"], row["n"]
            if outcome in metrics:
                metrics[outcome] += count
            if outcome in {"created", "revised"}:
                metrics["total"] += count
                metrics["completed"] += count if row["processing_step"] == "DONE" else 0
                metrics["failed"] += count if row["processing_error"] else 0
        return metrics
