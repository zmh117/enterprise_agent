"""Explicit administration of admitted sources and persisted extraction builds."""

from typing import Any
from datetime import UTC, datetime

from app.modules.knowledge.application.source_service import KnowledgeAdministration
from app.modules.knowledge.application.code_behavior import _bounded
from app.modules.knowledge.infrastructure.code_build_controller import review_digest
from app.modules.knowledge.application.code_schedule import next_daily
from app.modules.knowledge.domain.code_contracts import (
    CodeKnowledgeError,
    COMPONENTS,
    CONTRACT_VERSION,
)
from app.modules.knowledge.domain.governance import checked_identifier
from app.modules.knowledge.domain.identity import now
from app.modules.knowledge.domain.normalization import canonical_json, digest
from app.modules.knowledge.infrastructure.code_build_repository import CodeBuildRepository
from app.modules.knowledge.infrastructure.code_repository import CodeRepository, decoded
from app.modules.knowledge.infrastructure.storage import source_lock, table
from app.modules.knowledge.domain.code_identity_catalog import CATALOG_HASH
from app.shared.database import Database


class CodeKnowledgeOperations:
    def __init__(self, database: Database, admin: KnowledgeAdministration) -> None:
        self.db, self.admin = database, admin
        self.repo, self.builds = CodeRepository(database), CodeBuildRepository(database)

    def snapshot(self) -> dict[str, Any]:
        sources = self.db.execute(
            f"select b.source_id,b.knowledge_base_id,b.config_revision,b.enabled,b.demand_enabled,"
            f"b.collected_revision,b.collected_from_revision,b.active_snapshot_id,b.next_run_at,b.operations_json,b.collection_json,b.config_json,s.display_name "
            f"from {table(self.db, 'code_binding')} b join {table(self.db, 'source')} s on s.id=b.source_id order by b.source_id limit 21"
        )
        baselines = self.db.execute(
            f"select id,source_id,source_kind,svn_revision,manifest_hash,created_at,retired_at "
            f"from {table(self.db, 'code_source_snapshot')} order by created_at desc,id limit 101"
        )
        builds = self.db.execute(
            f"select b.id,b.source_id,b.source_snapshot_id,b.snapshot_id,b.purpose,b.stage,b.active,b.error_code,"
            f"b.created_at,b.updated_at,s.validation_json,s.processing_hash,"
            f"(select count(*) from {table(self.db, 'code_unit')} u where u.build_id=b.id) as unit_count,"
            f"(select count(*) from {table(self.db, 'code_unit')} u where u.build_id=b.id and u.state='VALIDATED') as validated_units "
            f"from {table(self.db, 'code_build')} b join {table(self.db, 'code_snapshot')} s on s.id=b.snapshot_id "
            "order by b.created_at desc,b.id limit 101"
        )
        for build in builds:
            build["validation"] = decoded(build.pop("validation_json"))
        for source in sources:
            config = decoded(source.pop("config_json"))
            operations = decoded(source.pop("operations_json"))
            collection = decoded(source.pop("collection_json"))
            source["svn_verified"] = bool(config.get("svn_verified"))
            source["svn_identity"] = config.get("svn_identity")
            source["plan"] = {k: v for k, v in operations.items() if k != "extraction"}
            source["collection"] = {k: v for k, v in collection.items() if k != "extraction"}
        demands = self.db.execute(
            f"select id,source_id,revision,state,build_id,created_at from {table(self.db, 'code_demand')} order by created_at desc,id limit 101"
        )
        histories = self.db.execute(
            f"select source_id,document_id,from_revision,to_revision,ledger_complete,comparison_json from {table(self.db, 'code_history_check')} order by to_revision desc,from_revision desc limit 51"
        )
        for history in histories:
            comparison = decoded(history.pop("comparison_json"))
            history.update(
                complete=comparison["complete"],
                checked_count=len(comparison["checked_revisions"]),
                unresolved_count=len(comparison["unresolved_intervals"]),
            )
        return {
            "components": COMPONENTS,
            "sources": sources[:20],
            "source_snapshots": baselines[:100],
            "builds": builds[:100],
            "demands": demands[:100],
            "history_checks": histories[:50],
            "partial": len(sources) > 20
            or len(baselines) > 100
            or len(builds) > 100
            or len(demands) > 100
            or len(histories) > 50,
        }

    def configure_plan(
        self,
        *,
        actor_id: str,
        source_id: str,
        expected_plan_revision: int,
        application_publication_id: str,
        service_account_id: str,
        schedule_enabled: bool,
        demand_enabled: bool,
        local_time: str = "02:00",
        timezone: str = "Asia/Shanghai",
    ) -> dict[str, Any]:
        self.admin.require_admin(actor_id)
        if (
            type(schedule_enabled) is not bool
            or type(demand_enabled) is not bool
            or type(expected_plan_revision) is not int
        ):
            raise CodeKnowledgeError("code_schedule_invalid")
        next_run = next_daily(datetime.now(UTC), local_time, timezone)
        extraction = self._configuration(application_publication_id, service_account_id)
        with source_lock(self.db, source_id), self.db.unit_of_work():
            self.admin.require_admin(actor_id)
            binding = self.repo.binding(source_id)
            if not decoded(binding["config_json"]).get("svn_verified"):
                raise CodeKnowledgeError("code_svn_unverified")
            prior = decoded(binding["operations_json"])
            if prior.get("revision", 0) != expected_plan_revision:
                raise CodeKnowledgeError("code_schedule_changed")
            plan = {
                **prior,
                "revision": expected_plan_revision + 1,
                "extraction": extraction,
                "application_publication_id": application_publication_id,
                "service_account_id": service_account_id,
                "schedule": {
                    "enabled": schedule_enabled,
                    "local_time": local_time,
                    "timezone": timezone,
                },
            }
            self.db.execute(
                f"update {table(self.db, 'code_binding')} set operations_json=?,enabled=1,demand_enabled=?,next_run_at=?,updated_at=? where source_id=?",
                (
                    canonical_json(plan),
                    int(demand_enabled),
                    next_run if schedule_enabled else None,
                    now(),
                    source_id,
                ),
            )
            self.admin.record(
                "code_plan_configured",
                actor_id=actor_id,
                identifier=source_id,
                revision=expected_plan_revision + 1,
            )
            return {
                "plan_revision": expected_plan_revision + 1,
                "next_run_at": next_run if schedule_enabled else None,
            }

    def request_version(self, *, actor_id: str, source_id: str, revision: int) -> dict[str, Any]:
        self.admin.require_admin(actor_id)
        with source_lock(self.db, source_id), self.db.unit_of_work():
            result = self.builds.demand(source_id, revision, actor_id, manual=True)
            self.admin.record(
                "code_version_requested", actor_id=actor_id, identifier=source_id, revision=revision
            )
            return result

    def bind_site(
        self,
        *,
        actor_id: str,
        source_id: str,
        site_id: str,
        snapshot_id: str,
        expected_plan_revision: int,
    ) -> dict[str, Any]:
        self.admin.require_admin(actor_id)
        checked_identifier(site_id)
        with source_lock(self.db, source_id), self.db.unit_of_work():
            binding = self.repo.binding(source_id)
            snapshot = self.repo.snapshot(binding["knowledge_base_id"], snapshot_id)
            if (
                snapshot["config_hash"] != binding["config_hash"]
                or snapshot["source_kind"] != "svn"
            ):
                raise CodeKnowledgeError("code_site_version_unavailable")
            operations = decoded(binding["operations_json"])
            if operations.get("revision", 0) != expected_plan_revision:
                raise CodeKnowledgeError("code_schedule_changed")
            sites = operations.get("sites", {})
            if site_id not in sites and len(sites) >= 100:
                raise CodeKnowledgeError("code_site_binding_limit")
            sites[site_id] = {
                "snapshot_id": snapshot_id,
                "revision": snapshot["svn_revision"],
                "updated_at": now(),
            }
            operations = {**operations, "sites": sites, "revision": expected_plan_revision + 1}
            self.db.execute(
                f"update {table(self.db, 'code_binding')} set operations_json=?,updated_at=? where source_id=?",
                (canonical_json(operations), now(), source_id),
            )
            self.admin.record(
                "code_site_version_bound",
                actor_id=actor_id,
                identifier=source_id,
                revision=snapshot["svn_revision"],
            )
            return {"site_id": site_id, **sites[site_id]}

    def retry_collection(self, *, actor_id: str, source_id: str) -> dict[str, Any]:
        self.admin.require_admin(actor_id)
        with source_lock(self.db, source_id), self.db.unit_of_work():
            binding = self.repo.binding(source_id)
            state = decoded(binding["collection_json"])
            if state.get("state") != "FAILED":
                raise CodeKnowledgeError("code_collection_not_retryable")
            state.update(
                state="COLLECTING" if state["purpose"] == "daily" else "FREEZING", error_code=None
            )
            self.db.execute(
                f"update {table(self.db, 'code_binding')} set collection_json=?,updated_at=? where source_id=?",
                (canonical_json(state), now(), source_id),
            )
            self.admin.record(
                "code_collection_retried",
                actor_id=actor_id,
                identifier=source_id,
                revision=state["target_revision"],
            )
            return {"source_id": source_id, "state": state["state"]}

    def start(
        self,
        *,
        actor_id: str,
        source_id: str,
        source_snapshot_id: str,
        application_publication_id: str,
        service_account_id: str,
    ) -> dict[str, str]:
        self.admin.require_admin(actor_id)
        for value in (
            source_id,
            source_snapshot_id,
            application_publication_id,
            service_account_id,
        ):
            checked_identifier(value)
        config = self._configuration(application_publication_id, service_account_id)
        with source_lock(self.db, source_id), self.db.unit_of_work():
            self.admin.require_admin(actor_id)
            source = self.db.execute_one(
                f"select source_kind from {table(self.db, 'code_source_snapshot')} where id=? and source_id=?",
                (source_snapshot_id, source_id),
            )
            if not source:
                raise CodeKnowledgeError("code_source_unavailable")
            result = self.repo.new_build(
                source_id,
                source_snapshot_id,
                purpose="baseline" if source["source_kind"] == "local_bundle" else "release",
                configuration=config,
            )
            self.admin.record(
                "code_build_requested", actor_id=actor_id, identifier=result["build_id"], revision=0
            )
            return result

    def _configuration(self, application_id: str, account_id: str) -> dict[str, Any]:
        account = self.db.execute_one(
            "select id from app_user where id=? and account_type='service' and status='enabled'",
            (account_id,),
        )
        application = self.db.execute_one(
            "select p.application_id,p.config_hash,p.snapshot_json from business_application_publication p "
            "join business_application a on a.id=p.application_id where p.id=? and a.status='enabled'",
            (application_id,),
        )
        if not account or not application:
            raise CodeKnowledgeError("code_extraction_configuration_unavailable")
        app = decoded(application["snapshot_json"])
        agent_id = app.get("agent", {}).get("id")
        agent = self.db.execute_one(
            "select config_hash,snapshot_json from agent_publication where id=?", (agent_id,)
        )
        snapshot = decoded(agent["snapshot_json"]) if agent else {}
        skill = snapshot.get("versioned_skills", {}).get("extract-business-knowledge")
        if not agent or not skill or "extract-business-knowledge" not in snapshot.get("skills", []):
            raise CodeKnowledgeError("code_extraction_skill_unpublished")
        # Standard Job creation independently verifies publications, current service
        # account/application authorization and Runtime admission before model use.
        return dict(
            application_id=application["application_id"],
            application_publication_id=application_id,
            application_config_hash=application["config_hash"],
            agent_publication_id=agent_id,
            agent_config_hash=agent["config_hash"],
            service_account_id=account_id,
            skill_hash=digest(skill),
            contract_version=CONTRACT_VERSION,
            identity_catalog_hash=CATALOG_HASH,
        )

    def details(self, build_id: str, *, after: str = "") -> dict[str, Any]:
        from app.modules.knowledge.infrastructure.code_fsm_repository import (
            CodeStateMachineRepository,
        )

        checked_identifier(build_id)
        if after:
            checked_identifier(after)
        build = self.builds.get(build_id)
        rows = self.db.execute(
            f"select m.document_id,r.id as revision_id,r.attributes from {table(self.db, 'code_member')} m "
            f"join {table(self.db, 'document_revision')} r on r.id=m.revision_id and r.document_id=m.document_id "
            "where m.snapshot_id=? and m.document_id>? order by m.document_id limit 11",
            (build["snapshot_id"], after),
        )
        units = self.db.execute(
            f"select id,unit_key,state,job_id,result_json,artifact_json from {table(self.db, 'code_unit')} where build_id=? order by unit_key limit 25",
            (build_id,),
        )
        candidate_digest = review_digest(units)
        for unit in units:
            unit["result"] = decoded(unit.pop("result_json")) or {}
            unit.pop("artifact_json")
            unit["error_code"] = None
        relations = self.db.execute(
            f"select relation_json from {table(self.db, 'code_relation')} where snapshot_id=? "
            f"and from_document_id in (select document_id from {table(self.db, 'code_member')} "
            "where snapshot_id=? and document_id>? order by document_id limit 10) order by relation_id limit 1001",
            (build["snapshot_id"], build["snapshot_id"], after),
        )
        if len(relations) > 1000:
            raise CodeKnowledgeError("code_review_relations_limit")
        records = []
        for row in rows[:10]:
            attributes = decoded(row["attributes"])
            if attributes["contract_version"] != CONTRACT_VERSION:
                raise CodeKnowledgeError("code_contract_version_retired")
            if attributes["knowledge"]["kind"] == "transition":
                attributes["knowledge"] = CodeStateMachineRepository(self.db).read(
                    build["snapshot_id"],
                    row["document_id"],
                    row["revision_id"],
                    attributes["knowledge"],
                )
            records.append(
                dict(knowledge_id=row["document_id"], revision_id=row["revision_id"], **attributes)
            )
        result = dict(
            build_id=build_id,
            snapshot_id=build["snapshot_id"],
            units=units,
            review_digest=candidate_digest,
            relations=[decoded(row["relation_json"]) for row in relations],
            records=records,
            has_more=len(rows) > 10,
            next_cursor=rows[9]["document_id"] if len(rows) > 10 else None,
        )
        _bounded(result)
        return result

    def review(
        self,
        *,
        actor_id: str,
        build_id: str,
        review_reference: str,
        processing_hash: str,
        candidate_digest: str,
        checked_unit_ids: list[str],
    ) -> dict[str, Any]:
        self.admin.require_admin(actor_id)
        checked_identifier(review_reference)
        if (
            not isinstance(checked_unit_ids, list)
            or not 1 <= len(checked_unit_ids) <= 24
            or len(set(checked_unit_ids)) != len(checked_unit_ids)
        ):
            raise CodeKnowledgeError("code_review_units_invalid")
        build = self.builds.get(build_id)
        with source_lock(self.db, build["source_id"]), self.db.unit_of_work():
            self.admin.require_admin(actor_id)
            build = self.builds.get(build_id)
            snapshot = self.repo.snapshot(
                self.repo.binding(build["source_id"])["knowledge_base_id"],
                build["snapshot_id"],
                ready=False,
            )
            if build["stage"] != "VALIDATING" or snapshot["processing_hash"] != processing_hash:
                raise CodeKnowledgeError("code_review_version_changed")
            units = self.db.execute(
                f"select id,state,result_json,artifact_json from {table(self.db, 'code_unit')} where build_id=? order by unit_key limit 25",
                (build_id,),
            )
            if not 1 <= len(units) <= 24 or any(row["state"] != "VALIDATED" for row in units):
                raise CodeKnowledgeError("code_review_units_incomplete")
            if candidate_digest != review_digest(units):
                raise CodeKnowledgeError("code_review_candidate_changed")
            active = [
                (row["id"], decoded(row["result_json"]))
                for row in units
                if not decoded(row["result_json"]).get("replacement_unit_id")
            ]
            if set(checked_unit_ids) != {key for key, _ in active} or any(
                not row.get("machine_valid") or row.get("activation_blocked", True)
                for _, row in active
            ):
                raise CodeKnowledgeError("code_review_validation_incomplete")
            validation = decoded(snapshot["validation_json"])
            if not validation.get("machine_valid") or validation.get("activation_blocked", True):
                raise CodeKnowledgeError("code_review_validation_incomplete")
            validation.update(
                business_verified=True,
                business_review={
                    "reviewer_id": actor_id,
                    "reference": review_reference,
                    "checked_at": now(),
                    "unit_digest": review_digest(units),
                },
            )
            self.db.execute(
                f"update {table(self.db, 'code_snapshot')} set validation_json=? where id=?",
                (canonical_json(validation), build["snapshot_id"]),
            )
            self.admin.record(
                "code_business_reviewed", actor_id=actor_id, identifier=build_id, revision=0
            )
            return {"build_id": build_id, "validation": validation}

    def retry(self, *, actor_id: str, build_id: str) -> dict[str, str]:
        self.admin.require_admin(actor_id)
        build = self.builds.get(build_id)
        with source_lock(self.db, build["source_id"]), self.db.unit_of_work():
            self.admin.require_admin(actor_id)
            build = self.builds.get(build_id)
            configuration = decoded(build["configuration_json"])
            if (
                configuration.get("contract_version") != CONTRACT_VERSION
                or configuration.get("identity_catalog_hash") != CATALOG_HASH
            ):
                raise CodeKnowledgeError("code_contract_version_retired")
            if (
                build["stage"] not in {"FAILED", "INTERRUPTED"}
                or build["config_hash"] != self.repo.binding(build["source_id"])["config_hash"]
            ):
                raise CodeKnowledgeError("code_build_not_retryable")
            snapshot = self.repo.snapshot(
                self.repo.binding(build["source_id"])["knowledge_base_id"],
                build["snapshot_id"],
                ready=False,
            )
            if snapshot["state"] == "READY":
                raise CodeKnowledgeError("code_ready_snapshot_use_rollback")
            units = self.db.execute(
                f"select u.state,j.status as job_status from {table(self.db, 'code_unit')} u left join agent_job j on j.id=u.job_id where u.build_id=?",
                (build_id,),
            )
            unknown = self.db.execute_one(
                f"select i.invocation_id from agent_runtime_invocation i join {table(self.db, 'code_unit')} u on u.job_id=i.job_id where u.build_id=? and i.execution_quiesced_at is null and i.state<>'PREPARED' limit 1",
                (build_id,),
            )
            if unknown or any(row["job_status"] not in {None, "SUCCEEDED"} for row in units):
                raise CodeKnowledgeError("code_retry_execution_unresolved")
            stage = (
                "VALIDATING"
                if units and all(row["state"] == "VALIDATED" for row in units)
                else "EXTRACTING"
                if units
                else "QUEUED"
            )
            self.db.execute(
                f"update {table(self.db, 'code_build')} set stage=?,active=0,error_code=null,lease_until=null,updated_at=? where id=?",
                (stage, now(), build_id),
            )
            # Candidate artifact and deterministic vector checkpoint are retained.
            self.db.execute(
                f"update {table(self.db, 'code_demand')} set state='BUILDING' where build_id=? and state='UNAVAILABLE'",
                (build_id,),
            )
            self.admin.record(
                "code_build_retried", actor_id=actor_id, identifier=build_id, revision=0
            )
            return {"build_id": build_id, "stage": stage}

    def rollback(
        self, *, actor_id: str, source_id: str, snapshot_id: str, expected_current: str
    ) -> dict[str, str]:
        self.admin.require_admin(actor_id)
        with source_lock(self.db, source_id), self.db.unit_of_work():
            self.admin.require_admin(actor_id)
            self.builds.rollback(source_id, snapshot_id, expected_active=expected_current)
            self.admin.record(
                "code_snapshot_rolled_back", actor_id=actor_id, identifier=snapshot_id, revision=0
            )
            return {"source_id": source_id, "snapshot_id": snapshot_id}
