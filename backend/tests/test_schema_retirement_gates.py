from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

from app.shared.schema_fact_sources import load_fact_source_manifest
from app.shared.schema_retirement import (
    RetirementEvidenceError,
    load_retirement_decisions,
    validate_retirement_evidence,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SHARED_ROOT = REPOSITORY_ROOT / "backend" / "app" / "shared"


def test_each_outbox_has_one_declared_transaction_boundary_writer() -> None:
    manifest = load_fact_source_manifest()
    entries = {entry["id"]: entry for entry in manifest["entries"]}
    expected = {
        "outbox.webhook": (
            "webhook_outbox",
            "backend/app/modules/webhook/infrastructure/event_repository.py",
        ),
        "outbox.channel_ingress": (
            "channel_ingress_outbox",
            "backend/app/modules/managed_channel/infrastructure/repository.py",
        ),
        "outbox.job_dispatch": (
            "job_dispatch_outbox",
            "backend/app/modules/job/infrastructure/repositories.py",
        ),
        "outbox.delivery": (
            "delivery_outbox",
            "backend/app/modules/job/infrastructure/repositories.py",
        ),
    }

    for identifier, (table, writer_path) in expected.items():
        entry = entries[identifier]
        assert entry["classification"] == "operational_coordination_fact"
        assert entry["retirement"]["status"] == "retained"
        declared_paths = {
            value.removeprefix("code:")
            for value in entry["writers"]
            if value.startswith("code:")
        }
        assert writer_path in declared_paths
        actual_insert_writers = {
            str(path.relative_to(REPOSITORY_ROOT))
            for path in (REPOSITORY_ROOT / "backend" / "app").rglob("*.py")
            if f"insert into {table}" in path.read_text(encoding="utf-8").lower()
        }
        assert actual_insert_writers == {writer_path}


def test_runtime_identity_publication_and_audit_facts_remain_retained() -> None:
    manifest = load_fact_source_manifest()
    by_id = {entry["id"]: entry for entry in manifest["entries"]}

    for identifier in (
        "runtime.terminal_ledger",
        "runtime.invocation_claim",
        "runtime.invocation_event",
        "identity.ones_challenge",
        "publication.agent",
        "publication.business_application",
        "workflow.publication",
        "audit.general",
        "audit.identity_migration",
        "audit.platform_config",
    ):
        assert by_id[identifier]["retirement"]["status"] == "retained"
        assert by_id[identifier]["retirement"]["earliest_phase"] == "never"

    consolidation_source = (SHARED_ROOT / "schema_consolidation.py").read_text(
        encoding="utf-8"
    ).lower()
    for sensitive_column in (
        "teams_json",
        "events_json",
        "snapshot_json",
        "payload_summary",
        "request_payload",
        "response_summary",
    ):
        assert sensitive_column not in consolidation_source


def _complete_evidence() -> dict[str, object]:
    environment = {
        "cutover_complete": True,
        "retention_satisfied": True,
        "backup_verified": True,
        "retry_recovery_cycle_observed": True,
        "production_release_cycle_observed": True,
        "unresolved_count": 0,
        "legacy_reader_count": 0,
        "legacy_writer_count": 0,
    }
    return {
        "candidate": "job_dispatch_cutover_quarantine",
        "owner": "job-operations",
        "environments": [
            {"name": "staging", **environment},
            {"name": "production", **environment},
        ],
        "evidence_basis": [
            "runtime_telemetry",
            "release_inventory",
            "retry_recovery_acceptance",
        ],
        "approvals": {
            "domain": True,
            "runtime": True,
            "database": True,
            "security_audit": True,
            "operations": True,
        },
        "audit_export_complete": True,
    }


@pytest.mark.parametrize(
    "mutation",
    (
        "zero-only",
        "single-environment",
        "missing-environment",
    ),
)
def test_retirement_evidence_rejects_weak_or_partial_bases(mutation: str) -> None:
    evidence = _complete_evidence()
    required = frozenset({"staging", "production"})
    if mutation == "zero-only":
        evidence["evidence_basis"] = ["zero_rows", "legacy_name", "local_static_search"]
    elif mutation == "single-environment":
        evidence["environments"] = list(evidence["environments"])[:1]  # type: ignore[arg-type]
        required = frozenset({"staging"})
    else:
        evidence["environments"] = list(evidence["environments"])[:1]  # type: ignore[arg-type]

    with pytest.raises(RetirementEvidenceError):
        validate_retirement_evidence(evidence, required_environments=required)


def test_retirement_evidence_records_unmet_gates_as_blocked() -> None:
    evidence = _complete_evidence()
    evidence["approvals"] = {"domain": True}

    decision = validate_retirement_evidence(
        evidence,
        required_environments=frozenset({"staging", "production"}),
    )

    assert decision.status == "blocked"
    assert "approval:runtime" in decision.unmet_conditions
    assert "approval:operations" in decision.unmet_conditions


def test_retirement_evidence_requires_all_gates_for_approval() -> None:
    decision = validate_retirement_evidence(
        _complete_evidence(),
        required_environments=frozenset({"staging", "production"}),
    )

    assert decision.status == "approved"
    assert decision.unmet_conditions == ()


def test_quarantine_retirement_decision_remains_explicitly_blocked() -> None:
    decisions = load_retirement_decisions(
        SHARED_ROOT / "schema_retirement_decisions.json"
    )

    assert len(decisions) == 1
    assert decisions[0].candidate == "job_dispatch_cutover_quarantine"
    assert decisions[0].status == "blocked"
    assert decisions[0].owner == "job-operations"
    assert decisions[0].unmet_conditions
    assert "message" not in json.dumps(decisions[0].unmet_conditions).lower()


def test_write_cutover_production_sql_has_no_compatibility_access() -> None:
    production_paths = (
        REPOSITORY_ROOT / "backend/app/modules/job/infrastructure/repositories.py",
        REPOSITORY_ROOT / "backend/app/modules/admin/infrastructure/read_repository.py",
        REPOSITORY_ROOT / "backend/app/modules/job/application/create_agent_job_service.py",
        REPOSITORY_ROOT / "backend/app/modules/agent/application/agent_context_builder.py",
        REPOSITORY_ROOT / "backend/app/modules/workflow/infrastructure/repository.py",
        REPOSITORY_ROOT / "backend/app/modules/workflow/application/service.py",
    )
    sources = {
        str(path.relative_to(REPOSITORY_ROOT)): path.read_text(encoding="utf-8")
        for path in production_paths
    }
    combined = "\n".join(sources.values())

    assert "dingding_conversation_id" not in combined
    assert "dingding_user_id" not in combined
    assert "graph_json" not in combined
    assert "select * from agent_job" not in combined.lower()
    assert "select * from agent_session" not in combined.lower()
    assert re.search(
        r"\b(?:job|j)\.(?:user_id|source|user_message)\b",
        combined,
        re.IGNORECASE,
    ) is None

    repository_source = sources[
        "backend/app/modules/job/infrastructure/repositories.py"
    ]
    for table, forbidden in (
        ("agent_session", {"dingding_conversation_id", "dingding_user_id", "source"}),
        ("agent_job", {"user_id", "source", "user_message"}),
    ):
        insert_columns = re.findall(
            rf"insert\s+into\s+{table}\s*\((.*?)\)\s*values",
            repository_source,
            flags=re.IGNORECASE | re.DOTALL,
        )
        assert insert_columns
        for raw_columns in insert_columns:
            assert forbidden.isdisjoint(
                {column.strip().lower() for column in raw_columns.split(",")}
            )
