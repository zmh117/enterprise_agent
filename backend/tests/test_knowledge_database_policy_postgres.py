"""Opt-in: use only a disposable PostgreSQL instance, never the deployment DSN."""

import os

import pytest
from psycopg.errors import InsufficientPrivilege, ReadOnlySqlTransaction
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
        "select * from knowledge.source_binding where false",
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


def test_external_content_connection_does_not_need_platform_account_or_schema_ledger(
    isolated_policy_database,
):
    from app.modules.knowledge.infrastructure.content_access import (
        ManagedContentAccess,
        PlatformStorageCredentials,
    )
    from app.modules.knowledge.domain.governance import KnowledgeGovernanceError

    admin, reader = isolated_policy_database
    config = conninfo_to_dict(reader.dsn)
    storage = {
        "postgres": {
            "mode": "external",
            "host": config["host"],
            "port": int(config["port"]),
            "database": config["dbname"],
            "username": ROLE,
            "password_ref": "secret://platform/synthetic_reader",
            "sslmode": "disable",
        },
        "qdrant": {"url": "http://synthetic-qdrant:6333", "api_key_ref": ""},
    }
    factory = ManagedContentAccess(
        None, PlatformStorageCredentials(lambda _: "synthetic-reader-password-for-tests-only")
    )
    with factory.open(storage, knowledge_base_id="synthetic", revision_id="synthetic") as content:
        assert "indexes" in content.records.catalog()
    admin.execute(f"GRANT UPDATE (status) ON knowledge.retrieval_resource TO {ROLE}")
    try:
        # 内容账号的写权限不阻止读取；用途只读不等于修改数据库角色权限。
        with factory.open(
            storage, knowledge_base_id="synthetic", revision_id="synthetic"
        ) as content:
            assert "indexes" in content.records.catalog()
            with pytest.raises(ReadOnlySqlTransaction):
                content.records.database.execute(
                    "update knowledge.retrieval_resource set status='disabled' where false"
                )
        # 同一个账号若用于 MCP 平台治理连接，仍必须遵守原最小权限合同。
        with pytest.raises(ValueError):
            assert_reader_role(reader)
    finally:
        admin.execute(f"REVOKE UPDATE (status) ON knowledge.retrieval_resource FROM {ROLE}")
    assert_reader_role(reader)
    admin.execute(f"REVOKE SELECT (display_name) ON knowledge.knowledge_base FROM {ROLE}")
    try:
        with pytest.raises(KnowledgeGovernanceError, match="knowledge_storage_unavailable"):
            with factory.open(
                storage, knowledge_base_id="synthetic", revision_id="synthetic"
            ) as content:
                content.records.catalog()
    finally:
        admin.execute(f"GRANT SELECT (display_name) ON knowledge.knowledge_base TO {ROLE}")
    assert_reader_role(reader)


def test_content_admin_can_read_but_its_managed_sessions_cannot_write(isolated_policy_database):
    from app.modules.knowledge.infrastructure.content_access import (
        ManagedContentAccess,
        PlatformStorageCredentials,
    )

    admin, _ = isolated_policy_database
    config = conninfo_to_dict(admin.dsn)
    assert admin.execute_one("select rolsuper from pg_roles where rolname=current_user")["rolsuper"]
    storage = {
        "postgres": {
            "mode": "external",
            "host": config["host"],
            "port": int(config["port"]),
            "database": config["dbname"],
            "username": config["user"],
            "password_ref": "secret://platform/synthetic_admin",
            "sslmode": "disable",
        },
        "qdrant": {"url": "http://synthetic-qdrant:6333", "api_key_ref": ""},
    }
    access = ManagedContentAccess(
        None, PlatformStorageCredentials(lambda _: config.get("password") or "synthetic-unused")
    )
    for _ in range(2):
        with access.open(
            storage, knowledge_base_id="synthetic", revision_id="synthetic"
        ) as content:
            database = content.records.database
            assert "indexes" in content.records.catalog()
            assert database.execute_one("show default_transaction_read_only") == {
                "default_transaction_read_only": "on"
            }
            assert database.execute_one("show statement_timeout") == {"statement_timeout": "5s"}
            assert database.execute_one("show lock_timeout") == {"lock_timeout": "3s"}
            for statement in (
                "insert into knowledge.knowledge_base(id,code,display_name,state,created_at) "
                "values('synthetic-blocked','synthetic-blocked','synthetic','storage_only','2026-09-20')",
                "update knowledge.knowledge_base set display_name='synthetic-blocked' where false",
                "delete from knowledge.knowledge_base where false",
                "create table knowledge.synthetic_blocked(id text)",
            ):
                with pytest.raises(ReadOnlySqlTransaction):
                    database.execute(statement)
            with pytest.raises(ReadOnlySqlTransaction):
                with database.unit_of_work():
                    database.execute("delete from knowledge.knowledge_base where false")
    # 原运维连接权限和默认事务属性不被内容读取连接修改。
    assert admin.execute_one("show default_transaction_read_only") == {
        "default_transaction_read_only": "off"
    }
    admin.execute("update knowledge.knowledge_base set display_name='synthetic' where false")
    with pytest.raises(ValueError):
        assert_reader_role(admin)


def test_code_answer_queries_use_only_granted_columns(isolated_policy_database, tmp_path):
    from dataclasses import replace
    from app.bootstrap import build_test_container
    from app.modules.knowledge.infrastructure.code_answer_store import CodeAnswerStore
    from app.modules.knowledge.infrastructure.code_answer_reader import CodeAnswerReader
    from app.modules.knowledge.infrastructure.code_index_store import CodeIndexStore
    from app.modules.knowledge.infrastructure.code_index_executor import CodeIndexExecutor
    from backend.tests.support.runtime import test_settings, direct_job_permission_service_factory
    from backend.tests.support.code_answers import code_configuration, CODE_INDEX_ID
    from backend.tests.test_code_answer_store import prepared, save
    from backend.tests.test_knowledge_vectors import SyntheticEmbedding
    from backend.tests.test_knowledge_incremental_sync import IncrementalMemory

    admin, reader = isolated_policy_database
    runtime = build_test_container(
        replace(test_settings(), database_dsn=admin.dsn),
        migrate=False,
        seed=True,
        configure_seed_secrets=True,
        permission_service_factory=direct_job_permission_service_factory,
    )
    try:
        runtime.create_agent_job_service.published_agent_runtime_enabled = True
        runtime.create_agent_job_service.runtime_readiness_guard = None
        _, source, checkout, _ = code_configuration(runtime, tmp_path)
        answers = CodeAnswerStore(runtime.database, authorize=lambda context: None)
        workspace = (runtime, answers, source, checkout)
        ctx, analysis, result = prepared(workspace)
        saved = save(answers, ctx, analysis, result)
        index_store = CodeIndexStore(runtime.database)
        vectors = IncrementalMemory()
        executor = CodeIndexExecutor(
            index_store,
            SyntheticEmbedding(),
            vectors,
            owner="pg-test",
            execution_root=tmp_path.resolve(),
        )
        task = runtime.database.execute_one("SELECT id FROM knowledge.code_index_task")
        assert executor.execute(task["id"])
        assert index_store.row("code_index_task", task["id"])["state"] == "succeeded"
        store = CodeAnswerReader(reader)
        args = dict(
            base_id="code-kb",
            environment_id="code-env-a",
            source_id=source,
            index_id=CODE_INDEX_ID,
            allowed_paths=["set_server"],
        )
        assert store.select_version(**args, revision=100, mode="exact")["document_ids"] == [
            saved["document_id"]
        ]
        answer = store.get(
            **args, document_id=saved["document_id"], revision_id=saved["revision_id"]
        )
        assert answer["svn_revision"] == 100 and answer["support_status"] == "supported"
        index = runtime.database.execute_one(
            "SELECT * FROM knowledge.vector_index WHERE id=?", (CODE_INDEX_ID,)
        )
        for point in vectors.points.values():
            assert store.chunk(
                index=index, point=point, allowed_paths=["set_server"], environment_id="code-env-a"
            )
        for statement in (
            "SELECT * FROM knowledge.code_evidence",
            "SELECT * FROM knowledge.code_qa_record",
            "SELECT * FROM knowledge.code_analysis",
            "SELECT * FROM knowledge.code_checkout",
            "UPDATE knowledge.code_answer SET svn_revision=101 WHERE false",
        ):
            with pytest.raises(InsufficientPrivilege):
                reader.execute(statement)
    finally:
        runtime.database.close()
