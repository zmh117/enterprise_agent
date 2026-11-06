"""Standard Job dispatch and exact Runtime artifact collection for persisted work units."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.modules.job.application.create_agent_job_service import (
    CreateAgentJobCommand,
    CreateAgentJobService,
)
from app.modules.job.domain.agent_job import AgentJob
from app.modules.knowledge.infrastructure.code_source_grant import CodeSourceGrant
from app.modules.knowledge.domain.code_contracts import (
    CODE_INTERNAL_CONNECTOR_ID,
    CodeKnowledgeError,
    MAX_PACKAGE_BYTES,
)
from app.modules.knowledge.domain.code_package import (
    EvidenceSource,
    decode_package,
    verify_candidate,
)
from app.modules.knowledge.domain.identity import now
from app.modules.knowledge.domain.normalization import canonical_json
from app.modules.knowledge.infrastructure.code_artifact_directory import CodeArtifactDirectory
from app.modules.knowledge.infrastructure.code_snapshot_directory import CodeSnapshotDirectory
from app.modules.knowledge.infrastructure.code_job_binding import extraction_unit
from app.modules.knowledge.infrastructure.code_repository import CodeRepository, decoded
from app.modules.knowledge.infrastructure.code_source import _read_beneath
from app.modules.knowledge.infrastructure.storage import table
from app.modules.knowledge.infrastructure.code_fsm_repository import CodeStateMachineRepository
from app.shared.database import Database


class CodeExtractionJobs:
    def __init__(self, database: Database, jobs: CreateAgentJobService) -> None:
        self.database, self.jobs = database, jobs

    def dispatch(self, unit_id: str, lease: int) -> AgentJob:
        unit = extraction_unit(self.database, unit_id, lease)
        config = decoded(unit["configuration_json"])
        agent = self.database.execute_one(
            "select d.code,d.project_code from agent_publication p join agent_definition d "
            "on d.id=p.agent_id where p.id=?",
            (config.get("agent_publication_id"),),
        )
        application = self.database.execute_one(
            "select a.code,p.snapshot_json from business_application a join business_application_publication p "
            "on p.application_id=a.id where p.id=? and a.id=?",
            (config.get("application_publication_id"), config.get("application_id")),
        )
        if not agent or not application:
            raise CodeKnowledgeError("code_extraction_configuration_unavailable")
        with self.database.unit_of_work():
            current = extraction_unit(self.database, unit_id, lease, lock=True)
            if not current["job_id"]:
                build = self.database.execute_one(
                    f"select snapshot_id from {table(self.database, 'code_build')} where id=?",
                    (current["build_id"],),
                )
                assert build is not None
                scope = decoded(current["scope_json"])
                scope["known_states"] = CodeStateMachineRepository(self.database).known_states(
                    build["snapshot_id"]
                )
                if len(canonical_json(scope).encode("utf-8")) > 96 * 1024:
                    raise CodeKnowledgeError("code_scope_limit")
                self.database.execute(
                    f"update {table(self.database, 'code_unit')} set scope_json=? where id=?",
                    (canonical_json(scope), unit_id),
                )
        snapshot = decoded(application["snapshot_json"])
        command = CreateAgentJobCommand(
            idempotency_key="code-unit:" + unit_id,
            user_message="按 code_source.scope 和 inputs/code-contract.txt 提取指定业务知识，保留证据与未知项。",
            requester_id=config["service_account_id"],
            project_code=agent["project_code"],
            source_channel="code_knowledge",
            source_connector_id=CODE_INTERNAL_CONNECTOR_ID,
            reply_route={"type": "none"},
            agent_code=agent["code"],
            fixed_agent_publication_id=config["agent_publication_id"],
            fixed_agent_config_hash=config["agent_config_hash"],
            business_application_id=config["application_id"],
            business_application_code=application["code"],
            business_application_publication_id=config["application_publication_id"],
            business_application_config_hash=config["application_config_hash"],
            application_execution_policy=snapshot.get("execution_policy") or {},
            conversation_mode="channel",
            continuous_conversation_enabled=False,
        )
        result = self.jobs.execute_code_unit(command, unit_id=unit_id, lease_version=lease)
        if not isinstance(result, AgentJob):
            raise CodeKnowledgeError("code_extraction_job_required")
        return result


class CodeArtifactCollector:
    def __init__(
        self,
        database: Database,
        grants: CodeSourceGrant,
        *,
        source_root: Path,
        artifact_root: Path,
    ) -> None:
        self.database, self.grants = database, grants
        self.sources = CodeSnapshotDirectory(source_root)
        self.artifacts = CodeArtifactDirectory(artifact_root)

    def collect(self, unit_id: str, lease: int) -> dict[str, Any]:
        unit = extraction_unit(self.database, unit_id, lease, completed=True)
        grant = self.grants.for_job(unit["job_id"], completed=True)
        if unit["state"] == "VALIDATED":
            return dict(decoded(unit["result_json"]))
        binding = self._binding(unit["job_id"], grant)
        artifact, files = self.artifacts.read(binding)
        package = decode_package(files["candidate.txt"])
        evidence_sources = self._evidence_sources(package, grant)
        scope = decoded(unit["scope_json"])
        entry_ids = scope.get("entry_ids")
        if not isinstance(entry_ids, list) or not entry_ids:
            raise CodeKnowledgeError("code_unit_entries_missing")
        result = verify_candidate(
            package,
            expected_manifest=grant["candidate_manifest"],
            sources=evidence_sources,
            expected_entries=set(entry_ids),
            known_states=scope.get("known_states", []),
        )
        with self.database.unit_of_work():
            current = extraction_unit(self.database, unit_id, lease, completed=True, lock=True)
            if self.grants.for_job(unit["job_id"], completed=True) != grant:
                raise CodeKnowledgeError("code_artifact_binding_changed")
            if current["state"] == "VALIDATED":
                return dict(decoded(current["result_json"]))
            build = self.database.execute_one(
                f"select snapshot_id from {table(self.database, 'code_build')} where id=?",
                (unit["build_id"],),
            )
            assert build is not None
            if not result["dependency_requests"]:
                CodeRepository(self.database).store_candidate(build["snapshot_id"], package)
            self.database.execute(
                f"update {table(self.database, 'code_unit')} set state='VALIDATED',artifact_json=?,result_json=?,updated_at=? where id=?",
                (canonical_json(artifact), canonical_json(result), now(), unit_id),
            )
        return result

    def _binding(self, job_id: str, grant: dict[str, Any]) -> dict[str, Any]:
        invocation = self.database.execute_one(
            "select * from agent_runtime_invocation where job_id=? order by attempt desc limit 1",
            (job_id,),
        )
        if (
            not invocation
            or invocation["state"] != "TERMINAL"
            or invocation["terminal_code"] != "runtime_succeeded"
            or invocation["execution_quiesced_at"] is None
            or invocation["cancel_requested_at"] is not None
            or any(
                invocation[field] != expected
                for field, expected in grant["execution_identity"].items()
            )
        ):
            raise CodeKnowledgeError("code_artifact_terminal_unproven")
        return {key: invocation[key] for key in ("job_id", "invocation_id", "request_digest")} | {
            "grant": grant
        }

    def _evidence_sources(
        self, package: dict[str, Any], grant: dict[str, Any]
    ) -> dict[str, EvidenceSource]:
        identifier = grant["candidate_manifest"]["source_snapshot_id"]
        manifest = self.sources.verify(identifier, grant["manifest_hash"])
        files = {row["file_id"]: row for row in manifest["files"]}
        result = {}
        for evidence in package["evidence.jsonl"]:
            row = files.get(evidence["file_id"])
            if not row or not any(
                row["path"] == prefix or row["path"].startswith(prefix + "/")
                for prefix in grant["allowed_prefixes"]
            ):
                raise CodeKnowledgeError("code_evidence_source_unavailable")
            content = _read_beneath(
                self.sources.root / identifier, "text/" + row["path"], MAX_PACKAGE_BYTES
            )
            result[row["file_id"]] = EvidenceSource(
                row["path"], row["raw_hash"], row["representation_hash"], content.decode("utf-8")
            )
        return result
