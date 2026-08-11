from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from app.shared.schema_fact_sources import (
    FactSourceManifestError,
    baseline_engine_catalogs,
    default_fact_source_manifest_path,
    default_fact_source_schema_path,
    load_fact_source_manifest,
    reconcile_manifest_with_catalogs,
    validate_declared_code_paths,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = REPOSITORY_ROOT / "backend" / "migrations" / "100_baseline_v1.sql"


def _write_manifest(tmp_path: Path, manifest: dict[str, object]) -> Path:
    path = tmp_path / "schema_fact_sources.json"
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return path


def test_repository_fact_source_manifest_is_valid_and_catalog_backed() -> None:
    manifest = load_fact_source_manifest()

    assert manifest["baseline_predecessor"] == "100"
    assert manifest["migration_plan"] == {
        "expand_candidate": "101",
        "backfill_checkpoint_candidate": "102",
        "contract_candidate": "103",
        "allocation_rule": (
            "Re-read the immutable active catalog and all active changes immediately before "
            "creating each migration; reallocate forward on any conflict and never edit an "
            "applied migration."
        ),
    }
    assert len(manifest["entries"]) >= 35
    assert {
        entry["classification"] for entry in manifest["entries"]
    } == {
        "canonical_mutable_fact",
        "immutable_snapshot",
        "compatibility_shadow",
        "operational_coordination_fact",
        "one_time_migration_artifact",
    }

    catalogs = baseline_engine_catalogs(BASELINE_PATH)
    assert set(catalogs) == {"sqlite", "postgres"}
    reconcile_manifest_with_catalogs(manifest, catalogs)
    validate_declared_code_paths(manifest, REPOSITORY_ROOT)


def test_manifest_tracks_required_retained_and_retirement_objects() -> None:
    manifest = load_fact_source_manifest()
    by_id = {entry["id"]: entry for entry in manifest["entries"]}

    for identifier in (
        "outbox.webhook",
        "outbox.channel_ingress",
        "outbox.job_dispatch",
        "outbox.delivery",
        "runtime.event",
        "runtime.terminal_ledger",
        "runtime.invocation_claim",
        "runtime.invocation_event",
        "identity.ones_challenge",
        "publication.agent",
        "publication.business_application",
        "publication.webhook_trigger",
        "workflow.publication",
        "audit.general",
        "audit.identity_migration",
        "audit.platform_config",
    ):
        assert by_id[identifier]["retirement"]["status"] == "retained"

    compatibility_ids = {
        "session.legacy_dingding_conversation_id",
        "session.legacy_dingding_user_id",
        "session.legacy_source",
        "job.legacy_user_id",
        "job.legacy_source",
        "job.legacy_user_message",
        "workflow.legacy_graph_json",
    }
    assert all(
        by_id[identifier]["retirement"]["earliest_phase"] == "contract/drop"
        for identifier in compatibility_ids
    )
    assert by_id["cutover.job_dispatch_quarantine"]["retirement"]["status"] == "blocked"


def test_manifest_rejects_unknown_classification(tmp_path: Path) -> None:
    manifest = copy.deepcopy(load_fact_source_manifest())
    manifest["entries"][0]["classification"] = "duplicate_but_probably_safe"

    with pytest.raises(FactSourceManifestError, match="schema validation"):
        load_fact_source_manifest(
            _write_manifest(tmp_path, manifest),
            schema_path=default_fact_source_schema_path(),
        )


def test_manifest_rejects_compatibility_shadow_without_exit_gate(tmp_path: Path) -> None:
    manifest = copy.deepcopy(load_fact_source_manifest())
    shadow = next(
        entry
        for entry in manifest["entries"]
        if entry["classification"] == "compatibility_shadow"
    )
    shadow["retirement"] = {
        "status": "retained",
        "earliest_phase": "never",
        "gates": ["none"],
    }

    with pytest.raises(FactSourceManifestError, match="requires an exit status"):
        load_fact_source_manifest(
            _write_manifest(tmp_path, manifest),
            schema_path=default_fact_source_schema_path(),
        )


def test_manifest_rejects_immutable_snapshot_without_source_contract(tmp_path: Path) -> None:
    manifest = copy.deepcopy(load_fact_source_manifest())
    snapshot = next(
        entry
        for entry in manifest["entries"]
        if entry["classification"] == "immutable_snapshot"
    )
    snapshot.pop("source_contract")

    with pytest.raises(FactSourceManifestError, match="requires source_contract"):
        load_fact_source_manifest(
            _write_manifest(tmp_path, manifest),
            schema_path=default_fact_source_schema_path(),
        )


def test_manifest_rejects_missing_declared_code_path(tmp_path: Path) -> None:
    manifest = copy.deepcopy(load_fact_source_manifest())
    manifest["entries"][0]["readers"].append("code:backend/app/not-present.py")

    with pytest.raises(FactSourceManifestError, match="missing code paths"):
        validate_declared_code_paths(manifest, REPOSITORY_ROOT)


def test_manifest_schema_file_itself_is_loaded_from_repository() -> None:
    assert default_fact_source_manifest_path().is_file()
    assert default_fact_source_schema_path().is_file()
