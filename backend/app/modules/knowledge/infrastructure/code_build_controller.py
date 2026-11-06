"""Bounded persisted build ticks. Models run only in standard dispatched Jobs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.modules.knowledge.infrastructure.code_extraction_jobs import (
    CodeArtifactCollector,
    CodeExtractionJobs,
)
from app.modules.knowledge.infrastructure.code_scope import CodeScopePlanner
from app.modules.knowledge.infrastructure.code_dependency_expansion import expand_dependencies
from app.modules.knowledge.infrastructure.code_indexing import CodeSnapshotIndexer
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.identity import now
from app.modules.knowledge.domain.normalization import canonical_json, digest
from app.modules.knowledge.infrastructure.code_build_repository import CodeBuildRepository
from app.modules.knowledge.infrastructure.code_repository import decoded
from app.modules.knowledge.infrastructure.storage import table
from app.shared.database import Database

MAX_UNITS = 24
BUILD_DEADLINE = timedelta(hours=24)


def review_digest(units: list[dict[str, Any]]) -> str:
    return digest(
        [
            {
                "id": unit["id"],
                "result": decoded(unit["result_json"]),
                "artifact": decoded(unit["artifact_json"]),
            }
            for unit in sorted(units, key=lambda row: row["id"])
            if not (decoded(unit["result_json"]) or {}).get("replacement_unit_id")
        ]
    )


class CodeBuildController:
    def __init__(
        self,
        database: Database,
        jobs: CodeExtractionJobs,
        collector: CodeArtifactCollector,
        *,
        source_root: Path,
        indexer: CodeSnapshotIndexer | None = None,
    ) -> None:
        self.db, self.jobs, self.collector = database, jobs, collector
        self.builds = CodeBuildRepository(database)
        self.planner = CodeScopePlanner(source_root)
        self.indexer = indexer
        # An expired lease is never renewed from memory; takeover increments the
        # persisted fencing version. Unit Jobs and artifact identities stay fixed.
        self.leases: dict[str, int] = {}

    def tick(self) -> list[dict[str, Any]]:
        rows = self.db.execute(
            f"select id,source_id from {table(self.db, 'code_build')} "
            "where stage in ('QUEUED','SOURCE_READY','EXTRACTING','VALIDATING','INDEXING','READY') "
            "and (stage<>'READY' or active=1 or purpose in ('baseline','daily')) order by active desc,created_at,id limit 100"
        )
        seen, results = set(), []
        for row in rows:
            if row["source_id"] in seen:
                continue
            seen.add(row["source_id"])
            results.append(self.step(row["id"]))
            if len(seen) >= 20:
                break
        return results

    def step(self, build_id: str) -> dict[str, Any]:
        try:
            lease = self.leases.get(build_id)
            if lease is not None:
                try:
                    self.builds.renew(build_id, lease)
                except CodeKnowledgeError:
                    self.leases.pop(build_id, None)
                    lease = None
            if lease is None:
                lease = self.builds.claim(build_id)
                self.leases[build_id] = lease
            build = self.builds._leased(build_id, lease)
            if build["stage"] in {"QUEUED", "SOURCE_READY", "EXTRACTING"}:
                created = build["created_at"]
                if isinstance(created, str):
                    created = datetime.fromisoformat(created)
                if datetime.now(UTC) - created > BUILD_DEADLINE:
                    raise CodeKnowledgeError("code_build_budget_exhausted")
            try:
                state = self._step(build, lease)
            except CodeKnowledgeError:
                raise
            except Exception:
                # Providers and authorization may throw non-domain errors. Never
                # expose their messages, configuration or connection details.
                raise CodeKnowledgeError("code_build_dependency_unavailable") from None
            return {"build_id": build_id, "state": state}
        except CodeKnowledgeError as exc:
            if exc.code in {
                "code_source_busy",
                "code_prior_execution_unresolved",
                "code_build_lease_lost",
            }:
                return {"build_id": build_id, "state": "WAITING", "reason": exc.code}
            lease = self.leases.pop(build_id, None)
            if lease is not None:
                try:
                    self.builds.fail(build_id, lease, exc.code)
                except CodeKnowledgeError:
                    pass  # A stale controller must not change the new owner's state.
            return {"build_id": build_id, "state": "FAILED", "reason": exc.code}

    def _step(self, build: dict[str, Any], lease: int) -> str:
        stage, identifier = build["stage"], build["id"]
        if stage == "QUEUED":
            count = self.planner.persist(self.db, identifier)
            if not 1 <= count <= MAX_UNITS:
                raise CodeKnowledgeError("code_unit_budget_exhausted")
            self.builds.advance(identifier, lease, stage)
            return "SOURCE_READY"
        if stage == "SOURCE_READY":
            self.builds.advance(identifier, lease, stage)
            return "EXTRACTING"
        if stage == "EXTRACTING":
            return self._extract(build, lease)
        if stage == "VALIDATING":
            validation = self._validation(build, lease)
            if not validation["business_verified"]:
                return "BUSINESS_REVIEW_REQUIRED"
            if validation["activation_blocked"]:
                return "DEPENDENCIES_UNRESOLVED"
            self.builds.advance(identifier, lease, stage)
            return "INDEXING"
        if stage == "INDEXING":
            if self.indexer is None:
                return "INDEXER_UNCONFIGURED"
            return "READY" if self.indexer.index(identifier, lease) else "INDEXING"
        if stage == "READY":
            if build["purpose"] in {"history", "release"}:
                self.builds.finish_history(identifier, lease)
            else:
                self.builds.activate(identifier, lease)
            self.leases.pop(identifier, None)
            return "READY" if build["purpose"] in {"history", "release"} else "ACTIVATED"
        return str(stage)

    def _units(self, build_id: str) -> list[dict[str, Any]]:
        rows = self.db.execute(
            f"select u.*,j.status as job_status from {table(self.db, 'code_unit')} u "
            "left join agent_job j on j.id=u.job_id where u.build_id=? "
            "order by case when u.state='RUNNING' then 0 else 1 end,u.unit_key limit 25",
            (build_id,),
        )
        if not 1 <= len(rows) <= MAX_UNITS:
            raise CodeKnowledgeError("code_unit_budget_exhausted")
        return rows

    def _extract(self, build: dict[str, Any], lease: int) -> str:
        units = self._units(build["id"])
        for unit in units:
            if unit["state"] == "VALIDATED":
                result = decoded(unit["result_json"])
                if result.get("dependency_requests") and not result.get("replacement_unit_id"):
                    expand_dependencies(self.db, unit, lease)
                    return "DEPENDENCIES_EXPANDED"
                continue
            if unit["state"] == "QUEUED" and not unit["job_id"]:
                # At most one in-flight unit per source; ordinary runtime pool
                # admission and frozen Application budgets remain in force.
                self.jobs.dispatch(unit["id"], lease)
                return "JOB_DISPATCHED"
            if unit["job_status"] in {"PENDING", "RUNNING", "RETRY_WAIT"}:
                return "JOB_RUNNING"
            invocation = self.db.execute_one(
                "select state,execution_quiesced_at from agent_runtime_invocation "
                "where job_id=? order by attempt desc limit 1",
                (unit["job_id"],),
            )
            if invocation and invocation["execution_quiesced_at"] is None:
                return "EXECUTION_UNRESOLVED"
            if unit["job_status"] != "SUCCEEDED":
                raise CodeKnowledgeError("code_extraction_job_failed")
            self.collector.collect(unit["id"], lease)
            return "CANDIDATE_COLLECTED"
        self.builds.advance(build["id"], lease, "EXTRACTING")
        return "VALIDATING"

    def _validation(self, build: dict[str, Any], lease: int) -> dict[str, Any]:
        units = self._units(build["id"])
        if any(unit["state"] != "VALIDATED" for unit in units):
            raise CodeKnowledgeError("code_units_incomplete")
        results = [decoded(unit["result_json"]) for unit in units]
        results = [result for result in results if not result.get("replacement_unit_id")]
        with self.db.unit_of_work():
            self.builds._leased(build["id"], lease)
            row = self.db.execute_one(
                f"select validation_json from {table(self.db, 'code_snapshot')} where id=?",
                (build["snapshot_id"],),
            )
            previous = decoded(row["validation_json"]) if row else {}
            continuity = self._continuity(build, results)
            result = {
                "machine_valid": all(r["machine_valid"] for r in results),
                "activation_blocked": any(r["activation_blocked"] for r in results)
                or not continuity["complete"],
                "continuity": continuity,
                "business_verified": bool(previous.get("business_verified"))
                and previous.get("business_review", {}).get("unit_digest") == review_digest(units),
                "unit_count": len(results),
                **{
                    name: sum(r[name] for r in results)
                    for name in (
                        "knowledge_count",
                        "evidence_count",
                        "relation_count",
                    )
                },
            }
            if previous.get("business_review"):
                result["business_review"] = previous["business_review"]
            self.db.execute(
                f"update {table(self.db, 'code_snapshot')} set validation_json=? where id=? and state='CANDIDATE'",
                (canonical_json(result), build["snapshot_id"]),
            )
            self.db.execute(
                f"update {table(self.db, 'code_build')} set updated_at=? where id=?",
                (now(), build["id"]),
            )
        return result

    def _continuity(self, build: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any]:
        source = self.db.execute_one(
            f"select manifest_json from {table(self.db, 'code_source_snapshot')} where id=?",
            (build["source_snapshot_id"],),
        )
        complete = bool(source and decoded(source["manifest_json"]).get("scan_complete"))
        if not build["parent_snapshot_id"]:
            return {"complete": complete, "missing_keys": [], "confirmed_absences": []}
        missing = self.db.execute(
            f"select d.external_id from {table(self.db, 'code_member')} old join {table(self.db, 'document')} d on d.id=old.document_id "
            f"where old.snapshot_id=? and not exists(select 1 from {table(self.db, 'code_member')} fresh where fresh.snapshot_id=? and fresh.document_id=old.document_id) order by d.external_id limit 1001",
            (build["parent_snapshot_id"], build["snapshot_id"]),
        )
        absent = {row["external_id"] for row in missing}
        declared = {
            item["business_key"] for result in results for item in result.get("removed_keys", [])
        }
        unresolved = sorted(absent - declared)
        return {
            "complete": complete and not unresolved and len(missing) <= 1000,
            "missing_keys": unresolved[:1000],
            "confirmed_absences": sorted(absent & declared)[:1000],
            "absence_status": "candidate_requires_business_review",
        }
