from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from fastapi.testclient import TestClient

from app import main as app_main
from app.bootstrap import build_test_container
from app.main import create_app
from app.modules.platform_config.infrastructure import PlatformConfigRepository
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import Migrator
from app.shared.runtime_config_loader import load_settings_with_db_overlay
from backend.tests.helpers import container
from backend.tests.helpers import test_settings as make_test_settings
from backend.tests.test_unified_identity_rbac import csrf_headers, login, unified_settings


def test_repeating_builtin_definition_sync_is_observably_unchanged() -> None:
    runtime = container()
    service = runtime.platform_config_service
    repository = service.repository
    before_definitions = service.list_runtime_config_definitions()
    before_revision = repository.runtime_config_revision()
    before_audit = repository.list_config_audit(limit=500)

    result = service.ensure_runtime_config_definitions(actor_id="user_local_admin")

    assert result == {
        "revision": before_revision,
        "created": 0,
        "updated": 0,
        "unchanged": len(before_definitions),
    }
    assert service.list_runtime_config_definitions() == before_definitions
    assert repository.runtime_config_revision() == before_revision
    assert repository.list_config_audit(limit=500) == before_audit


def test_definition_reconciliation_normalizes_semantic_fields() -> None:
    runtime = container()
    service = runtime.platform_config_service
    first = service.upsert_runtime_config_definition(
        {
            "key": "SEMANTIC_CONFIG",
            "value_type": "string",
            "default": {"beta": 2, "alpha": [1, 2]},
            "service_names": ["worker-b", "worker-a", "worker-b"],
            "description": "line one\r\nline two",
        },
        actor_id="user_local_admin",
    )
    audit_after_first = service.repository.list_config_audit(limit=500)

    second = service.upsert_runtime_config_definition(
        {
            "key": "SEMANTIC_CONFIG",
            "value_type": "string",
            "default": {"alpha": [1, 2], "beta": 2},
            "service_names": ["worker-a", "worker-b"],
            "description": "line one\nline two",
        },
        actor_id="user_local_admin",
    )

    assert second == first
    assert second["service_names"] == ["worker-a", "worker-b"]
    assert service.repository.list_config_audit(limit=500) == audit_after_first


def test_builtin_sync_reports_and_audits_only_real_changes() -> None:
    runtime = container()
    service = runtime.platform_config_service
    builtin = service.repository.get_runtime_config_definition("ANTHROPIC_MODEL")
    assert builtin is not None
    service.upsert_runtime_config_definition(
        {
            "key": builtin["key"],
            "value_type": builtin["value_type"],
            "default": builtin["default"],
            "sensitive": builtin["sensitive"],
            "bootstrap_only": builtin["bootstrap_only"],
            "service_names": builtin["service_names"],
            "description": "temporary semantic drift",
            "status": builtin["status"],
        },
        actor_id="user_local_admin",
    )
    audit_before_sync = service.repository.list_config_audit(limit=500)

    result = service.ensure_runtime_config_definitions(actor_id="user_local_admin")

    assert result["created"] == 0
    assert result["updated"] == 1
    assert result["unchanged"] > 0
    audit_after_sync = service.repository.list_config_audit(limit=500)
    assert len(audit_after_sync) == len(audit_before_sync) + 1
    assert audit_after_sync[0]["after"]["updated"] == 1

    repeated = service.ensure_runtime_config_definitions(actor_id="user_local_admin")
    assert repeated["updated"] == 0
    assert service.repository.list_config_audit(limit=500) == audit_after_sync


def test_stale_expected_revision_reconciles_same_target_as_unchanged() -> None:
    runtime = container()
    repository = runtime.platform_config_service.repository
    created = repository.upsert_runtime_config_definition(
        key="CONCURRENT_CONFIG",
        value_type="string",
        default="old",
        description="old",
    )
    assert created.outcome == "created"

    updated = repository.upsert_runtime_config_definition(
        key="CONCURRENT_CONFIG",
        value_type="string",
        default="new",
        description="new",
        expected_revision=created.entity["revision"],
    )
    stale_retry = repository.upsert_runtime_config_definition(
        key="CONCURRENT_CONFIG",
        value_type="string",
        default="new",
        description="new",
        expected_revision=created.entity["revision"],
    )

    assert updated.outcome == "updated"
    assert updated.entity["revision"] == 2
    assert stale_retry.outcome == "unchanged"
    assert stale_retry.entity["revision"] == 2


def test_sqlite_concurrent_reconciliation_counts_each_real_change_once(tmp_path) -> None:
    database = Database(
        f"sqlite:///{tmp_path / 'runtime-config.db'}",
        pool_min_size=0,
        pool_max_size=8,
    )
    Migrator(database, default_migrations_dir(), migrator_build="runtime-config-test").run()
    repository = PlatformConfigRepository(database)

    def reconcile(description: str, barrier: Barrier):
        barrier.wait()
        return repository.upsert_runtime_config_definition(
            key="CONCURRENT_SQLITE_CONFIG",
            value_type="string",
            default="value",
            description=description,
        )

    create_barrier = Barrier(8)
    with ThreadPoolExecutor(max_workers=8) as executor:
        created = list(executor.map(lambda _: reconcile("initial", create_barrier), range(8)))
    assert [result.outcome for result in created].count("created") == 1
    assert [result.outcome for result in created].count("unchanged") == 7

    update_barrier = Barrier(8)
    with ThreadPoolExecutor(max_workers=8) as executor:
        updated = list(executor.map(lambda _: reconcile("changed", update_barrier), range(8)))
    assert [result.outcome for result in updated].count("updated") == 1
    assert [result.outcome for result in updated].count("unchanged") == 7
    stored = repository.get_runtime_config_definition("CONCURRENT_SQLITE_CONFIG")
    assert stored is not None
    assert stored["description"] == "changed"
    assert stored["revision"] == 2
    database.close()


def test_definition_reads_report_missing_builtin_without_recreating_it() -> None:
    settings = unified_settings()
    runtime = build_test_container(settings, migrate=True, seed=True)
    missing_key = "WEBHOOK_MAX_JSON_DEPTH"
    runtime.database.execute(
        "delete from platform_runtime_config_definition where key = ?",
        (missing_key,),
    )
    before_revision = runtime.platform_config_service.repository.runtime_config_revision()
    before_audit = runtime.platform_config_service.repository.list_config_audit(limit=500)
    app = create_app(settings, container_factory=lambda _: runtime)

    with TestClient(app) as client:
        login(client)
        definitions_response = client.get("/api/platform/runtime-config/definitions")
        snapshot_response = client.get("/api/platform/runtime-config/snapshot")
        stored_after = (
            runtime.platform_config_service.repository.get_runtime_config_definition(missing_key)
        )
        revision_after = runtime.platform_config_service.repository.runtime_config_revision()
        audit_after = runtime.platform_config_service.repository.list_config_audit(limit=500)

    assert definitions_response.status_code == 200
    assert snapshot_response.status_code == 200
    assert missing_key not in {
        definition["key"] for definition in definitions_response.json()["definitions"]
    }
    assert definitions_response.json()["diagnostics"] == [
        {
            "code": "runtime_config_definition_missing",
            "keys": [missing_key],
        }
    ]
    snapshot = snapshot_response.json()["snapshot"]
    assert snapshot["source"] == "database-invalid"
    assert snapshot["errors"] == [f"runtime_config_definition_missing:{missing_key}"]
    assert stored_after is None
    assert revision_after == before_revision
    assert audit_after == before_audit


def test_authorized_runtime_config_reads_are_repeatable_and_write_free() -> None:
    settings = unified_settings()
    runtime = build_test_container(settings, migrate=True, seed=True)
    app = create_app(settings, container_factory=lambda _: runtime)

    with TestClient(app) as client:
        assert client.get("/api/platform/runtime-config/definitions").status_code == 401
        login(client)
        before_definitions = runtime.platform_config_service.list_runtime_config_definitions()
        before_revision = runtime.platform_config_service.repository.runtime_config_revision()
        before_audit = runtime.platform_config_service.repository.list_config_audit(limit=500)
        responses = [
            client.get("/api/platform/runtime-config/definitions"),
            client.get("/api/platform/runtime-config/definitions"),
            client.get("/api/platform/runtime-config/snapshot"),
            client.get("/api/platform/runtime-config/snapshot"),
        ]
        after_definitions = runtime.platform_config_service.list_runtime_config_definitions()
        after_revision = runtime.platform_config_service.repository.runtime_config_revision()
        after_audit = runtime.platform_config_service.repository.list_config_audit(limit=500)

    assert all(response.status_code == 200 for response in responses)
    assert after_definitions == before_definitions
    assert after_revision == before_revision
    assert after_audit == before_audit


def test_explicit_admin_sync_repairs_missing_definition_once() -> None:
    settings = unified_settings()
    runtime = build_test_container(settings, migrate=True, seed=True)
    missing_key = "WEBHOOK_MAX_JSON_DEPTH"
    runtime.database.execute(
        "delete from platform_runtime_config_definition where key = ?",
        (missing_key,),
    )
    app = create_app(settings, container_factory=lambda _: runtime)

    with TestClient(app) as client:
        csrf = login(client)
        denied = client.post("/api/platform/runtime-config/definitions/sync")
        first = client.post(
            "/api/platform/runtime-config/definitions/sync",
            headers=csrf_headers(csrf),
        )
        audit_after_first = runtime.platform_config_service.repository.list_config_audit(limit=500)
        second = client.post(
            "/api/platform/runtime-config/definitions/sync",
            headers=csrf_headers(csrf),
        )
        audit_after_second = runtime.platform_config_service.repository.list_config_audit(
            limit=500
        )

    assert denied.status_code == 403
    assert first.status_code == 200
    assert first.json()["sync"]["created"] == 1
    assert second.status_code == 200
    assert second.json()["sync"]["created"] == 0
    assert second.json()["sync"]["updated"] == 0
    assert audit_after_second == audit_after_first


def test_controlled_initialization_failure_returns_degraded_without_partial_registration(
    tmp_path,
) -> None:
    database = Database(f"sqlite:///{tmp_path / 'blocked-registration.db'}")
    Migrator(database, default_migrations_dir(), migrator_build="runtime-config-test").run()
    database.execute(
        """
        create trigger block_runtime_definition_insert
        before insert on platform_runtime_config_definition
        begin
          select raise(abort, 'definition registration blocked');
        end
        """
    )

    loaded = load_settings_with_db_overlay(
        make_test_settings(),
        service_name="api-server",
        database=database,
    )
    readiness = app_main._runtime_config_status(loaded)["runtime_config"]

    assert loaded.runtime_config_source == "env-fallback"
    assert loaded.runtime_config_degraded is True
    assert "definition registration blocked" in str(loaded.runtime_config_errors)
    assert readiness["source"] == "env-fallback"
    assert readiness["degraded"] is True
    assert "definition registration blocked" in str(readiness["errors"])
    assert database.execute_one(
        "select count(*) as count from platform_runtime_config_definition"
    ) == {"count": 0}
    database.close()


def test_aggregate_revision_changes_when_lower_revision_value_changes() -> None:
    runtime = container()
    service = runtime.platform_config_service
    service.upsert_runtime_config_definition(
        {
            "key": "LOW_REV_CONFIG",
            "value_type": "int",
            "default": 0,
        },
        actor_id="user_local_admin",
    )
    service.upsert_runtime_config_value(
        {"key": "LOW_REV_CONFIG", "value": 1},
        actor_id="user_local_admin",
    )
    builtin = service.repository.get_runtime_config_definition("ANTHROPIC_MODEL")
    assert builtin is not None
    for revision in range(6):
        service.upsert_runtime_config_definition(
            {
                "key": builtin["key"],
                "value_type": builtin["value_type"],
                "default": builtin["default"],
                "sensitive": builtin["sensitive"],
                "bootstrap_only": builtin["bootstrap_only"],
                "service_names": builtin["service_names"],
                "description": f"higher revision {revision}",
                "status": builtin["status"],
            },
            actor_id="user_local_admin",
        )
    before = service.runtime_config_snapshot()

    service.upsert_runtime_config_value(
        {"key": "LOW_REV_CONFIG", "value": 2},
        actor_id="user_local_admin",
    )
    after = service.runtime_config_snapshot()

    assert after["revision"] != before["revision"]
    assert after["config_hash"] != before["config_hash"]


def test_aggregate_version_tracks_supported_changes_and_repeated_snapshots_are_stable() -> None:
    runtime = container(configure_seed_secrets=False)
    service = runtime.platform_config_service
    initial = service.runtime_config_snapshot()

    service.upsert_runtime_config_definition(
        {
            "key": "VERSIONED_CONFIG",
            "value_type": "int",
            "default": 1,
        },
        actor_id="user_local_admin",
    )
    after_definition = service.runtime_config_snapshot()
    value = service.upsert_runtime_config_value(
        {"key": "VERSIONED_CONFIG", "value": 2},
        actor_id="user_local_admin",
    )
    after_value = service.runtime_config_snapshot()
    service.set_runtime_config_value_status(
        value["id"],
        "disabled",
        actor_id="user_local_admin",
    )
    after_disable = service.runtime_config_snapshot()
    service.create_platform_secret(
        {"code": "versioned_secret", "value": "synthetic-secret-value"},
        actor_id="user_local_admin",
    )
    after_secret_create = service.runtime_config_snapshot()
    service.rotate_platform_secret(
        "versioned_secret",
        {"value": "synthetic-rotated-value"},
        actor_id="user_local_admin",
    )
    after_secret_rotate = service.runtime_config_snapshot()
    service.disable_platform_secret(
        "versioned_secret",
        actor_id="user_local_admin",
    )
    after_secret_disable = service.runtime_config_snapshot()
    repeated = service.runtime_config_snapshot()

    revisions = [
        initial["revision"],
        after_definition["revision"],
        after_value["revision"],
        after_disable["revision"],
        after_secret_create["revision"],
        after_secret_rotate["revision"],
        after_secret_disable["revision"],
    ]
    assert all(current > previous for previous, current in zip(revisions, revisions[1:]))
    assert after_definition["config_hash"] != initial["config_hash"]
    assert after_value["config_hash"] != after_definition["config_hash"]
    assert after_disable["config_hash"] != after_value["config_hash"]
    assert repeated == after_secret_disable
    assert "synthetic-secret-value" not in str(repeated)
    assert "synthetic-rotated-value" not in str(repeated)
