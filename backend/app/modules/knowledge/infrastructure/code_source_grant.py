"""Frozen code capability and current original-Job source occupancy; metadata only."""

from datetime import timedelta
from typing import Any

from app.modules.agent.infrastructure.runtime_pool_store import (
    RuntimePoolStore,
    database_now,
    timestamp,
)
from app.modules.authorization_center.application.service import BusinessAuthorizationService
from app.modules.knowledge.application.resource_service import KnowledgeResourceReader
from app.modules.knowledge.domain.code_answers import (
    CodeAnalysisContext,
    code_authorization_hash,
    utc_time,
)
from app.modules.knowledge.domain.code_contracts import (
    CodeKnowledgeError,
    CODE_SOURCE_GRANT_PATH as CODE_SOURCE_GRANT_PATH,
)
from app.modules.knowledge.domain.normalization import digest
from app.modules.knowledge.infrastructure.code_answer_store import CodeAnswerStore
from app.modules.knowledge.infrastructure.code_checkout_store import json_value
from app.modules.knowledge.infrastructure.job_access import KnowledgeJobGate
from app.modules.mcp_tool_runtime.job_snapshot import JobMcpToolSnapshotService
from app.shared.database import Database


class CodeSourceGrant:
    def __init__(
        self,
        database: Database,
        authorization: BusinessAuthorizationService,
        resources: KnowledgeResourceReader,
    ) -> None:
        self.database = database
        self.gate = KnowledgeJobGate(database, JobMcpToolSnapshotService(database), authorization)
        self.resources = resources
        self.store = CodeAnswerStore(database)

    def for_job(self, job_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "SELECT internal_user_id FROM agent_job WHERE id=?", (job_id,)
        )
        if not row:
            raise CodeKnowledgeError("CODE_EXECUTION_MISMATCH")
        access = self.gate.resolve(job_id=job_id, actor_id=row["internal_user_id"])
        frozen = self.gate.snapshots.verify(job_id)["snapshot"]["tools"]
        if "knowledge_svn_update" not in {item["tool_identifier"] for item in frozen}:
            raise CodeKnowledgeError("CODE_SOURCE_CAPABILITY_DENIED")
        sources = []
        for base_id in sorted(access.knowledge_base_ids):
            base = self.resources.store.get("knowledge_base", base_id)
            if base.get("kind") != "code":
                continue
            pin = self.resources.resolve(base_id)
            config = self.resources.store.code_configuration(pin.revision_id)
            sources.append(
                dict(
                    knowledge_base_id=base_id,
                    config_revision_id=pin.revision_id,
                    source_id=pin.source_id,
                    checkout_id=config["checkout_id"],
                    resource_fingerprint=pin.fingerprint,
                    allowed_paths=config["allowed_paths_json"],
                )
            )
            if len(sources) > 50:
                raise CodeKnowledgeError("CODE_SOURCE_CAPABILITY_LIMIT")
        value = dict(
            contract="code-source-capability/v2",
            job_id=job_id,
            actor_id=access.actor_id,
            authorization_hash=code_authorization_hash(access),
            sources=sources,
            native_tools=["Read", "Glob", "Grep"],
        )
        return {**value, "capability_hash": digest(value)}

    def _invocation(self, value: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        identity = {k: value.get(k) for k in ("job_id", "invocation_id", "request_digest")}
        if any(not isinstance(v, str) or not 1 <= len(v) <= 200 for v in identity.values()):
            raise CodeKnowledgeError("CODE_GRANT_REQUEST_INVALID")
        typed_identity = {k: str(v) for k, v in identity.items()}
        pool = RuntimePoolStore(self.database)
        invocation = pool.require(typed_identity["invocation_id"], typed_identity["request_digest"])
        current = database_now(self.database)
        if (
            invocation["job_id"] != typed_identity["job_id"]
            or invocation["state"] != "RUNNING"
            or invocation["cancel_requested_at"] is not None
            or invocation["execution_quiesced_at"] is not None
            or any(
                utc_time(invocation[field]) <= current
                for field in ("lease_until", "execution_deadline_at")
            )
        ):
            raise CodeKnowledgeError("CODE_EXECUTION_ENDED")
        # Frozen request is authenticated by its digest and never returned as a whole.
        request = pool.request(typed_identity["invocation_id"])
        frozen = request["prompt"]["retrieved_context"].get("code_source")
        capability = self.for_job(typed_identity["job_id"])
        if frozen != capability:
            raise CodeKnowledgeError("CODE_SOURCE_CAPABILITY_CHANGED")
        return invocation, capability

    def check_invocation(self, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict) or set(value) - {
            "job_id",
            "invocation_id",
            "request_digest",
            "action",
            "analysis_id",
            "evidence",
        }:
            raise CodeKnowledgeError("CODE_GRANT_REQUEST_INVALID")
        invocation, capability = self._invocation(value)
        action = value.get("action", "capability")
        if action == "capability" and set(value) <= {
            "job_id",
            "invocation_id",
            "request_digest",
            "action",
        }:
            return capability
        if action not in {"grant", "heartbeat", "quiesce", "evidence"} or not isinstance(
            value.get("analysis_id"), str
        ):
            raise CodeKnowledgeError("CODE_GRANT_REQUEST_INVALID")
        analysis = self.store.row("code_analysis", value["analysis_id"])
        if (
            analysis["invocation_id"] != invocation["invocation_id"]
            or analysis["owner_instance_id"] != invocation["instance_id"]
            or analysis["job_id"] != invocation["job_id"]
        ):
            raise CodeKnowledgeError("CODE_EXECUTION_MISMATCH")
        sources = [
            s
            for s in capability["sources"]
            if all(
                analysis[k] == s[k]
                for k in ("knowledge_base_id", "config_revision_id", "source_id", "checkout_id")
            )
        ]
        if len(sources) != 1:
            raise CodeKnowledgeError("CODE_SOURCE_CAPABILITY_CHANGED")
        context = CodeAnalysisContext(
            **{
                key: analysis[key]
                for key in (
                    "job_id",
                    "invocation_id",
                    "owner_instance_id",
                    "knowledge_base_id",
                    "config_revision_id",
                    "source_id",
                    "checkout_id",
                    "exact_search_id",
                    "question_hash",
                    "authorization_hash",
                )
            },
            actor_id=invocation["app_user_id"],
            revision=analysis["requested_revision"],
            deadline_at=utc_time(analysis["deadline_at"]).isoformat(),
        )
        if action == "heartbeat":
            with self.database.unit_of_work():
                self.store._owner(context)
                self.store._configuration(context)
                self.store.row("code_checkout", context.checkout_id, lock=True)
                current_analysis = self.store.row("code_analysis", analysis["id"], lock=True)
                self.store._bound(context, current_analysis)
                current = database_now(self.database)
                if (
                    current_analysis["state"] not in {"reading", "validating"}
                    or current_analysis["read_released_at"] is not None
                    or current_analysis["lease_until"] is None
                    or utc_time(current_analysis["lease_until"]) <= current
                ):
                    raise CodeKnowledgeError("CODE_READ_GRANT_EXPIRED")
                if current_analysis["state"] == "reading":
                    self.store.require_reader(context, analysis["id"])
                self.database.execute(
                    f"UPDATE {self.store.t('code_analysis')} SET lease_until=?,updated_at=? WHERE id=?",
                    (
                        timestamp(
                            min(current + timedelta(seconds=30), utc_time(context.deadline_at))
                        ),
                        timestamp(current),
                        analysis["id"],
                    ),
                )
                return {"renewed": True, "analysis_id": analysis["id"]}
        if action == "quiesce":
            stopped = self.store.finalizing(context, analysis["id"])
            return {"analysis_id": analysis["id"], "state": stopped["state"]}
        with self.database.unit_of_work():
            reader = self.store.require_reader(context, analysis["id"])
            current = database_now(self.database)
            self.database.execute(
                f"UPDATE {self.store.t('code_analysis')} SET lease_until=?,updated_at=? WHERE id=?",
                (
                    timestamp(min(current + timedelta(seconds=30), utc_time(context.deadline_at))),
                    timestamp(current),
                    analysis["id"],
                ),
            )
            if action == "evidence":
                from app.modules.knowledge.infrastructure.code_evidence_store import (
                    record_runtime_evidence,
                )

                return record_runtime_evidence(self.store, context, analysis, value.get("evidence"))
            checkout = self.store.row("code_checkout", context.checkout_id)
            repository = self.database.execute_one(
                f"SELECT repository_uuid,branch_path FROM {self.store.t('code_repository')} WHERE source_id=?",
                (context.source_id,),
            )
            assert repository is not None
            repository["repository_uuid"] = str(repository["repository_uuid"])
            return dict(
                contract="code-source-grant/v2",
                capability_hash=capability["capability_hash"],
                analysis_id=analysis["id"],
                source_id=context.source_id,
                checkout_id=context.checkout_id,
                revision=context.revision,
                generation=reader["generation"],
                directory=checkout["relative_dir"],
                physical_key=checkout["physical_key"],
                selected_paths=json_value(checkout["selected_paths_json"]),
                allowed_paths=sources[0]["allowed_paths"],
                deadline_at=context.deadline_at,
                **repository,
            )
