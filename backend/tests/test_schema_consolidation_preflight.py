from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

import pytest

from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import Migrator, load_migration_catalog
from app.shared.schema_baseline import load_legacy_manifest
from app.shared.schema_consolidation import (
    SchemaConsolidationError,
    SchemaConsolidationPreflight,
    SessionJobMessageBackfill,
    WorkflowGraphBackfill,
    require_write_authorization,
)
from app.cli.schema_consolidation import build_parser


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
NOW = "2026-08-11T00:00:00+00:00"


@pytest.fixture
def database(tmp_path: Path) -> Database:
    migrations = tmp_path / "baseline-migrations"
    migrations.mkdir()
    source = default_migrations_dir()
    (migrations / "100_baseline_v1.sql").write_bytes(
        (source / "100_baseline_v1.sql").read_bytes()
    )
    (migrations / "legacy-v1-manifest.json").write_bytes(
        (source / "legacy-v1-manifest.json").read_bytes()
    )
    value = Database("sqlite:///:memory:")
    Migrator(value, migrations, migrator_build="consolidation-test").run()
    try:
        yield value
    finally:
        value.close()


@pytest.fixture
def expanded_database(tmp_path: Path) -> Database:
    migrations = tmp_path / "expanded-migrations"
    migrations.mkdir()
    source = default_migrations_dir()
    for name in (
        "100_baseline_v1.sql",
        "101_expand_canonical_job_message.sql",
        "102_schema_consolidation_checkpoint.sql",
        "legacy-v1-manifest.json",
    ):
        (migrations / name).write_bytes((source / name).read_bytes())
    value = Database("sqlite:///:memory:")
    Migrator(value, migrations, migrator_build="consolidation-expanded").run()
    try:
        yield value
    finally:
        value.close()


def _insert_job_fixture(
    database: Database,
    *,
    suffix: str,
    session_source: str = "dingding",
    session_source_channel: str = "dingding",
    session_conversation: str = "conversation",
    canonical_conversation: str = "conversation",
    session_user: str = "user",
    canonical_requester: str = "user",
    job_source: str = "dingding",
    job_source_channel: str = "dingding",
    job_user: str = "user",
    job_requester: str = "user",
    message_count: int = 1,
    message_content: str = "synthetic-question",
    job_content: str = "synthetic-question",
    status: str = "PENDING",
) -> None:
    session_id = f"session-{suffix}"
    job_id = f"job-{suffix}"
    database.execute(
        """
        insert into agent_session
          (id, dingding_conversation_id, dingding_user_id, source, project_code,
           created_at, updated_at, source_channel, source_connector_id,
           external_conversation_id, requester_id, session_key,
           application_publication_id, execution_scope_hash)
        values (?, ?, ?, ?, 'default', ?, ?, ?, 'connector-test', ?, ?, ?,
                'app-publication-test', 'scope-hash-test')
        """,
        (
            session_id,
            session_conversation,
            session_user,
            session_source,
            NOW,
            NOW,
            session_source_channel,
            canonical_conversation,
            canonical_requester,
            f"key-{suffix}",
        ),
    )
    database.execute(
        """
        insert into agent_job
          (id, session_id, idempotency_key, user_id, project_code, source,
           user_message, status, created_at, source_channel, source_connector_id,
           external_event_id, requester_id)
        values (?, ?, ?, ?, 'default', ?, ?, ?, ?, ?, 'connector-test', ?, ?)
        """,
        (
            job_id,
            session_id,
            f"idempotency-{suffix}",
            job_user,
            job_source,
            job_content,
            status,
            NOW,
            job_source_channel,
            f"event-{suffix}",
            job_requester,
        ),
    )
    for index in range(message_count):
        database.execute(
            """
            insert into agent_message
              (id, session_id, job_id, role, content, created_at, sequence_no)
            values (?, ?, ?, 'user', ?, ?, ?)
            """,
            (
                f"message-{suffix}-{index}",
                session_id,
                job_id,
                message_content,
                NOW,
                index + 1,
            ),
        )


def _insert_workflow_template(
    database: Database,
    *,
    suffix: str,
    graph: dict[str, object],
) -> str:
    template_id = f"workflow-{suffix}"
    database.execute(
        """
        insert into agent_workflow_template
          (id, code, name, project_code, status, version, graph_json,
           created_at, updated_at)
        values (?, ?, ?, 'default', 'draft', 1, ?, ?, ?)
        """,
        (
            template_id,
            f"workflow-{suffix}",
            f"Workflow {suffix}",
            json.dumps(graph, sort_keys=True),
            NOW,
            NOW,
        ),
    )
    return template_id


def _insert_normalized_node(database: Database, *, template_id: str, node_key: str) -> None:
    database.execute(
        """
        insert into agent_workflow_node
          (id, template_id, node_key, node_type, title, position_json,
           config_json, ui_json, created_at, updated_at)
        values (?, ?, ?, 'trigger', '', '{}', '{}', '{}', ?, ?)
        """,
        (f"node-{template_id}-{node_key}", template_id, node_key, NOW, NOW),
    )


def test_preflight_reports_exact_parity_without_exposing_content(database: Database) -> None:
    sensitive_marker = "MUST-NOT-APPEAR-IN-REPORT"
    _insert_job_fixture(
        database,
        suffix="parity",
        message_content=sensitive_marker,
        job_content=sensitive_marker,
    )

    report = SchemaConsolidationPreflight(database, default_migrations_dir()).run()

    assert report["status"] == "ready"
    assert report["migration"]["status"] == "current"
    assert report["compatibility"]["sessions"]["blocking_count"] == 0
    assert report["compatibility"]["jobs"]["blocking_count"] == 0
    assert report["compatibility"]["messages"]["blocking_count"] == 0
    assert sensitive_marker not in json.dumps(report, ensure_ascii=False)


def test_preflight_blocks_missing_and_conflicting_canonical_facts(database: Database) -> None:
    _insert_job_fixture(
        database,
        suffix="conflict",
        canonical_conversation="",
        canonical_requester="other-user",
        job_source_channel="webhook",
        job_requester="other-user",
    )

    report = SchemaConsolidationPreflight(database, default_migrations_dir()).run()

    assert report["status"] == "blocked"
    assert report["compatibility"]["sessions"]["blocking_ids"] == ["session-conflict"]
    assert report["compatibility"]["jobs"]["blocking_ids"] == ["job-conflict"]
    assert "session_parity" in report["blocker_codes"]
    assert "job_parity" in report["blocker_codes"]


@pytest.mark.parametrize(
    ("message_count", "message_content"),
    [(0, "synthetic-question"), (2, "synthetic-question"), (1, "different-question")],
)
def test_preflight_blocks_message_cardinality_or_parity(
    database: Database,
    message_count: int,
    message_content: str,
) -> None:
    _insert_job_fixture(
        database,
        suffix=f"message-{message_count}-{len(message_content)}",
        message_count=message_count,
        message_content=message_content,
    )

    report = SchemaConsolidationPreflight(database, default_migrations_dir()).run()

    assert report["compatibility"]["messages"]["blocking_count"] == 1
    assert "message_cardinality" in report["blocker_codes"]


def test_preflight_classifies_graph_only_normalized_only_and_divergent(database: Database) -> None:
    graph_only = _insert_workflow_template(
        database,
        suffix="graph-only",
        graph={"nodes": [{"node_key": "legacy", "node_type": "trigger"}], "edges": []},
    )
    normalized_only = _insert_workflow_template(database, suffix="normalized-only", graph={})
    _insert_normalized_node(database, template_id=normalized_only, node_key="normalized")
    divergent = _insert_workflow_template(
        database,
        suffix="divergent",
        graph={"nodes": [{"node_key": "legacy", "node_type": "trigger"}], "edges": []},
    )
    _insert_normalized_node(database, template_id=divergent, node_key="normalized")

    report = SchemaConsolidationPreflight(database, default_migrations_dir()).run()
    workflows = report["compatibility"]["workflows"]

    assert workflows["graph_only"] == 1
    assert workflows["normalized_only"] == 1
    assert workflows["divergent"] == 1
    assert workflows["blocking_ids"] == [divergent]
    assert graph_only not in workflows["blocking_ids"]


def test_preflight_reports_pending_retry_and_active_runtime_claim(database: Database) -> None:
    _insert_job_fixture(database, suffix="retry", status="RETRY_WAIT")
    database.execute(
        """
        insert into agent_runtime_invocation_claim
          (invocation_id, request_digest, runtime_kind, owner_instance_id,
           claimed_at, expires_at)
        values ('invocation-test', ?, 'python-v1', 'runtime-test', ?, ?)
        """,
        ("0" * 64, NOW, "2026-08-12T00:00:00+00:00"),
    )

    report = SchemaConsolidationPreflight(database, default_migrations_dir()).run()

    assert report["operational"]["agent_job_nonterminal"] == 1
    assert report["operational"]["runtime_invocation_claim"] == 1


def test_preflight_reports_exact_legacy_042_requires_adoption(database: Database) -> None:
    manifest = load_legacy_manifest(default_migrations_dir() / "legacy-v1-manifest.json")
    timestamp = datetime.now(UTC).isoformat()
    with database.unit_of_work():
        database.execute("delete from schema_migration")
        database.execute("delete from schema_baseline_adoption")
        for artifact in manifest["catalog"]:
            database.execute(
                """
                insert into schema_migration
                  (version, name, checksum, applied_at, duration_ms, migrator_build)
                values (?, ?, ?, ?, 0, 'legacy-fixture')
                """,
                (
                    artifact["version"],
                    artifact["name"],
                    artifact["checksum"],
                    timestamp,
                ),
            )

    report = SchemaConsolidationPreflight(database, default_migrations_dir()).run()

    assert report["status"] == "blocked"
    assert report["migration"] == {
        "status": "baseline_adoption_required",
        "current_head": "042",
        "repository_head": load_migration_catalog(default_migrations_dir())[-1].version,
        "checksum_valid": True,
    }


def test_preflight_requires_the_exact_requested_head(expanded_database: Database) -> None:
    report = SchemaConsolidationPreflight(
        expanded_database,
        default_migrations_dir(),
    ).run(expected_head="100")

    assert report["status"] == "blocked"
    assert report["migration"]["status"] == "head_or_checksum_mismatch"
    assert report["migration"]["current_head"] == "102"


def test_write_authorization_is_dry_run_by_default(tmp_path: Path) -> None:
    assert (
        require_write_authorization(
            apply=False,
            phase="backfill",
            expected_head="100",
            actual_head="042",
            target_label="local",
            confirmed_target="",
            evidence_directory=None,
            repository_root=REPOSITORY_ROOT,
        )
        is None
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"actual_head": "042"},
        {"confirmed_target": "other"},
        {"evidence_directory": None},
        {"phase": "preflight"},
    ],
)
def test_write_authorization_fails_closed(
    tmp_path: Path,
    overrides: dict[str, object],
) -> None:
    arguments: dict[str, object] = {
        "apply": True,
        "phase": "backfill",
        "expected_head": "100",
        "actual_head": "100",
        "target_label": "test-target",
        "confirmed_target": "test-target",
        "evidence_directory": tmp_path,
        "repository_root": REPOSITORY_ROOT,
    }
    arguments.update(overrides)

    with pytest.raises(SchemaConsolidationError):
        require_write_authorization(**arguments)  # type: ignore[arg-type]


def test_write_authorization_accepts_exact_non_secret_confirmation(tmp_path: Path) -> None:
    authorization = require_write_authorization(
        apply=True,
        phase="backfill",
        expected_head="100",
        actual_head="100",
        target_label="staging-blue",
        confirmed_target="staging-blue",
        evidence_directory=tmp_path,
        repository_root=REPOSITORY_ROOT,
    )

    assert authorization is not None
    assert authorization.target_label == "staging-blue"
    assert authorization.evidence_directory == tmp_path.resolve()


def test_workflow_backfill_is_dry_run_by_default_and_content_safe(database: Database) -> None:
    sensitive_marker = "GRAPH-BODY-MUST-NOT-APPEAR"
    template_id = _insert_workflow_template(
        database,
        suffix="backfill-dry-run",
        graph={
            "nodes": [
                {
                    "node_key": "start",
                    "node_type": "trigger",
                    "title": sensitive_marker,
                }
            ],
            "edges": [],
        },
    )

    report = WorkflowGraphBackfill(database).run()

    assert report["mode"] == "dry-run"
    assert report["classification_counts"]["graph_only"] == 1
    assert report["applied_count"] == 0
    assert database.execute_one(
        "select count(*) as count from agent_workflow_node where template_id = ?",
        (template_id,),
    ) == {"count": 0}
    assert sensitive_marker not in json.dumps(report, ensure_ascii=False)


def test_workflow_backfill_is_re_runnable_and_uses_stable_ids(
    expanded_database: Database,
) -> None:
    database = expanded_database
    template_id = _insert_workflow_template(
        database,
        suffix="backfill-apply",
        graph={
            "nodes": [
                {"node_key": "report", "node_type": "report"},
                {"node_key": "start", "node_type": "trigger"},
            ],
            "edges": [
                {
                    "edge_key": "start-report",
                    "source_node_key": "start",
                    "target_node_key": "report",
                }
            ],
        },
    )

    first = WorkflowGraphBackfill(database).run(apply=True)
    node_ids = [
        row["id"]
        for row in database.execute(
            "select id from agent_workflow_node where template_id = ? order by node_key",
            (template_id,),
        )
    ]
    second = WorkflowGraphBackfill(database).run(apply=True)

    assert first["applied_count"] == 1
    assert second["applied_count"] == 0
    assert second["processed_count"] == 0
    assert second["classification_counts"] == {}
    assert node_ids == [
        row["id"]
        for row in database.execute(
            "select id from agent_workflow_node where template_id = ? order by node_key",
            (template_id,),
        )
    ]
    assert database.execute_one(
        """
        select phase, target_object, last_id, scanned_count, updated_count,
               blocked_count
          from schema_consolidation_checkpoint
         where phase = 'workflow-graph'
           and target_object = 'agent_workflow_template'
        """
    ) == {
        "phase": "workflow-graph",
        "target_object": "agent_workflow_template",
        "last_id": template_id,
        "scanned_count": 1,
        "updated_count": 1,
        "blocked_count": 0,
    }


def test_workflow_backfill_fails_closed_before_any_write_on_divergence(
    expanded_database: Database,
) -> None:
    database = expanded_database
    graph_only = _insert_workflow_template(
        database,
        suffix="batch-graph-only",
        graph={"nodes": [{"node_key": "start", "node_type": "trigger"}], "edges": []},
    )
    divergent = _insert_workflow_template(
        database,
        suffix="batch-divergent",
        graph={"nodes": [{"node_key": "legacy", "node_type": "trigger"}], "edges": []},
    )
    _insert_normalized_node(database, template_id=divergent, node_key="normalized")

    report = WorkflowGraphBackfill(database).run(apply=True)

    assert report["status"] == "blocked"
    assert report["applied_count"] == 0
    assert report["blocking_ids"] == [divergent]
    assert database.execute_one(
        "select count(*) as count from agent_workflow_node where template_id = ?",
        (graph_only,),
    ) == {"count": 0}


def test_workflow_backfill_rolls_back_an_interrupted_batch(
    expanded_database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = expanded_database
    for suffix in ("interrupt-a", "interrupt-b"):
        _insert_workflow_template(
            database,
            suffix=suffix,
            graph={
                "nodes": [{"node_key": "start", "node_type": "trigger"}],
                "edges": [],
            },
        )
    backfill = WorkflowGraphBackfill(database)
    original = backfill._apply_template
    call_count = 0

    def interrupt_second(plan: dict[str, object]) -> bool:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise SchemaConsolidationError("synthetic interrupted batch")
        return original(plan)

    monkeypatch.setattr(backfill, "_apply_template", interrupt_second)

    with pytest.raises(SchemaConsolidationError, match="interrupted"):
        backfill.run(apply=True)

    assert database.execute_one(
        "select count(*) as count from agent_workflow_node"
    ) == {"count": 0}
    assert database.execute_one(
        """
        select count(*) as count
          from schema_consolidation_checkpoint
         where phase = 'workflow-graph'
        """
    ) == {"count": 0}


def test_schema_consolidation_cli_is_dry_run_by_default() -> None:
    preflight = build_parser().parse_args(["preflight"])
    backfill = build_parser().parse_args(["backfill-workflow"])

    assert preflight.apply is False
    assert backfill.apply is False
    assert backfill.expected_head == ""
    assert backfill.confirm_target == ""
    assert backfill.evidence_dir is None


def test_session_job_message_backfill_is_dry_run_and_content_safe(
    expanded_database: Database,
) -> None:
    marker = "MESSAGE-BODY-MUST-NOT-APPEAR"
    _insert_job_fixture(
        expanded_database,
        suffix="canonical-backfill-dry",
        message_content=marker,
        job_content=marker,
    )

    report = SessionJobMessageBackfill(expanded_database).run()

    assert report["mode"] == "dry-run"
    assert report["status"] == "ready"
    assert report["job_message"]["classification_counts"] == {"linkable": 1}
    assert report["applied_count"] == 0
    assert marker not in json.dumps(report, ensure_ascii=False)
    assert expanded_database.execute_one(
        "select input_message_id from agent_job where id = 'job-canonical-backfill-dry'"
    ) == {"input_message_id": None}


def test_session_job_message_backfill_is_re_runnable_and_checkpoints(
    expanded_database: Database,
) -> None:
    _insert_job_fixture(expanded_database, suffix="canonical-backfill-apply")

    first = SessionJobMessageBackfill(expanded_database).run(apply=True)
    linked = expanded_database.execute_one(
        "select input_message_id from agent_job where id = 'job-canonical-backfill-apply'"
    )
    second = SessionJobMessageBackfill(expanded_database).run(apply=True)

    assert first["status"] == "ready"
    assert first["applied_count"] == 1
    assert linked == {"input_message_id": "message-canonical-backfill-apply-0"}
    assert second["processed_count"] == 0
    assert second["applied_count"] == 0
    assert {
        row["target_object"]
        for row in expanded_database.execute(
            "select target_object from schema_consolidation_checkpoint"
        )
    } == {"agent_session", "agent_job"}


def test_session_job_message_backfill_fails_closed_before_any_write(
    expanded_database: Database,
) -> None:
    _insert_job_fixture(expanded_database, suffix="backfill-safe")
    _insert_job_fixture(
        expanded_database,
        suffix="backfill-blocked",
        message_count=0,
    )

    report = SessionJobMessageBackfill(expanded_database).run(apply=True)

    assert report["status"] == "blocked"
    assert report["applied_count"] == 0
    assert report["blocking_ids"] == ["job-backfill-blocked"]
    assert expanded_database.execute_one(
        "select input_message_id from agent_job where id = 'job-backfill-safe'"
    ) == {"input_message_id": None}
    assert expanded_database.execute("select * from schema_consolidation_checkpoint") == []
