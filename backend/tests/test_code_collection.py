"""Durable collection/schedule tests with a deterministic source, not production SVN."""

from contextlib import contextmanager
from datetime import UTC, datetime
import json
from types import SimpleNamespace

import pytest

from app.modules.knowledge.infrastructure.code_collection_controller import CodeCollectionController
from app.modules.knowledge.application.code_schedule import next_daily
from app.modules.knowledge.domain.code_contracts import COMPONENTS, CodeKnowledgeError
from app.modules.knowledge.domain.normalization import digest
from app.modules.knowledge.infrastructure.code_build_repository import CodeBuildRepository
from app.modules.knowledge.infrastructure.code_repository import CodeRepository, decoded
from app.modules.knowledge.infrastructure.code_source import LocalCodeCollector, FrozenSource
from app.modules.knowledge.infrastructure.storage import table
from backend.tests.test_code_knowledge import database as database_fixture

database = database_fixture


@pytest.fixture
def collection(database, tmp_path):
    repo = CodeRepository(database)
    key = {"key": "test", "digest": digest("registration")}
    ids = repo.register(
        code="code", base_code="code-base", config={"svn_verified": True, "svn_registration": key}
    )
    source_id = ids["source_id"]
    root = tmp_path / "source"
    for path in COMPONENTS.values():
        (root / path).mkdir(parents=True)
    (root / "set_server/rule.cpp").write_text("return accepted;\n")
    local = LocalCodeCollector(root.resolve())
    original = local.freeze()
    source = SimpleNamespace(head=lambda: 303, expected_uuid="repository", branch_path="/trunk")
    seen = []

    def commits(*, after, target, through):
        seen.append((after, target, through))
        return [
            {"revision": revision, "paths": [{"path": "/trunk/set_server/rule.cpp", "action": "M"}]}
            for revision in range(after + 1, through + 1)
        ]

    source.commits = commits

    @contextmanager
    def prepare(revision, capture_floating=False):
        manifest = {**original.manifest, "externals": {"complete": True, "declarations": []}}
        yield (
            local,
            FrozenSource(
                manifest,
                original.files,
                {
                    "kind": "svn",
                    "repository_uuid": "repository",
                    "branch_path": "/trunk",
                    "revision": revision,
                    "manifest_hash": digest(manifest),
                },
            ),
        )

    admission = SimpleNamespace(source=source, prepare=prepare, components=dict(COMPONENTS))
    registry = SimpleNamespace(get=lambda _: (key, admission))
    plan = {
        "schedule": {"enabled": True, "local_time": "02:00", "timezone": "Asia/Shanghai"},
        "extraction": {"synthetic": "fixed"},
    }
    database.execute(
        f"update {table(database, 'code_binding')} set enabled=1,demand_enabled=1,collected_revision=100,collected_from_revision=100,operations_json=? where source_id=?",
        (json.dumps(plan), source_id),
    )

    def controller():
        return CodeCollectionController(database, registry, tmp_path.resolve() / "volume")

    return database, repo, source_id, source, seen, controller


def test_daily_target_and_cursor_survive_restarts_without_chasing_head(collection):
    db, repo, source_id, source, seen, controller = collection
    assert controller().step(source_id)["collected_revision"] == 200
    source.head = lambda: 999  # New commits cannot change the already persisted target.
    assert controller().step(source_id)["collected_revision"] == 300
    result = controller().step(source_id)
    assert result["state"] == "BUILD_QUEUED"
    assert seen == [(100, 303, 200), (200, 303, 300), (300, 303, 303)]
    binding = repo.binding(source_id)
    assert binding["collected_revision"] == 303 and binding["active_snapshot_id"] is None
    assert db.execute_one(f"select count(*) as n from {table(db, 'code_commit')}")["n"] == 203
    assert controller().step(source_id)["state"] == "IDLE"
    assert db.execute_one(f"select count(*) as n from {table(db, 'code_build')}")["n"] == 1


def test_collection_resumes_after_committed_ledger_before_phase_update(collection):
    db, repo, source_id, _, _, controller = collection
    controller().step(source_id)
    worker = controller()
    original = worker._save

    def interrupted(binding, state, **kwargs):
        if state["state"] == "FREEZING":
            raise RuntimeError("synthetic crash after ledger commit")
        return original(binding, state, **kwargs)

    worker._save = interrupted
    worker.step(source_id)
    with pytest.raises(RuntimeError):
        worker.step(source_id)
    assert repo.binding(source_id)["collected_revision"] == 303
    assert controller().step(source_id)["state"] == "BUILD_QUEUED"
    assert db.execute_one(f"select count(*) as n from {table(db, 'code_commit')}")["n"] == 203


def test_unconfigured_paused_drift_and_historical_demand(collection):
    db, repo, source_id, source, _, controller = collection
    binding = repo.binding(source_id)
    plan = decoded(binding["operations_json"])
    plan["schedule"]["enabled"] = False
    db.execute(f"update {table(db, 'code_binding')} set operations_json=?", (json.dumps(plan),))
    assert controller().step(source_id)["state"] == "IDLE"
    demand = CodeBuildRepository(db).demand(source_id, 80, "test-human")
    result = controller().step(source_id)
    assert result["state"] == "BUILD_QUEUED"
    build = CodeBuildRepository(db).get(result["build_id"])
    assert build["purpose"] == "history"
    assert repo.binding(source_id)["collected_revision"] == 100
    assert repo.binding(source_id)["active_snapshot_id"] is None
    row = db.execute_one(
        f"select state,build_id from {table(db, 'code_demand')} where id=?", (demand["demand_id"],)
    )
    assert row == {"state": "BUILDING", "build_id": result["build_id"]}
    drift = controller()
    drift.registry.get = lambda _: ({"digest": "changed"}, source)
    with pytest.raises(CodeKnowledgeError, match="configuration_changed"):
        drift.step(source_id)


def test_daily_schedule_timezone_and_dst_are_explicit():
    assert (
        next_daily(datetime(2026, 11, 5, 19, tzinfo=UTC), "02:00", "Asia/Shanghai")
        == "2026-11-06T18:00:00+00:00"
    )
    assert (
        next_daily(datetime(2026, 3, 8, 5, tzinfo=UTC), "02:30", "America/New_York")
        == "2026-03-08T07:00:00+00:00"
    )
    assert (
        next_daily(datetime(2026, 11, 1, 5, 45, tzinfo=UTC), "01:30", "America/New_York")
        == "2026-11-02T06:30:00+00:00"
    )
    with pytest.raises(CodeKnowledgeError):
        next_daily(datetime.now(UTC), "25:00", "Asia/Shanghai")


def test_registration_preserves_local_identity_and_repeated_verification_keeps_cursor(collection):
    from app.modules.knowledge.infrastructure.code_svn_registration import CodeSvnRegistration

    db, repo, _, _, _, factory = collection
    worker = factory()
    ids = repo.register(
        code="local-to-svn", base_code="local-to-svn-base", config={"components": COMPONENTS}
    )
    _, admission = worker.registry.get("test")
    with admission.prepare(100) as (_, frozen):
        local_ref = {
            "kind": "local_bundle",
            "bundle_id": "local-bundle",
            "svn_revision": None,
            "manifest_hash": digest(frozen.manifest),
        }
        local_id = repo.freeze_source(ids["source_id"], local_ref, frozen.manifest)
    service = CodeSvnRegistration(db, worker.registry, worker.source_root)
    result = service.verify(ids["source_id"], "test", 100, local_snapshot_id=local_id, commit=True)
    assert result["mapping"]["state"] == "VERIFIED" and not result["enabled"]
    local_row = db.execute_one(
        f"select source_ref,svn_revision from {table(db, 'code_source_snapshot')} where id=?",
        (local_id,),
    )
    assert local_row["svn_revision"] is None and json.loads(local_row["source_ref"]) == local_ref
    db.execute(
        f"update {table(db, 'code_binding')} set collected_revision=103,enabled=1 where source_id=?",
        (ids["source_id"],),
    )
    again = service.verify(ids["source_id"], "test", 100, local_snapshot_id=local_id, commit=True)
    assert again["source_snapshot_id"] == result["source_snapshot_id"]
    assert again["enabled"] and repo.binding(ids["source_id"])["collected_revision"] == 103


def test_registry_accepts_only_deployment_targets_and_opaque_auth_refs(tmp_path):
    from app.modules.knowledge.infrastructure.code_source_registry import CodeSourceRegistry

    root = tmp_path.resolve()
    (root / "auth" / "mes-auth").mkdir(parents=True)
    entry = {
        "branch_url": "https://svn.example.test/project/trunk",
        "repository_uuid": "test-uuid",
        "branch_path": "/project/trunk",
        "auth_ref": "mes-auth",
        "components": dict(COMPONENTS),
        "externals": {},
    }
    path = root / "registry.json"
    path.write_text(json.dumps({"mes": entry}))
    registry = CodeSourceRegistry(path, root / "auth")
    registration, source = registry.get("mes")
    assert registration["digest"] == digest(entry) and source.source.expected_uuid == "test-uuid"
    for changes in (
        {"auth_ref": "../escape"},
        {"unexpected_credential": "synthetic-only"},
        {"branch_url": "http://unapproved.example.test/trunk"},
    ):
        path.write_text(json.dumps({"mes": {**entry, **changes}}))
        with pytest.raises(CodeKnowledgeError):
            registry.get("mes")
