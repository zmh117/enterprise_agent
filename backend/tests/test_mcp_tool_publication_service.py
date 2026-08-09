from __future__ import annotations

import json

import pytest

from app.modules.audit.application.audit_service import AuditService
from app.modules.job.infrastructure.repositories import AuditRepository
from app.modules.mcp_resources import McpResourceService
from app.modules.mcp_tool_publications import McpToolPublicationService
from app.shared.database import Database, default_migrations_dir
from app.shared.exceptions import NonRetryableExecutionError
from app.shared.migrations import Migrator


NOW = "2026-08-09T00:00:00+00:00"


@pytest.fixture
def database() -> Database:
    value = Database("sqlite:///:memory:")
    Migrator(value, default_migrations_dir(), migrator_build="mcp-tool-publication-test").run()
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
        values ('secret-1', 'db_password', 'encrypted_db',
                'secret://platform/db_password', 'test', 'enabled', 1,
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


def _database_manifest() -> dict:
    return {
        "api_version": "enterprise-agent/v1",
        "kind": "DATABASE",
        "metadata": {"code": "mes_db", "name": "MES Database"},
        "spec": {
            "provider": "mysql",
            "host": "mysql.internal",
            "port": 3306,
            "database": "mes",
            "username": "readonly",
            "password_ref": "secret://platform/db_password",
            "allowed_tables": ["work_order"],
            "max_rows": 100,
            "timeout_seconds": 5,
            "tls": True,
        },
    }


def _active_database_deployment(database: Database) -> str:
    resources = McpResourceService(database)
    resources.apply(
        _database_manifest(),
        actor_id="admin-1",
        expected_revision=0,
        idempotency_key="create-resource",
    )
    resources.verify("mes_db", actor_id="admin-1", expected_revision=1)
    published = resources.publish(
        "mes_db",
        actor_id="admin-1",
        expected_revision=1,
        idempotency_key="publish-resource",
    )
    resources.activate_generation(published["generation_id"], success=True)
    return str(published["deployment_id"])


def _audited_service(database: Database) -> McpToolPublicationService:
    return McpToolPublicationService(
        database,
        audit_service=AuditService(AuditRepository(database)),
    )


def test_catalog_is_code_owned_and_ones_publication_lifecycle_is_idempotent(
    database: Database,
) -> None:
    service = McpToolPublicationService(database)
    catalog = service.catalog()
    assert {entry["catalog_key"] for entry in catalog} >= {
        "ones-mcp/ones_work_item_search",
        "data-mcp/data_sample_rows",
    }
    assert all(len(str(entry["tool_schema_hash"])) == 64 for entry in catalog)

    created = service.create(
        code="ones_search",
        name="ONES work item search",
        catalog_key="ones-mcp/ones_work_item_search",
        actor_id="admin-1",
        idempotency_key="create-ones-tool",
    )
    assert (
        service.create(
            code="ones_search",
            name="ONES work item search",
            catalog_key="ones-mcp/ones_work_item_search",
            actor_id="admin-1",
            idempotency_key="create-ones-tool",
        )
        == created
    )
    verified = service.verify("ones_search", expected_revision=1, actor_id="admin-1")
    assert verified["required_scope"] == "ones.work_items.search"
    published = service.publish(
        "ones_search",
        expected_revision=1,
        actor_id="admin-1",
        idempotency_key="publish-ones-tool",
    )
    assert published["status"] == "PUBLISHED"
    detail = service.get("ones_search")
    assert detail["current_publication_id"] == published["publication_id"]
    assert detail["publications"][0]["tool_name"] == "ones_work_item_search"

    with pytest.raises(ValueError):
        service.create(
            code="free_executor",
            name="Free executor",
            catalog_key="external/arbitrary_http",
            actor_id="admin-1",
            idempotency_key="free-executor",
        )


def test_data_tool_freezes_exact_active_resource_and_revalidates_before_publish(
    database: Database,
) -> None:
    deployment_id = _active_database_deployment(database)
    service = McpToolPublicationService(database)
    service.create(
        code="mes_sample",
        name="MES bounded sample",
        catalog_key="data-mcp/data_sample_rows",
        resource_deployment_id=deployment_id,
        actor_id="admin-1",
        idempotency_key="create-data-tool",
    )
    verified = service.verify("mes_sample", expected_revision=1, actor_id="admin-1")
    assert verified["resource_kind"] == "DATABASE"
    assert verified["resource_deployment_id"] == deployment_id
    published = service.publish(
        "mes_sample",
        expected_revision=1,
        actor_id="admin-1",
        idempotency_key="publish-data-tool",
    )
    row = database.execute_one(
        "select * from mcp_tool_publication where id = ?",
        (published["publication_id"],),
    )
    assert row is not None
    assert row["resource_code"] == "mes_db"
    assert row["resource_deployment_id"] == deployment_id
    assert row["resource_revision_id"]

    service.update_draft(
        "mes_sample",
        expected_revision=2,
        catalog_key="data-mcp/data_sample_rows",
        resource_deployment_id=deployment_id,
        actor_id="admin-1",
    )
    service.verify("mes_sample", expected_revision=3, actor_id="admin-1")
    database.execute(
        "update mcp_resource_deployment set status = 'DISABLED' where id = ?",
        (deployment_id,),
    )
    with pytest.raises(NonRetryableExecutionError) as unavailable:
        service.publish(
            "mes_sample",
            expected_revision=3,
            actor_id="admin-1",
            idempotency_key="publish-disabled-data-tool",
        )
    assert unavailable.value.error_code == "mcp_tool_resource_unavailable"


def test_disable_revokes_existing_publication_and_revision_conflicts_fail_closed(
    database: Database,
) -> None:
    service = McpToolPublicationService(database)
    service.create(
        code="ones_search",
        name="ONES search",
        catalog_key="ones-mcp/ones_work_item_search",
        actor_id="admin-1",
        idempotency_key="create",
    )
    service.verify("ones_search", expected_revision=1, actor_id="admin-1")
    published = service.publish(
        "ones_search",
        expected_revision=1,
        actor_id="admin-1",
        idempotency_key="publish",
    )

    with pytest.raises(NonRetryableExecutionError) as conflict:
        service.disable("ones_search", expected_revision=1, actor_id="admin-1")
    assert conflict.value.error_code == "revision_conflict"

    disabled = service.disable("ones_search", expected_revision=2, actor_id="admin-1")
    assert disabled["status"] == "DISABLED"
    publication = database.execute_one(
        "select status from mcp_tool_publication where id = ?",
        (published["publication_id"],),
    )
    assert publication == {"status": "DISABLED"}


def test_publish_is_idempotent_and_rejects_duplicate_configuration_and_stale_writer(
    database: Database,
) -> None:
    service = _audited_service(database)
    service.create(
        code="ones_search",
        name="ONES search",
        catalog_key="ones-mcp/ones_work_item_search",
        actor_id="admin-1",
        idempotency_key="create",
    )
    service.verify(
        "ones_search",
        expected_revision=1,
        actor_id="admin-1",
        idempotency_key="verify-1",
    )
    published = service.publish(
        "ones_search",
        expected_revision=1,
        actor_id="admin-1",
        idempotency_key="publish-1",
    )
    assert (
        service.publish(
            "ones_search",
            expected_revision=1,
            actor_id="admin-1",
            idempotency_key="publish-1",
        )
        == published
    )

    with pytest.raises(NonRetryableExecutionError) as stale:
        service.update_draft(
            "ones_search",
            expected_revision=1,
            catalog_key="ones-mcp/ones_work_item_search",
            actor_id="admin-1",
        )
    assert stale.value.error_code == "revision_conflict"

    service.update_draft(
        "ones_search",
        expected_revision=2,
        catalog_key="ones-mcp/ones_work_item_search",
        actor_id="admin-1",
        idempotency_key="draft-2",
    )
    service.verify(
        "ones_search",
        expected_revision=3,
        actor_id="admin-1",
        idempotency_key="verify-2",
    )
    with pytest.raises(NonRetryableExecutionError) as duplicate:
        service.publish(
            "ones_search",
            expected_revision=3,
            actor_id="admin-1",
            idempotency_key="publish-duplicate",
        )
    assert duplicate.value.error_code == "mcp_tool_duplicate_publication"
    assert duplicate.value.diagnostics == {
        "publication_id": published["publication_id"],
        "publication_revision": 1,
    }

    audits = database.execute(
        "select event_type, payload_summary from audit_event where event_type like 'mcp.tool.%'"
    )
    assert {row["event_type"] for row in audits} >= {
        "mcp.tool.created",
        "mcp.tool.verified",
        "mcp.tool.published",
    }
    serialized = json.dumps(audits, ensure_ascii=False).lower()
    for forbidden in ("password", "authorization", "secret://", "api_key", "token"):
        assert forbidden not in serialized


def test_second_publication_and_rollback_preserve_exactly_one_active_version(
    database: Database,
) -> None:
    deployment_id = _active_database_deployment(database)
    service = _audited_service(database)
    service.create(
        code="governed_reader",
        name="Governed reader",
        catalog_key="ones-mcp/ones_work_item_search",
        actor_id="admin-1",
        idempotency_key="create-reader",
    )
    service.verify("governed_reader", expected_revision=1, actor_id="admin-1")
    first = service.publish(
        "governed_reader",
        expected_revision=1,
        actor_id="admin-1",
        idempotency_key="publish-reader-1",
    )
    service.update_draft(
        "governed_reader",
        expected_revision=2,
        catalog_key="data-mcp/data_sample_rows",
        resource_deployment_id=deployment_id,
        actor_id="admin-1",
    )
    service.verify("governed_reader", expected_revision=3, actor_id="admin-1")
    second = service.publish(
        "governed_reader",
        expected_revision=3,
        actor_id="admin-1",
        idempotency_key="publish-reader-2",
    )
    assert database.execute(
        "select id, status from mcp_tool_publication where tool_id = (select id from mcp_tool where code = ?) order by revision",
        ("governed_reader",),
    ) == [
        {"id": first["publication_id"], "status": "DISABLED"},
        {"id": second["publication_id"], "status": "PUBLISHED"},
    ]

    rolled_back = service.rollback(
        "governed_reader",
        publication_id=first["publication_id"],
        expected_revision=4,
        actor_id="admin-1",
        idempotency_key="rollback-reader-1",
    )
    assert (
        service.rollback(
            "governed_reader",
            publication_id=first["publication_id"],
            expected_revision=4,
            actor_id="admin-1",
            idempotency_key="rollback-reader-1",
        )
        == rolled_back
    )
    assert database.execute(
        "select id, status from mcp_tool_publication where tool_id = (select id from mcp_tool where code = ?) order by revision",
        ("governed_reader",),
    ) == [
        {"id": first["publication_id"], "status": "PUBLISHED"},
        {"id": second["publication_id"], "status": "DISABLED"},
    ]
    current = database.execute_one(
        "select current_publication_id, revision from mcp_tool where code = ?",
        ("governed_reader",),
    )
    assert current == {"current_publication_id": first["publication_id"], "revision": 5}
    active = database.execute_one(
        "select count(*) value from mcp_tool_publication where tool_id = (select id from mcp_tool where code = ?) and status = 'PUBLISHED'",
        ("governed_reader",),
    )
    assert active == {"value": 1}
