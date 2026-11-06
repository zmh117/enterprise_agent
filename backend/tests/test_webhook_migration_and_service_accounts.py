from __future__ import annotations

import sqlite3

import pytest

from app.modules.identity.application.passwords import PasswordService
from app.shared.database import Database, default_migrations_dir
from app.shared.exceptions import NonRetryableExecutionError, PermissionDenied
from app.shared.migrations import Migrator
from backend.tests.helpers import container


def test_baseline_webhook_schema_defaults_humans_and_is_repeatable() -> None:
    database = Database("sqlite:///:memory:")
    Migrator(
        database,
        default_migrations_dir(),
        migrator_build="webhook-baseline-test",
    ).run()
    database.execute(
        """
        insert into app_user
          (id, username, display_name, email, status, revision, created_at, updated_at)
        values ('legacy-user', 'legacy-user', 'Legacy User', '', 'enabled', 1,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """
    )

    repeated = Migrator(
        database,
        default_migrations_dir(),
        migrator_build="webhook-baseline-repeat-test",
    ).run()

    assert repeated.applied == ()
    legacy = database.execute_one("select account_type from app_user where id = 'legacy-user'")
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
            for row in database.execute("select name from sqlite_master where type = 'table'")
        }
    )
    columns = {str(row["name"]) for row in database.execute("pragma table_info(agent_job)")}
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


def test_simplification_migration_revokes_old_webhooks_and_preserves_events(tmp_path, monkeypatch):
    from backend.tests.test_dingtalk_enterprise_migration import _catalog_through
    from app.modules.webhook.domain.models import WebhookEventStatus

    old = _catalog_through(tmp_path, 156)
    current = default_migrations_dir()
    with monkeypatch.context() as patch:
        from backend.tests.support.migrations import seed_before_execution_user_migration

        patch.setattr("app.bootstrap.local_seed_sql", seed_before_execution_user_migration)
        patch.setattr("app.bootstrap.default_migrations_dir", lambda: old)
        patch.setattr("app.shared.runtime_config_loader.default_migrations_dir", lambda: old)
        c = container()
    try:
        c.database.execute("""insert into webhook_trigger_revision
          (id,trigger_id,revision,status,schema_version,config_json,config_hash,validation_json,created_by,created_at,updated_at)
          values ('old-webhook-revision','webhook_trigger_grafana_default',1,'published',1,'{}','hash','{}','user_local_admin',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)""")
        c.database.execute("""insert into webhook_trigger_publication
          (id,trigger_id,revision_id,revision,schema_version,snapshot_json,config_hash,agent_publication_id,agent_revision,agent_config_hash,status,published_by,published_at)
          values ('old-webhook-publication','webhook_trigger_grafana_default','old-webhook-revision',1,1,'{}','hash','agent_publication_default_v1',1,'hash','active','user_local_admin',CURRENT_TIMESTAMP)""")
        c.database.execute(
            "update webhook_trigger_definition set status='enabled',current_publication_id='old-webhook-publication'"
        )
        # Use the pre-upgrade shape explicitly to exercise the table rebuild and its FK dependants.
        c.database.execute("""insert into webhook_event
          (id,trigger_id,trigger_publication_id,agent_publication_id,service_account_id,payload_hash,correlation_id,status,received_at)
          values ('old-event','webhook_trigger_grafana_default','old-webhook-publication','agent_publication_default_v1','user_webhook_grafana_default','hash','synthetic', 'ACCEPTED',CURRENT_TIMESTAMP)""")
        Migrator(c.database, current, migrator_build="webhook-v2-upgrade").run()
        assert (
            c.webhook_trigger_repository.get_definition("grafana-default")["status"] == "disabled"
        )
        assert (
            c.webhook_trigger_repository.get_publication("old-webhook-publication")["status"]
            == "revoked"
        )
        assert (
            c.webhook_event_repository.get("old-event")["agent_publication_id"]
            == "agent_publication_default_v1"
        )
        rejected, _ = c.webhook_event_repository.receive(
            trigger_id="webhook_trigger_grafana_default",
            trigger_publication_id="old-webhook-publication",
            agent_publication_id="",
            execution_user_id="user_webhook_grafana_default",
            external_event_id="",
            dedup_key=None,
            payload_hash="hash",
            request_bytes=1,
            safe_summary={},
            normalized_event={},
            correlation_id="rejected",
            status=WebhookEventStatus.REJECTED_AUTH,
            auth_result="failed",
            filter_result="rejected",
        )
        assert rejected["agent_publication_id"] is None
        assert c.database.execute("pragma foreign_key_check") == []
        assert Migrator(c.database, current, migrator_build="repeat").run().applied == ()
    finally:
        c.database.close()
