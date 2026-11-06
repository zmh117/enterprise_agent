"""Durable bounded build coordination; all external work happens outside transactions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.identity import now, stable_id
from app.modules.knowledge.domain.normalization import digest
from app.modules.knowledge.infrastructure.code_repository import CodeRepository, decoded
from app.modules.knowledge.infrastructure.storage import insert, source_lock, table
from app.shared.database import Database

NEXT_STAGE = {
    "QUEUED": "SOURCE_READY",
    "SOURCE_READY": "EXTRACTING",
    "EXTRACTING": "VALIDATING",
    "VALIDATING": "INDEXING",
    "INDEXING": "READY",
}


class CodeBuildRepository:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.content = CodeRepository(database)

    def get(self, build_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            f"select * from {table(self.database, 'code_build')} where id=?", (build_id,)
        )
        if not row:
            raise CodeKnowledgeError("code_build_unavailable")
        return row

    def claim(self, build_id: str, *, lease_seconds: int = 300) -> int:
        if not 1 <= lease_seconds <= 900:
            raise CodeKnowledgeError("code_lease_invalid")
        build = self.get(build_id)
        with source_lock(self.database, build["source_id"]), self.database.unit_of_work():
            build = self.get(build_id)
            current = now()
            if build["stage"] in {"ACTIVATED", "CANCELLED", "FAILED", "INTERRUPTED"}:
                raise CodeKnowledgeError("code_build_terminal")
            active = self.database.execute_one(
                f"select id,lease_until from {table(self.database, 'code_build')} where source_id=? and active=1",
                (build["source_id"],),
            )
            if active and (
                active["id"] != build_id or _expiry(active["lease_until"]) > datetime.now(UTC)
            ):
                raise CodeKnowledgeError("code_source_busy")
            unknown = self.database.execute_one(
                f"select i.invocation_id from agent_runtime_invocation i "
                f"join {table(self.database, 'code_unit')} u on u.job_id=i.job_id "
                f"join {table(self.database, 'code_build')} b on b.id=u.build_id "
                "where b.source_id=? and b.id<>? and i.execution_quiesced_at is null "
                "and i.state<>'PREPARED' limit 1",
                (build["source_id"], build_id),
            )
            if unknown:
                raise CodeKnowledgeError("code_prior_execution_unresolved")
            until = (datetime.now(UTC) + timedelta(seconds=lease_seconds)).isoformat()
            self.database.execute(
                f"update {table(self.database, 'code_build')} set active=1,lease_version=lease_version+1,lease_until=?,updated_at=? where id=?",
                (until, current, build_id),
            )
            return int(build["lease_version"]) + 1

    def fail(self, build_id: str, lease: int, error_code: str) -> None:
        if not error_code.startswith("code_") or not error_code.replace("_", "").isalnum():
            error_code = "code_build_failed"
        with self.database.unit_of_work():
            self._leased(build_id, lease, check_config=False)
            self.database.execute(
                f"update {table(self.database, 'code_build')} set stage='FAILED',active=0,error_code=?,updated_at=? "
                "where id=? and lease_version=?",
                (error_code, now(), build_id, lease),
            )

    def _leased(self, build_id: str, lease: int, *, check_config: bool = True) -> dict[str, Any]:
        locking = (
            " for update of b,c"
            if self.database.engine == "postgres" and self.database.current_unit_of_work is not None
            else ""
        )
        build = self.database.execute_one(
            f"select b.*,c.config_hash as current_config_hash from {table(self.database, 'code_build')} b "
            f"join {table(self.database, 'code_binding')} c on c.source_id=b.source_id where b.id=?"
            + locking,
            (build_id,),
        )
        if not build:
            raise CodeKnowledgeError("code_build_unavailable")
        lease_until = build["lease_until"]
        if isinstance(lease_until, str):
            lease_until = datetime.fromisoformat(lease_until)
        if (
            not build["active"]
            or build["lease_version"] != lease
            or not lease_until
            or lease_until <= datetime.now(UTC)
        ):
            raise CodeKnowledgeError("code_build_lease_lost")
        if check_config and build["current_config_hash"] != build["config_hash"]:
            raise CodeKnowledgeError("code_source_configuration_changed")
        return build

    def renew(self, build_id: str, lease: int, *, lease_seconds: int = 300) -> None:
        if not 1 <= lease_seconds <= 900:
            raise CodeKnowledgeError("code_lease_invalid")
        with self.database.unit_of_work():
            self._leased(build_id, lease)
            self.database.execute(
                f"update {table(self.database, 'code_build')} set lease_until=?,updated_at=? where id=? and lease_version=?",
                (
                    (datetime.now(UTC) + timedelta(seconds=lease_seconds)).isoformat(),
                    now(),
                    build_id,
                    lease,
                ),
            )

    def advance(self, build_id: str, lease: int, expected_stage: str) -> None:
        if expected_stage not in NEXT_STAGE or expected_stage == "INDEXING":
            raise CodeKnowledgeError("code_build_stage_invalid")
        with self.database.unit_of_work():
            self._leased(build_id, lease)
            rows = self.database.execute(
                f"update {table(self.database, 'code_build')} set stage=?,updated_at=? where id=? and lease_version=? and stage=? returning id",
                (NEXT_STAGE[expected_stage], now(), build_id, lease, expected_stage),
            )
            if not rows:
                raise CodeKnowledgeError("code_build_stage_changed")

    def make_ready(
        self,
        build_id: str,
        lease: int,
        *,
        validation: dict[str, Any],
        expected_points: dict[str, str],
        visible_points: dict[str, str],
    ) -> None:
        # Values are supplied by deterministic validators/index adapters, never accepted from model answers.
        if (
            not validation.get("machine_valid")
            or validation.get("activation_blocked", True)
            or not validation.get("business_verified")
            or not expected_points
            or expected_points != visible_points
        ):
            raise CodeKnowledgeError("code_snapshot_validation_or_index_incomplete")
        with self.database.unit_of_work():
            build = self._leased(build_id, lease)
            if build["stage"] != "INDEXING":
                raise CodeKnowledgeError("code_build_stage_changed")
            row = self.database.execute_one(
                f"select index_manifest from {table(self.database, 'code_snapshot')} where id=?",
                (build["snapshot_id"],),
            )
            manifest = (
                {
                    **decoded(row["index_manifest"]),
                    "points": expected_points,
                    "digest": digest(expected_points),
                }
                if row
                else {}
            )
            self.database.execute(
                f"update {table(self.database, 'code_snapshot')} set state='READY',index_manifest=?,validation_json=?,ready_at=? where id=? and state='CANDIDATE'",
                (_json(manifest), _json(validation), now(), build["snapshot_id"]),
            )
            self.database.execute(
                f"update {table(self.database, 'code_build')} set stage='READY',updated_at=? where id=?",
                (now(), build_id),
            )

    def activate(self, build_id: str, lease: int) -> None:
        build = self.get(build_id)
        with source_lock(self.database, build["source_id"]), self.database.unit_of_work():
            build = self._leased(build_id, lease)
            if build["stage"] != "READY" or build["purpose"] in {"history", "release"}:
                raise CodeKnowledgeError("code_build_activation_denied")
            binding = self.content.binding(build["source_id"])
            if binding["active_snapshot_id"] != build["parent_snapshot_id"]:
                raise CodeKnowledgeError("code_build_parent_changed")
            self.content.snapshot(binding["knowledge_base_id"], build["snapshot_id"])
            rows = self.database.execute(
                f"update {table(self.database, 'code_binding')} set active_snapshot_id=?,updated_at=? where source_id=? and config_hash=? and (active_snapshot_id=? or (active_snapshot_id is null and ? is null)) returning source_id",
                (
                    build["snapshot_id"],
                    now(),
                    build["source_id"],
                    build["config_hash"],
                    build["parent_snapshot_id"],
                    build["parent_snapshot_id"],
                ),
            )
            if not rows:
                raise CodeKnowledgeError("code_build_parent_changed")
            self.database.execute(
                f"update {table(self.database, 'code_build')} set stage='ACTIVATED',active=0,updated_at=? where id=?",
                (now(), build_id),
            )

    def finish_history(self, build_id: str, lease: int) -> None:
        with self.database.unit_of_work():
            build = self._leased(build_id, lease)
            if build["stage"] != "READY" or build["purpose"] not in {"history", "release"}:
                raise CodeKnowledgeError("code_build_stage_invalid")
            self.database.execute(
                f"update {table(self.database, 'code_build')} set active=0,updated_at=? where id=?",
                (now(), build_id),
            )

    def rollback(self, source_id: str, snapshot_id: str, *, expected_active: str | None) -> None:
        with source_lock(self.database, source_id), self.database.unit_of_work():
            binding = self.content.binding(source_id)
            target = self.content.snapshot(binding["knowledge_base_id"], snapshot_id)
            if (
                binding["active_snapshot_id"] != expected_active
                or target["config_hash"] != binding["config_hash"]
            ):
                raise CodeKnowledgeError("code_rollback_conflict")
            if not decoded(target["index_manifest"]).get("points"):
                raise CodeKnowledgeError("code_snapshot_index_unavailable")
            self.database.execute(
                f"update {table(self.database, 'code_binding')} set active_snapshot_id=?,updated_at=? where source_id=?",
                (snapshot_id, now(), source_id),
            )

    def record_commits(
        self,
        source_id: str,
        *,
        config_hash: str,
        after: int,
        target: int,
        repository_uuid: str,
        commits: list[dict[str, Any]],
    ) -> None:
        if (
            target < after
            or any(not after < row["revision"] <= target for row in commits)
            or len({row["revision"] for row in commits}) != len(commits)
        ):
            raise CodeKnowledgeError("code_svn_range_invalid")
        with source_lock(self.database, source_id), self.database.unit_of_work():
            binding = self.content.binding(source_id)
            if binding["config_hash"] != config_hash or binding["collected_revision"] not in {
                None,
                after,
                target,
            }:
                raise CodeKnowledgeError("code_source_cursor_changed")
            self.store_commit_facts(source_id, config_hash, repository_uuid, commits)
            self.database.execute(
                f"update {table(self.database, 'code_binding')} set collected_revision=?,collected_from_revision=coalesce(collected_from_revision,?),updated_at=? where source_id=?",
                (target, after, now(), source_id),
            )

    def store_commit_facts(
        self, source_id: str, config_hash: str, repository_uuid: str, commits: list[dict[str, Any]]
    ) -> None:
        """Caller holds the source lock and transaction; no cursor movement."""
        for commit in commits:
            existing = self.database.execute_one(
                f"select repository_uuid,paths_json from {table(self.database, 'code_commit')} where source_id=? and config_hash=? and revision=?",
                (source_id, config_hash, commit["revision"]),
            )
            if existing and (
                existing["repository_uuid"] != repository_uuid
                or decoded(existing["paths_json"]) != commit["paths"]
            ):
                raise CodeKnowledgeError("code_svn_commit_conflict")
            insert(
                self.database,
                "code_commit",
                dict(
                    source_id=source_id,
                    config_hash=config_hash,
                    repository_uuid=repository_uuid,
                    revision=commit["revision"],
                    paths_json=commit["paths"],
                    complete=1,
                    analysis_state="PENDING",
                    created_at=now(),
                ),
                conflict="on conflict(source_id,config_hash,revision) do nothing",
            )

    def demand(
        self, source_id: str, revision: int, requester_id: str, *, manual: bool = False
    ) -> dict[str, Any]:
        if type(revision) is not int or revision < 0 or not requester_id:
            raise CodeKnowledgeError("code_history_request_invalid")
        with source_lock(self.database, source_id), self.database.unit_of_work():
            binding = self.content.binding(source_id)
            if not decoded(binding["config_json"]).get("svn_verified"):
                return {"status": "BASELINE_UNMAPPED"}
            if not binding["enabled"] or (not manual and not binding["demand_enabled"]):
                return {"status": "BUILD_REQUIRED"}
            key = stable_id("code_demand", source_id, binding["config_hash"], str(revision))
            existing = self.database.execute_one(
                f"select id,state from {table(self.database, 'code_demand')} where id=?", (key,)
            )
            if existing:
                return {
                    "status": "READY"
                    if existing["state"] == "READY"
                    else "VERSION_UNAVAILABLE"
                    if existing["state"] in {"UNAVAILABLE", "CANCELLED"}
                    else "BUILD_PENDING",
                    "demand_id": key,
                }
            count = self.database.execute_one(
                f"select count(*) as n from {table(self.database, 'code_demand')} where source_id=? and state='PENDING'",
                (source_id,),
            )
            if count and count["n"] >= 20:
                return {"status": "BUILD_REQUIRED", "reason": "queue_full"}
            insert(
                self.database,
                "code_demand",
                dict(
                    id=key,
                    source_id=source_id,
                    config_hash=binding["config_hash"],
                    revision=revision,
                    requester_id=requester_id,
                    state="PENDING",
                    created_at=now(),
                ),
            )
            return {"status": "BUILD_PENDING", "demand_id": key}


def _json(value: Any) -> str:
    from app.modules.knowledge.domain.normalization import canonical_json

    return canonical_json(value)


def _expiry(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value)) if value else datetime.min.replace(tzinfo=UTC)
