"""Trusted controller-to-Job binding; no model-supplied grant or source path."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.modules.knowledge.domain.code_contracts import (
    CodeKnowledgeError,
    CODE_INTERNAL_CONNECTOR_ID,
    CONTRACT_VERSION,
)
from app.modules.knowledge.domain.code_identity_catalog import CATALOG_HASH
from app.modules.knowledge.domain.identity import now
from app.modules.knowledge.infrastructure.code_repository import decoded
from app.modules.knowledge.infrastructure.storage import table
from app.shared.database import Database


def extraction_unit(
    database: Database,
    unit_id: str,
    lease_version: int,
    *,
    lock: bool = False,
    completed: bool = False,
) -> dict[str, Any]:
    locking = " for update of u,b,c" if lock and database.engine == "postgres" else ""
    row = database.execute_one(
        f"select u.*,b.source_id,b.source_snapshot_id,b.config_hash,b.configuration_json,b.stage,"
        f"b.active,b.lease_version,b.lease_until,c.config_hash as current_config_hash,c.knowledge_base_id "
        f"from {table(database, 'code_unit')} u join {table(database, 'code_build')} b on b.id=u.build_id "
        f"join {table(database, 'code_binding')} c on c.source_id=b.source_id where u.id=?"
        + locking,
        (unit_id,),
    )
    if not row:
        raise CodeKnowledgeError("code_unit_unavailable")
    expires = row["lease_until"]
    if isinstance(expires, str):
        expires = datetime.fromisoformat(expires)
    if (
        row["stage"] != "EXTRACTING"
        or not row["active"]
        or row["lease_version"] != lease_version
        or not expires
        or expires <= datetime.now(UTC)
        or row["config_hash"] != row["current_config_hash"]
        or row["state"]
        not in ({"RUNNING", "SUBMITTED", "VALIDATED"} if completed else {"QUEUED", "RUNNING"})
    ):
        raise CodeKnowledgeError("code_unit_execution_denied")
    return row


def validate_internal_command(
    database: Database, command: Any, unit_id: str, lease: int, *, lock: bool = False
) -> dict[str, Any]:
    unit = extraction_unit(database, unit_id, lease, lock=lock)
    if unit["job_id"] and unit["execution_lease_version"] != lease:
        raise CodeKnowledgeError("code_unit_execution_lease_changed")
    config = decoded(unit["configuration_json"])
    if (
        config.get("contract_version") != CONTRACT_VERSION
        or config.get("identity_catalog_hash") != CATALOG_HASH
    ):
        raise CodeKnowledgeError("code_extraction_contract_changed")
    expected = {
        "requester_id": "service_account_id",
        "fixed_agent_publication_id": "agent_publication_id",
        "fixed_agent_config_hash": "agent_config_hash",
        "business_application_id": "application_id",
        "business_application_publication_id": "application_publication_id",
        "business_application_config_hash": "application_config_hash",
    }
    if any(
        not config.get(field) or getattr(command, attribute) != config[field]
        for attribute, field in expected.items()
    ):
        raise CodeKnowledgeError("code_job_publication_mismatch")
    if (
        command.source_channel != "code_knowledge"
        or command.source_connector_id != CODE_INTERNAL_CONNECTOR_ID
        or command.effective_reply_route.get("type") != "none"
        or command.attachments
        or command.file_references
        or command.idempotency_key != "code-unit:" + unit_id
    ):
        raise CodeKnowledgeError("code_job_boundary_invalid")
    user = database.execute_one(
        "select id from app_user where id=? and status='enabled' and account_type='service'",
        (command.requester_id,),
    )
    if not user:
        raise CodeKnowledgeError("code_execution_identity_unavailable")
    publication = database.execute_one(
        "select snapshot_json,config_hash from agent_publication where id=?",
        (command.fixed_agent_publication_id,),
    )
    snapshot = decoded(publication["snapshot_json"]) if publication else {}
    if (
        not publication
        or publication["config_hash"] != command.fixed_agent_config_hash
        or "extract-business-knowledge" not in (snapshot.get("skills") or [])
        or not snapshot.get("versioned_skills", {}).get("extract-business-knowledge")
    ):
        raise CodeKnowledgeError("code_extraction_skill_unpublished")
    return unit


def bind_internal_job(database: Database, unit: dict[str, Any], job_id: str) -> None:
    if unit["job_id"] and unit["job_id"] != job_id:
        raise CodeKnowledgeError("code_unit_job_conflict")
    rows = database.execute(
        f"update {table(database, 'code_unit')} set job_id=?,execution_lease_version=?,state='RUNNING',updated_at=? "
        "where id=? and (job_id is null or job_id=?) returning id",
        (job_id, unit["lease_version"], now(), unit["id"], job_id),
    )
    if not rows:
        raise CodeKnowledgeError("code_unit_job_conflict")
