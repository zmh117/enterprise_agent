"""知识 MCP 固定数据库权限合同；按实际读取列授予，不读取凭据或原始 Job 消息。"""

from psycopg import sql
from app.shared.database import Database

ROLE = "knowledge_mcp_reader"
# SELECT * 的既有元数据查询也展开明确列；未来加列必须重新审查，不能自动扩权。
READ_COLUMNS = {
    table: tuple(columns.split())
    for table, columns in {
        "public.agent_job": "id internal_user_id status session_id agent_publication_id agent_config_hash business_application_id business_application_publication_id business_application_config_hash business_application_route_decision_json execution_policy_json locked_at project_code retry_count",
        "public.agent_session": "id application_publication_id",
        "public.app_user": "id username display_name email status account_type revision created_at updated_at",
        "public.agent_job_mcp_tool_snapshot": "id job_id agent_publication_id application_publication_id authorization_hash created_at schema_version snapshot_hash snapshot_json",
        "public.agent_publication": "id config_hash schema_version snapshot_json",
        "public.business_application_publication": "id application_id config_hash schema_version snapshot_json",
        "public.agent_publication_mcp_tool": "agent_publication_id schema_hash selection_order server_code tool_identifier",
        "public.business_application_publication_mcp_tool": "agent_publication_id application_publication_id schema_hash server_code tool_identifier",
        "public.business_application": "id code name description project_code status owner_user_id created_by revision created_at updated_at",
        "public.business_application_deployment": "active application_id environment publication_id updated_at",
        "public.rbac_role": "id code name description origin protected purpose_tags_json status revision admin_revision business_revision membership_revision metadata_revision created_at updated_at",
        "public.rbac_user_role": "id user_id role_id status expires_at revision",
        "public.rbac_role_application_access": "id application_id role_id status revision created_at updated_at",
        "public.rbac_role_application_knowledge_base": "application_access_id knowledge_base_id",
        "public.rbac_role_application_mcp_tool": "application_access_id tool_identifier",
        "public.rbac_role_application_scope": "id application_access_id scope_key environment_id base_id workshop_id",
        "public.platform_environment": "id code",
        "public.platform_base": "id code",
        "public.platform_workshop": "id code",
        "public.user_external_identity": "id external_subject_id metadata_json provider status tenant_code user_id",
        "public.audit_event": "id",
        "public.agent_tool_call": "id mcp_call_id status",
        "public.mcp_operation_audit": "id agent_tool_call_id status",
        "public.schema_migration": "version name checksum applied_at duration_ms migrator_build",
        "public.schema_baseline_adoption": "target_baseline source_generation source_head legacy_catalog_digest schema_fingerprint comment_manifest_digest retained_data_counts_json retained_data_digest baseline_name baseline_checksum migrator_build adopted_at",
        "knowledge.source": "id code created_at display_name identity_metadata origin_state source_system",
        "knowledge.retrieval_resource": "id knowledge_base_id code name status revision state_revision draft_revision_id published_revision_id created_by created_at updated_at",
        "knowledge.retrieval_revision": "id resource_id revision binding_id index_id profile_hash corpus_hash config_hash created_by created_at published_by published_at storage_config_json",
        "knowledge.knowledge_base": "id code display_name description state created_at",
        "knowledge.document": "id current_revision_id external_id lifecycle_state source_id source_object_type",
        "knowledge.document_revision": "id document_id content_hash source_project_id",
        "knowledge.knowledge_base_document": "document_id knowledge_base_id state",
        "knowledge.vector_index": "id code knowledge_base_id state profile profile_hash chunk_profile_hash collection_name corpus_hash expected_document_count expected_chunk_count error_code created_at updated_at",
        "knowledge.document_chunk": "id chunk_set_id ordinal chunk_kind source_field source_start source_end evidence_text evidence_hash embedding_text embedding_hash char_count embedding_char_count quality_flags",
        "knowledge.document_chunk_set": "id document_id document_revision_id profile_hash source_content_hash",
        "knowledge.vector_index_item": "chunk_id embedding_text_hash index_id point_id state",
    }.items()
}
WRITE_TABLES = {
    "public.audit_event": ("INSERT",),
    "public.agent_tool_call": ("INSERT", "UPDATE"),
    "public.mcp_operation_audit": ("INSERT", "UPDATE"),
}


def assert_reader_role(database: Database, *, require_current_user: bool = True) -> None:
    if database.engine != "postgres":
        raise ValueError("知识 MCP 部署要求 PostgreSQL 独立读取账号")
    role = database.execute_one(
        "select rolsuper,rolinherit,rolcreaterole,rolcreatedb,rolreplication,rolbypassrls,"
        "rolname=current_user as current_role from pg_roles where rolname=?",
        (ROLE,),
    )
    if (
        not role
        or any(
            role[k]
            for k in (
                "rolsuper",
                "rolinherit",
                "rolcreaterole",
                "rolcreatedb",
                "rolreplication",
                "rolbypassrls",
            )
        )
        or (require_current_user and not role["current_role"])
    ):
        raise ValueError("知识 MCP 数据库角色不符合固定权限合同")
    if database.execute_one(
        "select 1 from pg_auth_members where member=(select oid from pg_roles where rolname=?)",
        (ROLE,),
    ):
        raise ValueError("知识 MCP 数据库角色不得继承或切换其他角色")
    for schema in ("public", "knowledge"):
        allowed = database.execute_one(
            "select has_schema_privilege(?, ?, 'CREATE') as allowed", (ROLE, schema)
        )
        if allowed and allowed["allowed"]:
            raise ValueError("知识 MCP 不得创建数据库对象")
    columns = database.execute(
        "select n.nspname || '.' || c.relname as relation,a.attname as name,"
        "has_column_privilege(?,c.oid,a.attnum,'SELECT') as allowed,"
        "has_column_privilege(?,c.oid,a.attnum,'INSERT') as can_insert,"
        "has_column_privilege(?,c.oid,a.attnum,'UPDATE') as can_update,"
        "has_column_privilege(?,c.oid,a.attnum,'REFERENCES') as can_reference "
        "from pg_class c join pg_namespace n on n.oid=c.relnamespace "
        "join pg_attribute a on a.attrelid=c.oid "
        "where n.nspname in ('public','knowledge') and c.relkind in ('r','p','v','m','f') "
        "and a.attnum>0 and not a.attisdropped",
        (ROLE, ROLE, ROLE, ROLE),
    )
    actual = {(row["relation"], row["name"]) for row in columns if row["allowed"]}
    expected = {(table, column) for table, values in READ_COLUMNS.items() for column in values}
    if actual != expected:
        raise ValueError("知识 MCP 读取列授权缺失或超出合同")
    for column in columns:
        for flag, privilege in (
            ("can_insert", "INSERT"),
            ("can_update", "UPDATE"),
            ("can_reference", "REFERENCES"),
        ):
            if bool(column[flag]) != (privilege in WRITE_TABLES.get(column["relation"], ())):
                raise ValueError("知识 MCP 列写入授权缺失或超出审计边界")
    for table in {row["relation"] for row in columns}:
        for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
            row = database.execute_one(
                "select has_table_privilege(?, ?, ?) as allowed", (ROLE, table, privilege)
            )
            if bool(row and row["allowed"]) != (privilege in WRITE_TABLES.get(table, ())):
                raise ValueError("知识 MCP 写入授权缺失或超出审计边界")


def grant_reader(database: Database, password: str) -> None:
    """仅运维显式调用；不创建 schema、不迁移数据、不在服务启动时运行。"""
    if database.engine != "postgres" or len(password) < 24:
        raise ValueError("需要 PostgreSQL 和至少 24 字符的独立数据库口令")
    existing = database.execute_one("select 1 from pg_roles where rolname=?", (ROLE,))
    with database.unit_of_work(), database.session() as connection:
        statement = sql.SQL(
            "{} ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
        ).format(
            sql.SQL("ALTER" if existing else "CREATE"),
            sql.Identifier(ROLE),
            sql.Literal(password),
        )
        connection.execute(statement).close()
        for schema in ("public", "knowledge"):
            for kind in ("TABLES", "SEQUENCES"):
                connection.execute(
                    sql.SQL("REVOKE ALL ON ALL {} IN SCHEMA {} FROM {}").format(
                        sql.SQL(kind), sql.Identifier(schema), sql.Identifier(ROLE)
                    )
                ).close()
            connection.execute(
                sql.SQL("REVOKE CREATE ON SCHEMA {} FROM {}").format(
                    sql.Identifier(schema), sql.Identifier(ROLE)
                )
            ).close()
            connection.execute(
                sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                    sql.Identifier(schema), sql.Identifier(ROLE)
                )
            ).close()
        # 表级 REVOKE 不撤销历史列级授权；逐表逐列撤销该角色本身的授权，再精确授予。
        columns = database.execute(
            "select table_schema,table_name,column_name from information_schema.columns where table_schema in ('public','knowledge')"
        )
        for row in columns:
            connection.execute(
                sql.SQL("REVOKE ALL ({}) ON {} FROM {}").format(
                    sql.Identifier(row["column_name"]),
                    sql.Identifier(row["table_schema"], row["table_name"]),
                    sql.Identifier(ROLE),
                )
            ).close()
        for table, names in READ_COLUMNS.items():
            connection.execute(
                sql.SQL("GRANT SELECT ({}) ON {} TO {}").format(
                    sql.SQL(",").join(map(sql.Identifier, names)),
                    sql.Identifier(*table.split(".")),
                    sql.Identifier(ROLE),
                )
            ).close()
        for table, privileges in WRITE_TABLES.items():
            connection.execute(
                sql.SQL("GRANT {} ON {} TO {}").format(
                    sql.SQL(",").join(map(sql.SQL, privileges)),
                    sql.Identifier(*table.split(".")),
                    sql.Identifier(ROLE),
                )
            ).close()
        assert_reader_role(database, require_current_user=False)
