from __future__ import annotations

import copy

import pytest

from app.modules.mcp_resources.service import McpResourceService, validate_manifest
from app.shared.database import Database, default_migrations_dir
from app.shared.exceptions import NonRetryableExecutionError
from app.shared.migrations import Migrator


NOW = "2026-08-08T00:00:00+00:00"


@pytest.fixture
def database() -> Database:
    value = Database("sqlite:///:memory:")
    Migrator(value, default_migrations_dir(), migrator_build="mcp-resource-test").run()
    value.execute(
        """
        insert into app_user
          (id, username, display_name, email, status, account_type,
           revision, created_at, updated_at)
        values ('admin-1', 'admin', 'Admin', '', 'enabled', 'human', 1, ?, ?)
        """,
        (NOW, NOW),
    )
    value.execute(
        """
        insert into platform_secret
          (id, code, provider, ref, purpose, status, active_version,
           masked_summary, metadata_json, revision, created_at, updated_at)
        values ('secret-1', 'mes_db_password', 'encrypted_db',
                'secret://platform/mes_db_password', 'test', 'enabled', 1,
                '***', '{}', 1, ?, ?)
        """,
        (NOW, NOW),
    )
    value.execute(
        """
        insert into platform_secret_version
          (id, secret_id, version, ciphertext, nonce, key_id, algorithm,
           status, created_by, created_at)
        values ('secret-version-1', 'secret-1', 1, 'ciphertext', 'nonce',
                'key', 'AES-256-GCM-AAD-V1', 'active', 'admin-1', ?)
        """,
        (NOW,),
    )
    try:
        yield value
    finally:
        value.close()


def _manifest() -> dict:
    return {
        "api_version": "enterprise-agent/v1",
        "kind": "DATABASE",
        "metadata": {"code": "mes_db", "name": "MES Database"},
        "spec": {
            "provider": "mysql",
            "host": "mysql.internal",
            "port": 3306,
            "database": "mes",
            "username": "readonly_user",
            "password_ref": "secret://platform/mes_db_password",
            "allowed_tables": ["work_order", "defect"],
            "max_rows": 100,
            "timeout_seconds": 5,
            "tls": True,
        },
    }


def test_manifest_is_strict_and_rejects_plaintext_or_reserved_secret_providers() -> None:
    canonical, content_hash, refs = validate_manifest(_manifest())
    assert canonical["kind"] == "DATABASE"
    assert len(content_hash) == 64
    assert refs == ("secret://platform/mes_db_password",)

    plaintext = _manifest()
    plaintext["spec"]["password"] = "do-not-store"
    with pytest.raises(ValueError, match="unknown fields"):
        validate_manifest(plaintext)

    for unsupported in ("env:DB_PASSWORD", "vault:secret/db", "kms:key/db"):
        invalid = _manifest()
        invalid["spec"]["password_ref"] = unsupported
        with pytest.raises(ValueError):
            validate_manifest(invalid)


def test_resource_draft_verify_publish_generation_and_unpublish(database: Database) -> None:
    service = McpResourceService(database, verifier=lambda manifest: {"connection": "ok"})
    planned = service.plan(_manifest())
    assert planned["action"] == "CREATE"
    assert planned["secret_refs"] == ["secret://platform/<redacted>"]

    applied = service.apply(
        _manifest(),
        actor_id="admin-1",
        expected_revision=0,
        idempotency_key="apply-mes-db-v1",
    )
    assert applied["status"] == "DRAFT"
    assert (
        service.apply(
            _manifest(),
            actor_id="admin-1",
            expected_revision=0,
            idempotency_key="apply-mes-db-v1",
        )
        == applied
    )

    verified = service.verify("mes_db", actor_id="admin-1", expected_revision=1)
    assert verified["status"] == "PASSED"
    published = service.publish(
        "mes_db",
        actor_id="admin-1",
        expected_revision=1,
        idempotency_key="publish-mes-db-v1",
    )
    assert published["generation_status"] == "BUILDING"
    assert service.status("mes_db")["deployment"]["generation_status"] == "BUILDING"

    activated = service.activate_generation(published["generation_id"], success=True)
    assert activated["status"] == "ACTIVE"
    assert service.status("mes_db")["deployment"]["generation_status"] == "ACTIVE"

    unpublished = service.unpublish("mes_db", actor_id="admin-1", expected_revision=2)
    assert unpublished["status"] == "DISABLED"
    assert service.status("mes_db")["deployment"]["status"] == "DISABLED"

    restored_draft = service.draft_from_revision(
        "mes_db",
        published["resource_revision_id"],
        actor_id="admin-1",
        expected_revision=3,
        idempotency_key="restore-mes-db-v1",
    )
    assert restored_draft["revision"] == 4
    service.verify("mes_db", actor_id="admin-1", expected_revision=4)
    restored = service.publish(
        "mes_db",
        actor_id="admin-1",
        expected_revision=4,
        idempotency_key="publish-restored-mes-db-v1",
    )
    assert restored["resource_revision"] == 2
    assert restored["resource_revision_id"] != published["resource_revision_id"]


def test_failed_secret_generation_reports_degraded_and_preserves_exact_lkg(
    database: Database,
) -> None:
    service = McpResourceService(database)
    service.apply(
        _manifest(),
        actor_id="admin-1",
        expected_revision=0,
        idempotency_key="apply-degraded",
    )
    service.verify("mes_db", actor_id="admin-1", expected_revision=1)
    published = service.publish(
        "mes_db",
        actor_id="admin-1",
        expected_revision=1,
        idempotency_key="publish-degraded",
    )
    service.activate_generation(published["generation_id"], success=True)
    database.execute(
        """
        insert into mcp_resource_generation
          (id, deployment_id, resource_revision_id, generation,
           secret_versions_hash, status, safe_error_code, created_at,
           claimed_at, builder_id, activated_at)
        select 'generation-failed', deployment_id, resource_revision_id, generation + 1,
               secret_versions_hash, 'BUILDING', '', ?, null, '', null
          from mcp_resource_generation where id = ?
        """,
        (NOW, published["generation_id"]),
    )
    service.activate_generation(
        "generation-failed",
        success=False,
        safe_error_code="provider_verification_failed",
    )

    deployment = service.status("mes_db")["deployment"]
    assert deployment["generation_status"] == "DEGRADED"
    assert deployment["safe_error_code"] == "provider_verification_failed"
    row = database.execute_one(
        """
        select current_generation_id, last_known_good_generation_id
          from mcp_resource_deployment where id = ?
        """,
        (published["deployment_id"],),
    )
    assert row == {
        "current_generation_id": published["generation_id"],
        "last_known_good_generation_id": published["generation_id"],
    }


def test_revision_conflict_and_new_revision_cannot_float_to_old_lkg(database: Database) -> None:
    service = McpResourceService(database)
    service.apply(_manifest(), actor_id="admin-1", expected_revision=0, idempotency_key="apply-1")
    service.verify("mes_db", actor_id="admin-1", expected_revision=1)
    first = service.publish(
        "mes_db", actor_id="admin-1", expected_revision=1, idempotency_key="publish-1"
    )
    service.activate_generation(first["generation_id"], success=True)

    changed = copy.deepcopy(_manifest())
    changed["spec"]["max_rows"] = 50
    with pytest.raises(NonRetryableExecutionError) as conflict:
        service.apply(changed, actor_id="admin-1", expected_revision=1, idempotency_key="stale")
    assert conflict.value.error_code == "revision_conflict"

    service.apply(changed, actor_id="admin-1", expected_revision=2, idempotency_key="apply-2")
    service.verify("mes_db", actor_id="admin-1", expected_revision=3)
    second = service.publish(
        "mes_db", actor_id="admin-1", expected_revision=3, idempotency_key="publish-2"
    )
    service.activate_generation(
        second["generation_id"], success=False, safe_error_code="connection_failed"
    )
    deployment = service.status("mes_db")["deployment"]
    assert deployment["resource_revision_id"] == second["resource_revision_id"]
    assert deployment["generation_status"] == "FAILED"
    row = database.execute_one(
        "select current_generation_id, last_known_good_generation_id from mcp_resource_deployment where id = ?",
        (second["deployment_id"],),
    )
    assert row == {"current_generation_id": "", "last_known_good_generation_id": ""}


def test_idempotency_key_cannot_be_reused_for_changed_manifest(database: Database) -> None:
    service = McpResourceService(database)
    service.apply(_manifest(), actor_id="admin-1", expected_revision=0, idempotency_key="same-key")
    changed = _manifest()
    changed["spec"]["max_rows"] = 10
    with pytest.raises(NonRetryableExecutionError) as raised:
        service.apply(changed, actor_id="admin-1", expected_revision=1, idempotency_key="same-key")
    assert raised.value.error_code == "mcp_idempotency_conflict"


def test_secret_invalidation_and_multiple_active_deployments_fail_closed(
    database: Database,
) -> None:
    service = McpResourceService(database)
    service.apply(_manifest(), actor_id="admin-1", expected_revision=0, idempotency_key="apply")
    database.execute("update platform_secret set status = 'disabled' where id = 'secret-1'")
    with pytest.raises(NonRetryableExecutionError):
        service.verify("mes_db", actor_id="admin-1", expected_revision=1)

    database.execute("update platform_secret set status = 'enabled' where id = 'secret-1'")
    service.verify("mes_db", actor_id="admin-1", expected_revision=1)
    published = service.publish(
        "mes_db", actor_id="admin-1", expected_revision=1, idempotency_key="publish"
    )
    deployment = database.execute_one(
        "select * from mcp_resource_deployment where id = ?",
        (published["deployment_id"],),
    )
    with pytest.raises(Exception):
        database.execute(
            """
            insert into mcp_resource_deployment
              (id, resource_id, server_code, resource_revision_id, status,
               revision, current_generation_id, last_known_good_generation_id,
               updated_by, created_at, updated_at)
            values ('deployment-conflict', ?, 'data-mcp', ?, 'ACTIVE', 1,
                    '', '', 'admin-1', ?, ?)
            """,
            (
                deployment["resource_id"],
                deployment["resource_revision_id"],
                NOW,
                NOW,
            ),
        )
