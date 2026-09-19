"""Opt-in: use only a disposable PostgreSQL instance, never the deployment DSN."""

import os

import pytest
from psycopg.errors import InsufficientPrivilege
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from app.modules.job.infrastructure.repositories import AuditRepository
from app.modules.mcp_audit import McpAuditCoordinator
from app.modules.mcp_audit.application import McpAuditError
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import Migrator, SchemaHeadValidator
from services.knowledge_mcp_server.database_policy import (
    READ_COLUMNS,
    ROLE,
    assert_reader_role,
    grant_reader,
)


@pytest.fixture(scope="module")
def isolated_policy_database():
    dsn = os.environ.get("KNOWLEDGE_POLICY_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("explicit disposable PostgreSQL DSN not supplied")
    password = "synthetic-reader-password-for-tests-only"
    admin = Database(dsn)
    reader = None
    try:
        Migrator(admin, default_migrations_dir(), migrator_build="knowledge-policy-test").run()
        grant_reader(admin, password)
        config = conninfo_to_dict(dsn)
        config.update(user=ROLE, password=password)
        reader = Database(make_conninfo(**config))
        yield admin, reader
    finally:
        if reader:
            reader.close()
        admin.close()


def test_postgres_reader_readiness_and_explicit_columns(isolated_policy_database):
    admin, reader = isolated_policy_database
    assert_reader_role(reader)
    with pytest.raises(ValueError, match="固定权限"):
        assert_reader_role(admin)
    SchemaHeadValidator(reader, default_migrations_dir()).require_current()
    audit = McpAuditCoordinator(reader, max_payload_bytes=16384)
    audit.assert_ready(retention_cleanup=False)
    with pytest.raises(McpAuditError):
        audit.assert_ready()
    for table, columns in READ_COLUMNS.items():
        assert reader.execute(f"select {','.join(columns)} from {table} where false") == []
    audit_id = AuditRepository(reader).record(
        event_type="KNOWLEDGE_TEST", status="SUCCEEDED", summary="合成权限边界验证"
    )
    assert reader.execute_one("select id from audit_event where id=?", (audit_id,))


@pytest.mark.parametrize(
    "statement",
    [
        "select * from agent_job where false",
        "select * from agent_session where false",
        "select * from external_identity_credential where false",
        "select * from knowledge.document_revision where false",
        "select * from audit_event where false",
        "select * from mcp_operation_audit where false",
        "update knowledge.retrieval_resource set status='disabled' where false",
        "update agent_job set status='RUNNING' where false",
        "delete from mcp_operation_audit where false",
        "create table public.forbidden_knowledge_table(id text)",
        "create table knowledge.forbidden_knowledge_table(id text)",
    ],
)
def test_postgres_forbidden_access_fails(isolated_policy_database, statement):
    _, reader = isolated_policy_database
    with pytest.raises(InsufficientPrivilege):
        reader.execute(statement)


@pytest.mark.parametrize(
    "grant,revoke",
    [
        ("SELECT ON external_identity_credential", "SELECT ON external_identity_credential"),
        ("UPDATE (status) ON agent_job", "UPDATE (status) ON agent_job"),
        ("REFERENCES (id) ON app_user", "REFERENCES (id) ON app_user"),
        ("DELETE ON audit_event", "DELETE ON audit_event"),
        ("CREATE ON SCHEMA knowledge", "CREATE ON SCHEMA knowledge"),
    ],
)
def test_postgres_excess_grants_fail_closed(isolated_policy_database, grant, revoke):
    admin, reader = isolated_policy_database
    admin.execute(f"GRANT {grant} TO {ROLE}")
    try:
        with pytest.raises(ValueError):
            assert_reader_role(reader)
    finally:
        admin.execute(f"REVOKE {revoke} FROM {ROLE}")
    assert_reader_role(reader)


def test_postgres_reprovision_removes_previous_column_grants(isolated_policy_database):
    admin, reader = isolated_policy_database
    admin.execute(f"GRANT UPDATE(status) ON agent_job TO {ROLE}")
    grant_reader(admin, "synthetic-reader-password-for-tests-only")
    assert_reader_role(reader)
