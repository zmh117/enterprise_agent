"""知识运维状态机、HTTP 权限及执行器边界；只使用合成数据和假 Compose。"""

from datetime import UTC, datetime, timedelta
import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from pathlib import Path
from threading import Event
import sys

import pytest
import yaml

from app.modules.knowledge.domain.governance import KnowledgeGovernanceError
from app.modules.knowledge.domain.identity import now
from app.modules.knowledge.infrastructure.incremental_repository import IncrementalSyncRepository
from app.modules.knowledge.infrastructure.operations_repository import OperationsRepository
from app.modules.knowledge.infrastructure.operations_scheduler import KnowledgeSyncScheduler
from app.modules.knowledge.infrastructure.operations_store import OperationsStore
from app.modules.knowledge.infrastructure.operations_compose import KnowledgeCompose
from app.modules.knowledge.infrastructure.deployment_paths import docker_environment
from app.modules.knowledge.infrastructure.operations_process import exclusive_process, run_process
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import Migrator, SchemaHeadValidator, load_migration_catalog
from backend.tests.test_knowledge_import import database as database_fixture
from backend.tests.test_knowledge_ones_collection import _enabled_binding
from backend.tests.test_knowledge_api import managed as managed_fixture
from backend.tests.test_unified_identity_rbac import login, csrf_headers
from backend.tests.test_schema_migration_postgres_integration import (
    postgres_database_dsn as postgres_fixture,
)
from backend.tests.support.migrations import schema_versions_after

database = database_fixture
managed = managed_fixture
postgres_database_dsn = postgres_fixture
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def plan(database):
    _, binding = _enabled_binding(database)
    database.execute('update "knowledge.sync_binding" set schedule_enabled=0')
    return binding


def submit(ops, plan, key="request-1", **values):
    return ops.submit(
        kind="sync", binding_id=plan["id"], request_key=key, actor_id="synthetic-admin", **values
    )


def baseline(database, plan):
    repo = IncrementalSyncRepository(database)
    run = repo.begin_collection(plan["id"], now())
    database.execute(
        "update \"knowledge.sync_run\" set phase='ACTIVATED',active=0 where id=?", (run["id"],)
    )
    return run


def test_idempotent_submission_conflict_and_replay_after_disable(database, plan):
    ops = OperationsRepository(database)
    operation = submit(ops, plan)
    database.execute('update "knowledge.sync_binding" set enabled=0')
    assert submit(ops, plan)["id"] == operation["id"]
    with pytest.raises(KnowledgeGovernanceError, match="idempotency_conflict"):
        ops.submit(kind="build", request_key="request-1", actor_id="synthetic-admin")
    assert len(ops.history()) == 1


@pytest.mark.parametrize(
    "values",
    [
        dict(kind="shell"),
        dict(kind="build", first_day="2024-01-01"),
        dict(kind="up", binding_id="anything"),
        dict(kind="build", request_key="$(id)"),
    ],
)
def test_reject_arbitrary_operations_and_parameters(database, values):
    with pytest.raises((KnowledgeGovernanceError, ValueError)):
        OperationsRepository(database).submit(
            **{"kind": "build", "request_key": "safe", "actor_id": "synthetic", **values}
        )


def test_deployment_operations_serialize_and_build_does_not_activate(database):
    ops = OperationsRepository(database)
    first = ops.submit(kind="build", request_key="a", actor_id="synthetic")
    with pytest.raises(KnowledgeGovernanceError, match="busy"):
        ops.submit(kind="stop", request_key="b", actor_id="synthetic")
    assert ops.runtime("deployment")["snapshot"] == {}
    ops.update(first["id"], state="SUCCEEDED")
    assert ops.submit(kind="stop", request_key="b", actor_id="synthetic")["state"] == "QUEUED"


def test_initial_schedule_is_immediate_and_pause_keeps_current_run(database, plan):
    repo = IncrementalSyncRepository(database)
    store = OperationsStore(database)
    store.schedule(binding_id=plan["id"], enabled=True, expected_revision=1)
    assert repo.scheduled_due(plan["id"], datetime.now(UTC))
    op = KnowledgeSyncScheduler(OperationsRepository(database)).select()
    assert op["kind"] == "sync"
    run = repo.begin_collection(plan["id"], now())
    store.schedule(binding_id=plan["id"], enabled=False, expected_revision=1)
    assert repo.binding(plan["id"])["enabled"] == 1
    assert repo.active_run(plan["id"])["id"] == run["id"]
    assert store.plan(plan["id"])["next_run_at"] is None


def test_completed_sync_waits_four_hours_without_accumulating_runs(database, plan):
    repo, ops = IncrementalSyncRepository(database), OperationsRepository(database)
    database.execute('update "knowledge.sync_binding" set schedule_enabled=1')
    operation = ops.start(submit(ops, plan)["id"])
    run = baseline(database, plan)
    ops.update(operation["id"], run_id=run["id"])
    scheduler = KnowledgeSyncScheduler(ops)
    before = datetime.now(UTC)
    scheduler.finish(operation, 0, None)
    binding = repo.binding(plan["id"])
    due = datetime.fromisoformat(binding["next_run_at"])
    assert binding["interval_seconds"] == 14400
    assert before + timedelta(hours=4) <= due <= datetime.now(UTC) + timedelta(hours=4)
    assert not repo.scheduled_due(plan["id"], due - timedelta(microseconds=1))
    assert repo.scheduled_due(plan["id"], due)
    assert scheduler.select() is None
    assert len(ops.history()) == 1


@pytest.mark.parametrize("engine", ["sqlite", "postgres"])
def test_four_hour_migration_preserves_existing_plans_and_run(
    engine, tmp_path, monkeypatch, request
):
    from app.modules.knowledge.infrastructure import sync_repository

    if engine == "postgres" and not os.getenv("MIGRATION_POSTGRES_DSN"):
        pytest.skip("requires isolated PostgreSQL")
    dsn = (
        request.getfixturevalue("postgres_database_dsn")
        if engine == "postgres"
        else "sqlite:///:memory:"
    )
    database = Database(dsn)
    historical = tmp_path / "head-152"
    historical.mkdir()
    shutil.copyfile(
        default_migrations_dir() / "legacy-v1-manifest.json", historical / "legacy-v1-manifest.json"
    )
    for entry in load_migration_catalog(default_migrations_dir()):
        if entry.version <= "152":
            shutil.copyfile(default_migrations_dir() / entry.name, historical / entry.name)
    try:
        Migrator(database, historical, migrator_build="interval-before").run()
        with monkeypatch.context() as patch:
            patch.setattr(sync_repository, "SYNC_INTERVAL_SECONDS", 3600)
            repo, binding = _enabled_binding(database)
            for suffix, enabled in (("first", True), ("disabled", False)):
                configuration = {
                    **binding["configuration_json"],
                    "base_codes": {
                        kind: code + suffix
                        for kind, code in binding["configuration_json"]["base_codes"].items()
                    },
                }
                fresh = repo.configure(
                    code=suffix,
                    source_code=suffix,
                    configuration=configuration,
                    expected_revision=0,
                )
                if enabled:
                    repo.set_collection_enabled(fresh["id"], enabled=True, expected_revision=1)
        ops = OperationsRepository(database)
        operation = ops.start(submit(ops, binding)["id"])
        run = repo.begin_collection(binding["id"], now())
        ops.update(operation["id"], run_id=run["id"])
        database.execute(
            f"update {repo.t('sync_binding')} set schedule_enabled=0 where id=?", (binding["id"],)
        )
        database.execute(
            f"update {repo.t('sync_binding')} set next_run_at=? where enabled=1",
            ("2026-11-05T04:00:00+00:00",),
        )
        before = database.execute(f"select * from {repo.t('sync_binding')} order by id")
        run_before, operation_before = repo.run(run["id"]), ops.operation(operation["id"])
        assert Migrator(
            database, default_migrations_dir(), migrator_build="interval-after"
        ).run().applied == schema_versions_after("152")
        after = database.execute(f"select * from {repo.t('sync_binding')} order by id")
        for old, new in zip(before, after, strict=True):
            assert old.pop("interval_seconds") == 3600 and new.pop("interval_seconds") == 14400
            old_due, new_due = old.pop("next_run_at"), new.pop("next_run_at")
            if old["id"] == binding["id"]:
                assert datetime.fromisoformat(str(new_due)) - datetime.fromisoformat(
                    str(old_due)
                ) == timedelta(hours=3)
            else:
                assert old_due == new_due
            assert old == new
        assert repo.run(run["id"]) == run_before
        assert ops.operation(operation["id"]) == operation_before
        SchemaHeadValidator(database, default_migrations_dir()).require_current()
        assert (
            Migrator(database, default_migrations_dir(), migrator_build="interval-replay")
            .run()
            .applied
            == ()
        )
        if engine == "sqlite":
            assert database.execute("PRAGMA foreign_key_check") == []
    finally:
        database.close()


def test_backfill_waits_for_current_run_then_preserves_range_on_restart(database, plan):
    baseline(database, plan)
    ops, repo = OperationsRepository(database), IncrementalSyncRepository(database)
    current = ops.start(submit(ops, plan)["id"])
    run = repo.begin_collection(plan["id"], now())
    ops.update(current["id"], run_id=run["id"])
    backfill = ops.submit(
        kind="backfill",
        binding_id=plan["id"],
        request_key="backfill",
        actor_id="synthetic",
        first_day="2024-01-02",
        last_day="2024-01-04",
    )
    scheduler = KnowledgeSyncScheduler(ops)
    assert scheduler.select()["id"] == current["id"]
    database.execute(
        "update \"knowledge.sync_run\" set active=0,phase='ACTIVATED' where id=?", (run["id"],)
    )
    scheduler.finish(current, 0, None)
    assert scheduler.select()["id"] == backfill["id"]
    ops.start(backfill["id"])
    resumed = OperationsRepository(database).operation(backfill["id"])
    command = scheduler.command(resumed, "python", "/qdrant/storage")
    assert command[-4:] == ["--from-date", "2024-01-02", "--through-date", "2024-01-04"]
    assert KnowledgeSyncScheduler(OperationsRepository(database)).select()["id"] == backfill["id"]


def test_crash_between_run_creation_and_link_reuses_original_operation(database, plan):
    ops = OperationsRepository(database)
    op = ops.start(submit(ops, plan)["id"])
    run = IncrementalSyncRepository(database).begin_collection(plan["id"], now())
    selected = KnowledgeSyncScheduler(ops).select()
    assert selected["id"] == op["id"]
    assert selected["run_id"] == run["id"]
    assert len(ops.history()) == 1


def test_retry_budget_and_explicit_retry_keep_identity(database, plan):
    ops = OperationsRepository(database)
    operation = submit(ops, plan)
    scheduler = KnowledgeSyncScheduler(ops)
    for attempt in range(1, 4):
        started = ops.start(operation["id"])
        scheduler.finish(started, 1, "knowledge_vector_timeout")
        latest = ops.operation(operation["id"])
        assert latest["state"] == ("RETRY_WAIT" if attempt < 3 else "FAILED")
    assert ops.retry(operation["id"])["id"] == operation["id"]
    assert ops.operation(operation["id"])["attempts"] == 0


def test_full_queue_still_consumes_existing_work(database, plan, monkeypatch):
    ops = OperationsRepository(database)
    queued = [submit(ops, plan, key=f"queued-{index}") for index in range(50)]
    scheduler = KnowledgeSyncScheduler(ops)
    # 另一个到期计划尝试入队时，队列满不能阻止消费已有任务。
    monkeypatch.setattr(
        scheduler,
        "_schedule_due",
        lambda: scheduler._enqueue(
            kind="sync",
            request_key="due-plan",
            actor_id="system:knowledge-sync",
            binding_id=plan["id"],
            automatic=True,
        ),
    )
    assert scheduler.select()["id"] == queued[0]["id"]
    assert len(ops.waiting(sync=True)) == 50


def test_scheduler_retains_safe_revision_event_and_transient_error(database, plan):
    ops = OperationsRepository(database)
    operation = submit(ops, plan)
    scheduler = KnowledgeSyncScheduler(ops)
    scheduler.observe(
        operation["id"],
        json.dumps(
            {
                "event": "knowledge_source_same_stamp_revised",
                "old_stamp": 1730000000,
                "new_stamp": 1730000000,
                "old_semantic_hash": "a" * 64,
                "new_semantic_hash": "b" * 64,
                "body": "DO-NOT-PERSIST",
            }
        ),
    )
    assert (
        scheduler.observe(
            operation["id"],
            json.dumps(
                {
                    "event": "knowledge_sync_failed",
                    "error_code": "knowledge_vector_timeout",
                }
            ),
        )
        == "knowledge_vector_timeout"
    )
    events = ops.events(operation_id=operation["id"])["events"]
    assert events[1]["details"]["old_stamp"] == 1730000000
    assert "DO-NOT-PERSIST" not in json.dumps(events)


def test_events_whitelist_and_cursor_are_bounded(database):
    ops = OperationsRepository(database)
    ops.event(
        None,
        "sync",
        "sync_event",
        {
            "document_id": "synthetic-doc",
            "processed": 2,
            "body": "DO-NOT-PERSIST",
            "token": "DO-NOT-PERSIST",
            "error_code": "contains spaces",
        },
    )
    events = ops.events()
    assert events["events"][0]["details"] == {"document_id": "synthetic-doc", "processed": 2}
    assert "DO-NOT-PERSIST" not in json.dumps(
        database.execute('select * from "knowledge.ops_event"')
    )
    assert ops.events(after=events["cursor"])["events"] == []
    with pytest.raises(KnowledgeGovernanceError):
        ops.events(after="bad")


def test_heartbeat_expiry_is_unknown_not_service_stopped(database):
    ops = OperationsRepository(database)
    ops.heartbeat("controller", {"services": [{"name": "knowledge-mcp", "state": "running"}]})
    database.execute(
        'update "knowledge.ops_runtime" set heartbeat_at=?',
        ((datetime.now(UTC) - timedelta(minutes=5)).isoformat(),),
    )
    status = ops.runtime("controller")
    assert not status["online"]
    assert status["snapshot"]["services"][0]["state"] == "running"


def test_http_auth_csrf_strict_payload_and_safe_snapshot(managed):
    runtime, client, *_ = managed
    path = "/api/platform/knowledge/operations"
    assert client.get(path).status_code in {401, 403}
    session = login(client)
    assert client.post(path, json={"kind": "build", "request_key": "ui"}).status_code == 403
    headers = csrf_headers(session)
    assert (
        client.post(
            path,
            headers=headers,
            json={"kind": "build", "request_key": "ui", "command": "rm -rf /"},
        ).status_code
        == 400
    )
    response = client.post(path, headers=headers, json={"kind": "build", "request_key": "ui"})
    assert response.status_code == 202
    duplicate = client.post(path, headers=headers, json={"kind": "build", "request_key": "ui"})
    assert duplicate.json()["id"] == response.json()["id"]
    snapshot = client.get(path).json()
    assert snapshot["operations"][0]["state"] == "QUEUED"
    assert not snapshot["controller"]["online"]


def test_plan_configuration_can_be_read_without_write_csrf(managed):
    runtime, client, *_ = managed
    _, binding = _enabled_binding(runtime.database)
    path = f"/api/platform/knowledge/operations/plans/{binding['id']}/configuration"
    assert client.get(path).status_code in {401, 403}
    login(client)
    response = client.get(path)
    assert response.status_code == 200
    assert response.json()["expected_revision"] == 1
    assert response.json()["configuration"]["collector"]["credential_ref"].startswith("secret://")


def test_only_controller_has_docker_socket_and_uses_main_compose():
    deploy = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    for name, service in deploy["services"].items():
        assert ("docker.sock" in json.dumps(service)) == (name == "knowledge-ops-controller")
    assert all(
        deploy["volumes"][name]["external"]
        for name in (
            "knowledge-models",
            "knowledge-reranker-models",
            "knowledge-qdrant",
            "knowledge-operation-state",
        )
    )
    controller = deploy["services"]["knowledge-ops-controller"]
    assert not controller.get("profiles")
    assert controller["environment"]["KNOWLEDGE_COMPOSE_PROJECT"] == "${COMPOSE_PROJECT_NAME}"


@pytest.mark.parametrize(
    "role, error, expected",
    [
        ("controller", "knowledge_ops_mount_invalid", 1),
        ("controller", None, 0),
        ("sync", "knowledge_collection_provider_unavailable", 0),
    ],
)
def test_controller_health_requires_valid_observation_without_changing_sync_health(
    monkeypatch, role, error, expected
):
    from types import SimpleNamespace
    from app.cli import knowledge_ops

    monkeypatch.setenv("DATABASE_DSN", "synthetic")
    monkeypatch.setattr(knowledge_ops, "Database", lambda _: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(
        knowledge_ops,
        "SchemaHeadValidator",
        lambda *_: SimpleNamespace(require_current=lambda: None),
    )
    monkeypatch.setattr(
        knowledge_ops,
        "OperationsRepository",
        lambda _: SimpleNamespace(
            runtime=lambda _: {"online": True, "snapshot": {"error_code": error}}
        ),
    )
    assert knowledge_ops.main(["health", "--role", role]) == expected


def test_start_uses_fixed_main_file_and_never_recurses_platform_dependencies(
    database, tmp_path, monkeypatch
):
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    monkeypatch.setenv("KNOWLEDGE_DEPLOY_ROOT", str(tmp_path))
    monkeypatch.setenv("COMPOSE_FILE", "/untrusted/compose.yml")
    monkeypatch.setenv("DOCKER_CONTEXT", "untrusted")
    ops = OperationsRepository(database)
    compose = KnowledgeCompose(ops, Event())
    compose._environment = docker_environment()
    command = compose.command("ps")
    assert command[command.index("-f") + 1] == str(tmp_path / "docker-compose.yml")
    assert (
        "COMPOSE_FILE" not in compose.environment()
        and "DOCKER_CONTEXT" not in compose.environment()
    )
    calls = []
    monkeypatch.setattr(
        compose, "_run", lambda operation, stage, args, **kwargs: calls.append(args)
    )
    # A direct main-Compose build must not require a previous web build operation.
    compose.start({"id": "synthetic"})
    starts = [c for c in calls if c[0] == "up"]
    assert len(starts) == 2 and all("--no-deps" in c and "--no-build" in c for c in starts)
    assert all("--no-deps" in c for c in calls if c[0] == "run")
    assert not any(
        set(c) & {"postgres", "migrator", "api-server", "knowledge-ops-controller", "down"}
        for c in calls
    )


def test_stop_order_and_reconciliation_do_not_replay_build(database, tmp_path, monkeypatch):
    env = tmp_path / "docker-compose.yml"
    env.write_text("# synthetic\n")
    monkeypatch.setenv("KNOWLEDGE_DEPLOY_ROOT", str(tmp_path))
    ops = OperationsRepository(database)
    compose = KnowledgeCompose(ops, Event())
    op = ops.start(ops.submit(kind="stop", request_key="stop", actor_id="synthetic")["id"])
    calls = []
    monkeypatch.setattr(
        compose, "_run", lambda operation, stage, args, **kwargs: calls.append(args)
    )
    monkeypatch.setattr(
        compose,
        "services",
        lambda: [{"name": "knowledge-sync", "state": "exited", "health": "none"}],
    )
    compose.execute(op)
    assert calls[0] == ["stop", "--timeout", "240", "knowledge-sync"]
    assert "knowledge-qdrant" in calls[1]
    assert not any("down" in c or "postgres" in c for c in calls)
    compose.reconcile(op)
    assert ops.operation(op["id"])["state"] == "SUCCEEDED"
    build = ops.start(ops.submit(kind="build", request_key="build", actor_id="synthetic")["id"])
    compose.reconcile(build)
    assert ops.operation(build["id"])["state"] == "INTERRUPTED"
    assert len(calls) == 2


def test_owned_process_output_is_bounded_and_lock_is_exclusive(tmp_path):
    lock = tmp_path / "owned.lock"
    with exclusive_process(lock):
        with pytest.raises(BlockingIOError):
            with exclusive_process(lock):
                pytest.fail("second owner")
    lines = []
    code = "print('x'*20000); print('safe')"
    assert (
        run_process(
            [sys.executable, "-c", code], stop=Event(), heartbeat=lambda: None, line=lines.append
        )
        == 0
    )
    assert lines == ["safe"]


@pytest.mark.skipif(
    not os.getenv("KNOWLEDGE_OPS_TEST_POSTGRES_DSN"), reason="requires isolated PostgreSQL"
)
def test_real_postgres_concurrent_idempotency_and_persisted_recovery():
    dsn = os.environ["KNOWLEDGE_OPS_TEST_POSTGRES_DSN"]
    database = Database(dsn)
    try:
        Migrator(database, default_migrations_dir(), migrator_build="knowledge-ops-synthetic").run()
        SchemaHeadValidator(database, default_migrations_dir()).require_current()
        key = "concurrent-" + uuid4().hex

        def request(_):
            connection = Database(dsn)
            try:
                return OperationsRepository(connection).submit(
                    kind="build", request_key=key, actor_id="synthetic-concurrent"
                )["id"]
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=4) as pool:
            identifiers = list(pool.map(request, range(12)))
        assert len(set(identifiers)) == 1
        ops = OperationsRepository(database)
        started = ops.start(identifiers[0])
        assert started["state"] == "RUNNING"
        recovered = OperationsRepository(database).operation(started["id"])
        assert recovered["attempts"] == 1
        ops.update(started["id"], state="INTERRUPTED", error_code="knowledge_ops_interrupted")
        assert ops.retry(started["id"])["id"] == identifiers[0]
        ops.update(started["id"], state="SUCCEEDED")
        suffix = uuid4().hex[:12]
        sync = IncrementalSyncRepository(database)
        binding = sync.configure(
            code="pg-plan-" + suffix,
            source_code="pg-source-" + suffix,
            expected_revision=0,
            configuration={
                "base_codes": {
                    kind: "pg-" + kind + suffix for kind in ("defect", "ticket", "requirement")
                },
                "resource_ids": [],
                "collector": {
                    "provider_origin": "https://ones.example.test",
                    "team_id": "synthetic-team",
                    "project_ids": ["synthetic-project"],
                    "issue_types": {
                        kind: [kind + "-type"] for kind in ("defect", "ticket", "requirement")
                    },
                    "child_type_ids": ["child-type"],
                    "first_date": "2024-01-01",
                    "credential_ref": "secret://platform/synthetic-collector",
                },
            },
        )
        sync.set_collection_enabled(binding["id"], enabled=True, expected_revision=1)
        operation = ops.start(submit(ops, binding, key="pg-sync-" + suffix)["id"])
        # PostgreSQL JSONB 是 dict、时间列是 datetime，必须与 SQLite 续跑行为一致。
        run = sync.begin_collection(binding["id"], now())
        selected = KnowledgeSyncScheduler(ops).select()
        assert selected["id"] == operation["id"]
        assert selected["run_id"] == run["id"]
        projection = OperationsStore(database).plan(binding["id"])
        assert len(projection["bases"]) == 3
        assert projection["run"]["collection"]["completed_days"] == 0
        database.execute(
            f"update {sync.t('sync_run')} set active=0,phase='ACTIVATED' where id=?", (run["id"],)
        )
        KnowledgeSyncScheduler(ops).finish(selected, 0, None)
        OperationsStore(database).schedule(
            binding_id=binding["id"], enabled=False, expected_revision=1
        )
    finally:
        database.close()


@pytest.mark.parametrize(
    "line,action,position",
    [
        ("#1 [internal] load local bake definitions", "load_build_definition", None),
        ("#2 [internal] load build context", "load_build_context", None),
        (
            "#3 [internal] load metadata for private.invalid/team/image:tag",
            "load_image_metadata",
            None,
        ),
        ("#4 [auth] private/image:pull token for registry.invalid", "registry_auth", None),
        (
            "#11 [knowledge-embedding 4/11] RUN pip install --require-hashes -r /tmp/runtime.lock",
            "install_python_dependencies",
            (4, 11),
        ),
        (
            "#5 [api python-deps 3/7] RUN python -c \"subprocess.run(['pip', 'install', 'package'])\"",
            "install_python_dependencies",
            (3, 7),
        ),
        (
            "#6 [knowledge-embedding 5/11] COPY backend/app/modules/knowledge/embedding_model.json /app/",
            "copy_model_configuration",
            (5, 11),
        ),
        (
            "#7 [knowledge-mcp 2/4] COPY services/knowledge_mcp_server /app/services/",
            "copy_application_code",
            (2, 4),
        ),
        (
            "#8 [knowledge-embedding 6/11] COPY backend/app/modules/knowledge/embedding_runtime.lock /tmp/",
            "copy_dependency_manifests",
            (6, 11),
        ),
        ("#9 [stage 1/3] RUN groupadd --gid 10007 embedding", "configure_runtime_user", (1, 3)),
        ("#10 [stage 4/3] WORKDIR /private/path", "configure_workdir", None),
        ("#12 exporting to image", "export_image", None),
        ("#13 resolving provenance for metadata file", "resolve_provenance", None),
    ],
)
def test_build_step_description_is_structured_without_raw_output(line, action, position):
    from app.modules.knowledge.infrastructure.operations_compose import build_step_details
    from app.modules.knowledge.domain.operations import safe_details

    details = build_step_details(line)
    assert details is not None and details["build_action"] == action
    assert safe_details(details) == details
    assert set(details) == (
        {"step", "build_action", "stage_step", "stage_total"}
        if position
        else {"step", "build_action"}
    )
    if position:
        assert (details["stage_step"], details["stage_total"]) == position
    assert "private" not in json.dumps(details) and "token" not in json.dumps(details)


def test_build_events_keep_parallel_step_order_and_never_persist_commands(database, monkeypatch):
    from app.modules.knowledge.infrastructure import operations_compose

    ops = OperationsRepository(database)
    compose = KnowledgeCompose(ops, Event())
    compose._environment = docker_environment()
    op = ops.start(ops.submit(kind="build", request_key="safe-build", actor_id="synthetic")["id"])

    def process(*args, line, **kwargs):
        for raw in (
            "#11 [stage 4/11] RUN pip install --index-url https://synthetic-secret.invalid package",
            "#3 [internal] load build context",
            "#11 [stage 4/11] RUN pip install repeated-output",
            "#11 0.2 synthetic-secret-command-output",
            "#11 DONE 1.0s",
            "#3 CACHED",
            "#12 exporting to image",
        ):
            line(raw)
        return 0

    monkeypatch.setattr(operations_compose, "run_process", process)
    compose._run(op, "building", ["build", "knowledge-embedding"], service="knowledge-embedding")
    events = [e for e in ops.events(operation_id=op["id"])["events"] if e["code"] == "build_step"]
    assert [e["details"]["step"] for e in events] == [11, 3, 12]
    assert events[0]["details"]["build_action"] == "install_python_dependencies"
    assert "synthetic-secret" not in json.dumps(events) and "repeated-output" not in json.dumps(
        events
    )


def test_build_action_is_a_closed_safety_projection():
    from app.modules.knowledge.domain.operations import safe_details

    assert safe_details(
        {"step": 11, "build_action": "synthetic-private-value", "command": "synthetic-secret"}
    ) == {"step": 11}
