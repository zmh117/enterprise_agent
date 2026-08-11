from __future__ import annotations

import json

import pytest

from app.modules.platform_config.application.validation import PlatformConfigValidationError
from app.modules.workflow.application.graph_facts import (
    canonical_draft_graph,
    graph_config_hash,
    publication_snapshot,
)
from app.modules.workflow.infrastructure.repository import WorkflowDraftConflict
from backend.tests.helpers import container


ADMIN = "user_local_admin"


def _create_template(runtime: object, code: str = "fact-source-flow") -> dict[str, object]:
    return runtime.workflow_service.upsert_template(  # type: ignore[attr-defined]
        {"code": code, "name": "Fact Source Flow", "project_code": "default"},
        actor_id=ADMIN,
    )


def _restore_legacy_graph_column(runtime: object) -> None:
    columns = {
        row["name"]
        for row in runtime.database.execute(  # type: ignore[attr-defined]
            "pragma table_info(agent_workflow_template)"
        )
    }
    if "graph_json" in columns:
        return
    runtime.database.execute(  # type: ignore[attr-defined]
        "alter table agent_workflow_template add column graph_json text not null default '{}'"
    )


def test_canonical_graph_serialization_is_stable_and_ignores_row_metadata() -> None:
    first = canonical_draft_graph(
        nodes=[
            {
                "id": "random-b",
                "node_key": "b",
                "node_type": "report",
                "updated_at": "later",
            },
            {
                "id": "random-a",
                "node_key": "a",
                "node_type": "trigger",
                "updated_at": "earlier",
            },
        ],
        edges=[
            {
                "id": "random-edge",
                "edge_key": "a-b",
                "source_node_key": "a",
                "target_node_key": "b",
            }
        ],
    )
    second = canonical_draft_graph(
        nodes=[
            {"id": "other-a", "node_key": "a", "node_type": "trigger"},
            {"id": "other-b", "node_key": "b", "node_type": "report"},
        ],
        edges=[
            {
                "id": "other-edge",
                "edge_key": "a-b",
                "source_node_key": "a",
                "target_node_key": "b",
            }
        ],
    )

    assert first == second
    assert graph_config_hash({"graph": first}) == graph_config_hash({"graph": second})
    assert [node["node_key"] for node in first["nodes"]] == ["a", "b"]


def test_template_updates_do_not_write_legacy_graph_json() -> None:
    runtime = container()
    _restore_legacy_graph_column(runtime)
    template = _create_template(runtime)
    runtime.database.execute(
        "update agent_workflow_template set graph_json = ? where id = ?",
        (json.dumps({"legacy": "preserve-until-backfill"}), template["id"]),
    )

    updated = runtime.workflow_service.upsert_template(
        {
            "code": "fact-source-flow",
            "name": "Renamed",
            "project_code": "default",
        },
        actor_id=ADMIN,
    )

    row = runtime.database.execute_one(
        "select graph_json from agent_workflow_template where id = ?",
        (template["id"],),
    )
    assert updated["name"] == "Renamed"
    assert "graph_json" not in updated
    assert row == {"graph_json": json.dumps({"legacy": "preserve-until-backfill"})}


def test_template_api_rejects_a_second_mutable_graph_input() -> None:
    runtime = container()

    with pytest.raises(PlatformConfigValidationError, match="normalized node and edge"):
        runtime.workflow_service.upsert_template(
            {
                "code": "legacy-graph-input",
                "name": "Legacy Graph",
                "graph": {"nodes": [{"node_key": "start"}]},
            },
            actor_id=ADMIN,
        )


def test_publication_uses_only_normalized_graph_and_is_immutable() -> None:
    runtime = container()
    _restore_legacy_graph_column(runtime)
    template = _create_template(runtime)
    runtime.database.execute(
        "update agent_workflow_template set graph_json = ? where id = ?",
        (
            json.dumps(
                {"nodes": [{"node_key": "legacy", "node_type": "trigger"}], "edges": []}
            ),
            template["id"],
        ),
    )
    runtime.workflow_service.upsert_node(
        "fact-source-flow",
        {"node_key": "start", "node_type": "trigger", "title": "Start"},
        actor_id=ADMIN,
    )
    runtime.workflow_service.upsert_template(
        {
            "code": "fact-source-flow",
            "name": "Fact Source Flow",
            "project_code": "default",
            "entry_node_key": "start",
        },
        actor_id=ADMIN,
    )

    publication = runtime.workflow_service.publish("fact-source-flow", actor_id=ADMIN)
    original_snapshot = publication["graph_snapshot"]
    runtime.workflow_service.upsert_node(
        "fact-source-flow",
        {"node_key": "start", "node_type": "trigger", "title": "Changed"},
        actor_id=ADMIN,
    )
    persisted = runtime.workflow_service.repository.get_publication(publication["id"])

    assert [node["node_key"] for node in original_snapshot["nodes"]] == ["start"]
    assert "legacy" not in json.dumps(original_snapshot, sort_keys=True)
    assert persisted["graph_snapshot"] == original_snapshot


def test_publication_rejects_concurrent_draft_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = container()
    template = _create_template(runtime, code="concurrent-flow")
    original = runtime.workflow_service.repository.load_normalized_draft

    def load_and_change(template_code: str, *, lock: bool = False) -> dict[str, object]:
        draft = original(template_code, lock=lock)
        runtime.database.execute(
            "update agent_workflow_template set updated_at = ? where id = ?",
            ("2099-01-01T00:00:00+00:00", template["id"]),
        )
        return draft

    monkeypatch.setattr(
        runtime.workflow_service.repository,
        "load_normalized_draft",
        load_and_change,
    )

    with pytest.raises(WorkflowDraftConflict, match="changed during publication"):
        runtime.workflow_service.publish("concurrent-flow", actor_id=ADMIN)

    assert runtime.database.execute_one(
        "select count(*) as count from agent_workflow_publication where template_id = ?",
        (template["id"],),
    ) == {"count": 0}


def test_repository_operates_when_legacy_graph_column_is_absent() -> None:
    runtime = container()
    runtime.database.execute("drop table agent_workflow_publication")
    runtime.database.execute("drop table agent_workflow_edge")
    runtime.database.execute("drop table agent_workflow_node")
    runtime.database.execute("drop table agent_workflow_template")
    runtime.database.execute(
        """
        create table agent_workflow_template (
          id text primary key, code text not null unique, name text not null,
          description text not null default '', project_code text not null default 'default',
          status text not null default 'draft', version integer not null default 1,
          entry_node_key text not null default '', graph_schema_version integer not null default 1,
          settings_json text not null default '{}', created_by text not null default '',
          created_at text not null, updated_at text not null
        )
        """
    )
    runtime.database.execute(
        """
        create table agent_workflow_node (
          id text primary key, template_id text not null, node_key text not null,
          node_type text not null, title text not null default '', position_json text not null,
          config_json text not null, ui_json text not null, created_at text not null,
          updated_at text not null, unique(template_id, node_key)
        )
        """
    )
    runtime.database.execute(
        """
        create table agent_workflow_edge (
          id text primary key, template_id text not null, edge_key text not null,
          source_node_key text not null, target_node_key text not null,
          source_port text not null default '', target_port text not null default '',
          condition_json text not null, created_at text not null, updated_at text not null,
          unique(template_id, edge_key)
        )
        """
    )
    runtime.database.execute(
        """
        create table agent_workflow_publication (
          id text primary key, template_id text not null, version integer not null,
          graph_snapshot_json text not null, config_hash text not null,
          published_by text not null default '', published_at text not null,
          unique(template_id, version)
        )
        """
    )

    template = _create_template(runtime, code="contract-flow")
    runtime.workflow_service.upsert_node(
        "contract-flow",
        {"node_key": "start", "node_type": "trigger"},
        actor_id=ADMIN,
    )
    publication = runtime.workflow_service.publish("contract-flow", actor_id=ADMIN)

    assert template["code"] == "contract-flow"
    assert publication["graph_snapshot"]["nodes"][0]["node_key"] == "start"


def test_publication_snapshot_hash_covers_schema_version_and_settings() -> None:
    base = publication_snapshot(
        template={
            "id": "workflow",
            "code": "flow",
            "name": "Flow",
            "graph_schema_version": 1,
            "settings": {"budget": 1},
        },
        nodes=[],
        edges=[],
    )
    changed = publication_snapshot(
        template={
            "id": "workflow",
            "code": "flow",
            "name": "Flow",
            "graph_schema_version": 2,
            "settings": {"budget": 1},
        },
        nodes=[],
        edges=[],
    )

    assert graph_config_hash(base) != graph_config_hash(changed)
