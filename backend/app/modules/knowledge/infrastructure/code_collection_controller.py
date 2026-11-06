"""Restartable pinned SVN collection; separate from model dispatch and ONES schedules."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.modules.knowledge.infrastructure.code_baseline import CodeBaselineAdmission
from app.modules.knowledge.application.code_schedule import next_daily
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.identity import now
from app.modules.knowledge.domain.normalization import canonical_json
from app.modules.knowledge.infrastructure.code_build_repository import CodeBuildRepository
from app.modules.knowledge.infrastructure.code_repository import CodeRepository, decoded
from app.modules.knowledge.infrastructure.code_source_registry import CodeSourceRegistry
from app.modules.knowledge.infrastructure.storage import source_lock, table
from app.shared.database import Database


def due(value: Any, current: datetime) -> bool:
    return (
        not value or (datetime.fromisoformat(value) if isinstance(value, str) else value) <= current
    )


class CodeCollectionController:
    def __init__(self, database: Database, registry: CodeSourceRegistry, source_root: Path) -> None:
        self.db, self.registry, self.source_root = database, registry, source_root
        self.repo, self.builds = CodeRepository(database), CodeBuildRepository(database)

    def tick(self) -> list[dict[str, Any]]:
        rows = self.db.execute(
            f"select source_id from {table(self.db, 'code_binding')} where enabled=1 order by next_run_at,source_id limit 20"
        )
        results = []
        for row in rows:
            try:
                # A process-scoped lock drops on disconnect; the persisted target survives.
                with source_lock(self.db, "code-svn:" + row["source_id"]):
                    results.append(self.step(row["source_id"]))
            except CodeKnowledgeError as exc:
                results.append(
                    {"source_id": row["source_id"], "state": "FAILED", "error_code": exc.code}
                )
        return results

    def step(self, source_id: str) -> dict[str, Any]:
        binding = self.repo.binding(source_id)
        config, operations = decoded(binding["config_json"]), decoded(binding["operations_json"])
        if (
            not binding["enabled"]
            or not config.get("svn_verified")
            or not operations.get("extraction")
        ):
            return {"source_id": source_id, "state": "UNCONFIGURED"}
        registered, admission = self.registry.get(config["svn_registration"]["key"])
        if registered["digest"] != config["svn_registration"]["digest"]:
            raise CodeKnowledgeError("code_source_configuration_changed")
        self._complete_demands(binding)
        if binding["demand_enabled"] and self._history_ledger(binding, admission.source):
            return {"source_id": source_id, "state": "HISTORY_LEDGER_COLLECTED"}
        state = decoded(binding["collection_json"])
        if state.get("state") in {None, "IDLE"}:
            current = datetime.now(UTC)
            demand = self.db.execute_one(
                f"select * from {table(self.db, 'code_demand')} where source_id=? and config_hash=? and state='PENDING' order by created_at,id limit 1",
                (source_id, binding["config_hash"]),
            )
            schedule = operations.get("schedule", {})
            scheduled = schedule.get("enabled") and due(binding["next_run_at"], current)
            if scheduled:
                target = admission.source.head()
                next_run = next_daily(current, schedule["local_time"], schedule["timezone"])
                state = {
                    **state,
                    "state": "COLLECTING",
                    "target_revision": target,
                    "purpose": "daily",
                    "demand_id": None,
                    "started_at": now(),
                    "error_code": None,
                    "extraction": operations["extraction"],
                }
                self._save(binding, state, next_run_at=next_run)
            elif demand:
                state = {
                    **state,
                    "state": "FREEZING",
                    "target_revision": demand["revision"],
                    "purpose": "history",
                    "demand_id": demand["id"],
                    "started_at": now(),
                    "error_code": None,
                    "extraction": operations["extraction"],
                }
                self._save(binding, state)
            else:
                return {"source_id": source_id, "state": "IDLE"}
        try:
            return self._advance(binding, state, admission, operations)
        except CodeKnowledgeError as exc:
            if exc.code == "code_collection_interrupted":
                return {"source_id": source_id, "state": "INTERRUPTED"}
            state = {**state, "state": "FAILED", "error_code": exc.code}
            self._save(binding, state)
            raise

    def _advance(
        self,
        binding: dict[str, Any],
        state: dict[str, Any],
        admission: Any,
        operations: dict[str, Any],
    ) -> dict[str, Any]:
        source_id, target = binding["source_id"], state["target_revision"]
        if state["state"] == "FAILED":
            return {"source_id": source_id, "state": "FAILED", "error_code": state["error_code"]}
        if state["state"] == "COLLECTING":
            after = binding["collected_revision"]
            if after is None or target < after:
                raise CodeKnowledgeError("code_svn_range_invalid")
            upper = min(target, after + 100)
            commits = admission.source.commits(after=after, target=target, through=upper)
            # Cursor and commit facts are atomic; a crash before the next state update resumes at that cursor.
            self.builds.record_commits(
                source_id,
                config_hash=binding["config_hash"],
                after=after,
                target=upper,
                repository_uuid=admission.source.expected_uuid,
                commits=commits,
            )
            if upper < target:
                return {
                    "source_id": source_id,
                    "state": "COLLECTING",
                    "collected_revision": upper,
                    "target_revision": target,
                }
            state = {**state, "state": "FREEZING"}
            self._save(binding, state)
        busy = self.db.execute_one(
            f"select id from {table(self.db, 'code_build')} where source_id=? and stage not in ('READY','ACTIVATED','FAILED','INTERRUPTED','CANCELLED') limit 1",
            (source_id,),
        )
        if busy:
            schedule = operations.get("schedule", {})
            current = datetime.now(UTC)
            if (
                state["purpose"] == "daily"
                and schedule.get("enabled")
                and due(binding["next_run_at"], current)
            ):
                latest = admission.source.head()
                if latest < target:
                    raise CodeKnowledgeError("code_svn_range_invalid")
                state = {**state, "target_revision": latest, "state": "COLLECTING"}
                self._save(
                    binding,
                    state,
                    next_run_at=next_daily(current, schedule["local_time"], schedule["timezone"]),
                )
            return {"source_id": source_id, "state": "WAITING_BUILD", "target_revision": target}
        with admission.prepare(target, capture_floating=state["purpose"] == "daily") as (
            collector,
            frozen,
        ):
            if not frozen.manifest["scan_complete"]:
                raise CodeKnowledgeError("code_svn_externals_unresolved")
            with source_lock(self.db, source_id):
                current_binding = self.repo.binding(source_id)
                if (
                    current_binding["config_hash"] != binding["config_hash"]
                    or not current_binding["enabled"]
                ):
                    raise CodeKnowledgeError("code_source_configuration_changed")
                snapshot = CodeBaselineAdmission(self.db, self.source_root).publish(
                    source_id, collector, frozen
                )
                with self.db.unit_of_work():
                    build = self.repo.new_build(
                        source_id,
                        snapshot,
                        purpose=state["purpose"],
                        configuration=state["extraction"],
                    )
                    if state["demand_id"]:
                        self.db.execute(
                            f"update {table(self.db, 'code_demand')} set state='BUILDING',build_id=? where id=? and state='PENDING'",
                            (build["build_id"], state["demand_id"]),
                        )
                    self._save(
                        binding,
                        {
                            **state,
                            "state": "IDLE",
                            "last_source_snapshot_id": snapshot,
                            "last_build_id": build["build_id"],
                        },
                    )
                    return {"source_id": source_id, "state": "BUILD_QUEUED", **build}

    def _save(
        self, binding: dict[str, Any], state: dict[str, Any], *, next_run_at: str | None = None
    ) -> None:
        with source_lock(self.db, binding["source_id"]), self.db.unit_of_work():
            rows = self.db.execute(
                f"update {table(self.db, 'code_binding')} set collection_json=?,next_run_at=coalesce(?,next_run_at),updated_at=? where source_id=? and config_hash=? returning source_id",
                (
                    canonical_json(state),
                    next_run_at,
                    now(),
                    binding["source_id"],
                    binding["config_hash"],
                ),
            )
            if not rows:
                raise CodeKnowledgeError("code_source_configuration_changed")

    def _complete_demands(self, binding: dict[str, Any]) -> None:
        rows = self.db.execute(
            f"select d.id,b.stage from {table(self.db, 'code_demand')} d join {table(self.db, 'code_build')} b on b.id=d.build_id "
            "where d.source_id=? and d.config_hash=? and d.state='BUILDING' limit 20",
            (binding["source_id"], binding["config_hash"]),
        )
        for row in rows:
            state = (
                "READY"
                if row["stage"] in {"READY", "ACTIVATED"}
                else "UNAVAILABLE"
                if row["stage"] in {"FAILED", "INTERRUPTED", "CANCELLED"}
                else None
            )
            if state:
                self.db.execute(
                    f"update {table(self.db, 'code_demand')} set state=? where id=? and state='BUILDING'",
                    (state, row["id"]),
                )

    def _history_ledger(self, binding: dict[str, Any], source: Any) -> bool:
        check = self.db.execute_one(
            f"select * from {table(self.db, 'code_history_check')} where source_id=? and config_hash=? and ledger_complete=0 order by from_revision,to_revision limit 1",
            (binding["source_id"], binding["config_hash"]),
        )
        if not check:
            return False
        comparison = decoded(check["comparison_json"])
        after = comparison.get("ledger_progress", {}).get(
            "through_revision", check["from_revision"]
        )
        target = check["to_revision"]
        upper = min(target, after + 100)
        commits = source.commits(after=after, target=target, through=upper)
        with source_lock(self.db, binding["source_id"]), self.db.unit_of_work():
            if self.repo.binding(binding["source_id"])["config_hash"] != binding["config_hash"]:
                raise CodeKnowledgeError("code_source_configuration_changed")
            self.builds.store_commit_facts(
                binding["source_id"], binding["config_hash"], source.expected_uuid, commits
            )
            latest = self.db.execute_one(
                f"select comparison_json from {table(self.db, 'code_history_check')} where source_id=? and document_id=? and config_hash=? and from_revision=? and to_revision=?",
                (
                    binding["source_id"],
                    check["document_id"],
                    binding["config_hash"],
                    check["from_revision"],
                    target,
                ),
            )
            if latest is None:
                raise CodeKnowledgeError("code_history_ledger_changed")
            comparison = decoded(latest["comparison_json"])
            comparison["ledger_progress"] = {"through_revision": upper, "target_revision": target}
            self.db.execute(
                f"update {table(self.db, 'code_history_check')} set ledger_complete=?,comparison_json=? where source_id=? and document_id=? and config_hash=? and from_revision=? and to_revision=?",
                (
                    int(upper == target),
                    canonical_json(comparison),
                    binding["source_id"],
                    check["document_id"],
                    binding["config_hash"],
                    check["from_revision"],
                    target,
                ),
            )
        return True
