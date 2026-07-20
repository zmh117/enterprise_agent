from __future__ import annotations

import sqlite3

import pytest

from app.modules.identity.application.passwords import PasswordService
from app.shared.database import Database, default_migrations_dir
from app.shared.exceptions import NonRetryableExecutionError, PermissionDenied
from backend.tests.helpers import container


def test_webhook_migration_backfills_humans_and_is_repeatable() -> None:
    database = Database("sqlite:///:memory:")
    migrations = default_migrations_dir()
    for path in sorted(migrations.glob("*.sql")):
        if path.name == "008_webhook_agent_triggers.sql":
            break
        database.execute_script(path.read_text())
    database.execute(
        """
        insert into app_user
          (id, username, display_name, email, status, revision, created_at, updated_at)
        values ('legacy-user', 'legacy-user', 'Legacy User', '', 'enabled', 1,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """
    )

    migration = (migrations / "008_webhook_agent_triggers.sql").read_text()
    database.execute_script(migration)
    database.execute_script(migration)

    legacy = database.execute_one(
        "select account_type from app_user where id = 'legacy-user'"
    )
    assert legacy == {"account_type": "human"}
    assert {
        "webhook_trigger_definition",
        "webhook_trigger_revision",
        "webhook_trigger_publication",
        "webhook_event",
        "webhook_replay_nonce",
        "webhook_outbox",
    }.issubset(
        {
            str(row["name"])
            for row in database.execute(
                "select name from sqlite_master where type = 'table'"
            )
        }
    )
    columns = {
        str(row["name"])
        for row in database.execute("pragma table_info(agent_job)")
    }
    assert {
        "webhook_event_id",
        "webhook_trigger_id",
        "webhook_trigger_publication_id",
    }.issubset(columns)

    with pytest.raises(sqlite3.IntegrityError):
        database.execute(
            """
            insert into app_user
              (id, username, display_name, status, account_type, revision,
               created_at, updated_at)
            values ('bad-user', 'bad-user', 'Bad', 'enabled', 'robot', 1,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
        )


def test_service_account_has_no_password_session_or_external_identity() -> None:
    c = container()
    service = c.identity_repository.create_user(
        username="svc-webhook-test",
        display_name="Webhook Test Service",
        account_type="service",
    )
    assert service["account_type"] == "service"

    with pytest.raises(NonRetryableExecutionError) as password_error:
        c.identity_repository.set_password_hash(
            str(service["id"]), PasswordService().hash("not-a-login-password")
        )
    assert password_error.value.error_code == "service_account_password_forbidden"

    with pytest.raises(NonRetryableExecutionError) as session_error:
        c.identity_repository.create_session(
            user_id=str(service["id"]),
            token_hash="token-hash",
            csrf_hash="csrf-hash",
            idle_expires_at="2099-01-01T00:00:00+00:00",
            absolute_expires_at="2099-01-02T00:00:00+00:00",
        )
    assert session_error.value.error_code == "service_account_session_forbidden"

    with pytest.raises(NonRetryableExecutionError) as identity_error:
        c.identity_repository.bind_external_identity(
            user_id=str(service["id"]),
            provider="dingtalk",
            tenant_code="default",
            external_subject_id="service-account-must-not-bind",
            connector_id="connector-dingtalk-stream-default",
        )
    assert identity_error.value.error_code == "service_account_identity_forbidden"

    with pytest.raises(PermissionDenied):
        c.auth_service.login(
            username=str(service["username"]),
            password="not-a-login-password",
        )
