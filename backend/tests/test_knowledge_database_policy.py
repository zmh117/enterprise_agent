from contextlib import contextmanager
import sqlite3

import pytest

from backend.tests.test_knowledge_mcp_server import (
    knowledge_contract as knowledge_contract_fixture,
    readable_fixture as readable_fixture_impl,
    bridge_fixture as bridge_fixture_impl,
    search_fixture as search_fixture_impl,
    mcp_fixture as mcp_fixture_impl,
    headers,
)
from backend.tests.test_knowledge_search import SyntheticReadability
from services.knowledge_mcp_server.execution import CallControl
from services.knowledge_mcp_server.database_policy import (
    READ_COLUMNS,
    WRITE_TABLES,
    grant_reader,
    assert_reader_role,
)
from app.shared.database import Database

knowledge_contract = knowledge_contract_fixture
readable_fixture = readable_fixture_impl
bridge_fixture = bridge_fixture_impl
search_fixture = search_fixture_impl
mcp_fixture = mcp_fixture_impl


def test_reader_sql_surface(mcp_fixture, monkeypatch):
    f = mcp_fixture
    f["tools"].search.readability = SyntheticReadability(f)
    database = f["runtime"].database
    original = database.session
    reads, writes = {}, {}

    def authorize(action, table, column, db, trigger):
        if action == sqlite3.SQLITE_READ:
            reads.setdefault(table, set()).add(column)
        if action in {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}:
            writes.setdefault(table, set()).add(action)
        return sqlite3.SQLITE_OK

    @contextmanager
    def session():
        with original() as connection:
            connection.set_authorizer(authorize)
            try:
                yield connection
            finally:
                connection.set_authorizer(None)

    monkeypatch.setattr(database, "session", session)
    for name, arguments in (
        ("knowledge_list_bases", {}),
        (
            "knowledge_search",
            {"knowledge_base_id": f["body"]["knowledge_base_id"], "query": "合成查询"},
        ),
    ):
        f["tools"].invoke(
            name=name,
            arguments=arguments,
            token=f["knowledge_token"],
            headers=headers(f),
            control=CallControl(),
        )
    # SQLite authorizes FK metadata reads itself; PostgreSQL checks FK without
    # exposing the referenced credential table to the caller.
    assert reads.pop("external_identity_credential", set()) <= {"id"}
    for table, columns in reads.items():
        qualified = table if table.startswith("knowledge.") else "public." + table
        assert columns - {""} <= set(READ_COLUMNS.get(qualified, ())), qualified
    operations = {
        sqlite3.SQLITE_INSERT: "INSERT",
        sqlite3.SQLITE_UPDATE: "UPDATE",
        sqlite3.SQLITE_DELETE: "DELETE",
    }
    for table, actions in writes.items():
        assert {operations[action] for action in actions} <= set(
            WRITE_TABLES.get("public." + table, ())
        )
    assert set(writes) == {"audit_event", "agent_tool_call", "mcp_operation_audit"}


def test_reader_never_grants_raw_messages_credentials_or_business_writes():
    assert not {"prompt", "input_json", "result_json"}.intersection(
        READ_COLUMNS["public.agent_job"]
    )
    assert "public.external_identity_credential" not in READ_COLUMNS
    assert "knowledge.document_payload" not in READ_COLUMNS
    assert set(WRITE_TABLES) == {
        "public.audit_event",
        "public.agent_tool_call",
        "public.mcp_operation_audit",
    }
    assert all("DELETE" not in privileges for privileges in WRITE_TABLES.values())


def test_deployment_role_policy_refuses_sqlite_without_modifying_it():
    database = Database("sqlite:///:memory:")
    try:
        with pytest.raises(ValueError, match="PostgreSQL"):
            grant_reader(database, "synthetic-long-password-for-tests")
        with pytest.raises(ValueError, match="PostgreSQL"):
            assert_reader_role(database)
        assert database.execute("select name from sqlite_master where type='table'") == []
    finally:
        database.close()
