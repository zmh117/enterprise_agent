"""Current authorization for one internal extraction Job, never a model-selected mount."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from app.modules.knowledge.domain.code_contracts import (
    CONTRACT_VERSION,
    CodeKnowledgeError,
    COMPONENTS,
    CODE_SOURCE_GRANT_PATH as CODE_SOURCE_GRANT_PATH,
)
from app.modules.knowledge.domain.normalization import digest
from app.modules.knowledge.infrastructure.code_job_binding import extraction_unit
from app.modules.knowledge.infrastructure.code_repository import decoded
from app.modules.knowledge.infrastructure.code_source import relative_path
from app.modules.knowledge.infrastructure.storage import table
from app.shared.database import Database
from app.modules.knowledge.domain.code_identity_catalog import CATALOG_HASH, identity_catalog


class CurrentAuthorization(Protocol):
    def require(self, **kwargs: Any) -> dict[str, Any]: ...


class CodeSourceGrant:
    def __init__(self, database: Database, authorization: CurrentAuthorization) -> None:
        self.database = database
        self.authorization = authorization

    def for_job(self, job_id: str, *, completed: bool = False) -> dict[str, Any]:
        db = self.database
        row = db.execute_one(
            f"select u.id,b.lease_version from {table(db, 'code_unit')} u "
            f"join {table(db, 'code_build')} b on b.id=u.build_id where u.job_id=?",
            (job_id,),
        )
        if not row:
            raise CodeKnowledgeError("code_job_unbound")
        unit = extraction_unit(db, row["id"], row["lease_version"], completed=completed)
        # The controller lease may be reclaimed. The original Job remains the only
        # execution for this unit; its artifact binding never changes on takeover.
        if not unit["execution_lease_version"]:
            raise CodeKnowledgeError("code_unit_execution_lease_changed")
        config = decoded(unit["configuration_json"])
        if (
            config.get("contract_version") != CONTRACT_VERSION
            or config.get("identity_catalog_hash") != CATALOG_HASH
        ):
            raise CodeKnowledgeError("code_extraction_contract_changed")
        job = db.execute_one("select * from agent_job where id=?", (job_id,))
        if (
            not job
            or job["source_channel"] != "code_knowledge"
            or job["status"] != ("SUCCEEDED" if completed else "RUNNING")
        ):
            raise CodeKnowledgeError("code_job_inactive")
        bindings = {
            "internal_user_id": "service_account_id",
            "agent_publication_id": "agent_publication_id",
            "agent_config_hash": "agent_config_hash",
            "business_application_id": "application_id",
            "business_application_publication_id": "application_publication_id",
            "business_application_config_hash": "application_config_hash",
        }
        if any(not config.get(c) or job.get(j) != config[c] for j, c in bindings.items()):
            raise CodeKnowledgeError("code_job_binding_changed")
        user = db.execute_one(
            "select id from app_user where id=? and status='enabled' and account_type='service'",
            (job["internal_user_id"],),
        )
        if not user:
            raise CodeKnowledgeError("code_execution_identity_unavailable")
        self.authorization.require(
            user_id=job["internal_user_id"], application_id=job["business_application_id"]
        )
        scope = decoded(unit["scope_json"])
        prefixes = scope.get("allowed_prefixes")
        if not isinstance(prefixes, list) or not 1 <= len(prefixes) <= 100:
            raise CodeKnowledgeError("code_mount_scope_invalid")
        for prefix in prefixes:
            relative_path(prefix)
            if not any(
                prefix == root or prefix.startswith(root + "/") for root in COMPONENTS.values()
            ):
                raise CodeKnowledgeError("code_mount_scope_invalid")
        source = db.execute_one(
            f"select * from {table(db, 'code_source_snapshot')} where id=? and source_id=?",
            (unit["source_snapshot_id"], unit["source_id"]),
        )
        if (
            not source
            or source["retired_at"] is not None
            or source["config_hash"] != unit["config_hash"]
        ):
            raise CodeKnowledgeError("code_source_unavailable")
        exclusions = [
            entry
            for entry in decoded(source["manifest_json"]).get("excluded", [])
            if any(
                entry["path"] == prefix or entry["path"].startswith(prefix + "/")
                for prefix in prefixes
            )
        ]
        return {
            "job_id": job_id,
            "execution_identity": {
                "app_user_id": job["internal_user_id"],
                "agent_publication_id": job["agent_publication_id"],
                "application_publication_id": job["business_application_publication_id"],
            },
            "lease_version": unit["execution_lease_version"],
            "manifest_hash": source["manifest_hash"],
            "allowed_prefixes": prefixes,
            "scope": scope,
            "identity_catalog": identity_catalog(),
            "identity_catalog_hash": CATALOG_HASH,
            "source_exclusions": {
                "items": exclusions[:100],
                "total": len(exclusions),
                "truncated": len(exclusions) > 100,
            },
            "candidate_manifest": {
                "contract_version": CONTRACT_VERSION,
                "build_id": unit["build_id"],
                "work_unit_id": unit["id"],
                "source_snapshot_id": source["id"],
                "source_ref": decoded(source["source_ref"]),
                "scope_hash": digest(scope),
                "config_hash": unit["config_hash"],
            },
        }

    def check_invocation(self, value: dict[str, Any]) -> dict[str, Any]:
        if set(value) != {"job_id", "invocation_id", "request_digest"} or any(
            not isinstance(item, str) or not 1 <= len(item) <= 200 for item in value.values()
        ):
            raise CodeKnowledgeError("code_grant_request_invalid")
        invocation = self.database.execute_one(
            "select * from agent_runtime_invocation where invocation_id=? and job_id=? "
            "and request_digest=? and state='RUNNING' and cancel_requested_at is null "
            "and execution_quiesced_at is null",
            (value["invocation_id"], value["job_id"], value["request_digest"]),
        )
        if not invocation:
            raise CodeKnowledgeError("code_invocation_inactive")
        for field in ("lease_until", "execution_deadline_at"):
            timestamp = invocation[field]
            expiry = datetime.fromisoformat(timestamp) if isinstance(timestamp, str) else timestamp
            if not expiry or expiry <= datetime.now(UTC):
                raise CodeKnowledgeError("code_invocation_expired")
        grant = self.for_job(value["job_id"])
        if any(
            invocation[field] != expected for field, expected in grant["execution_identity"].items()
        ):
            raise CodeKnowledgeError("code_invocation_binding_mismatch")
        return grant
