from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.modules.identity.application.external_credentials import (
    ExternalCredentialBindingService,
)
from app.modules.identity.api.external_credential_controller import (
    BeginOnesBindingRequest,
    ConfirmOnesBindingRequest,
)
from app.modules.identity.infrastructure import (
    AuthenticatedOnesSubject,
    DingTalkBindingChallengeRepository,
    IdentityRepository,
    ProviderCredentialCipher,
    ProviderCredentialRepository,
    ProviderInstanceRepository,
)
from app.shared.database import Database, default_migrations_dir
from app.shared.exceptions import NonRetryableExecutionError
from app.shared.migrations import Migrator, load_migration_catalog


NOW = "2026-08-08T00:00:00+00:00"
MASTER_KEY = "provider-credential-test-master-key-32-bytes"


class RecordingAudit:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def record(self, event_type: str, **values: Any) -> str:
        self.events.append({"event_type": event_type, **values})
        return f"audit-{len(self.events)}"


class AllowAuthorization:
    def require(self, **_: Any) -> None:
        return None


class DenyAuthorization:
    def require(self, **_: Any) -> None:
        raise NonRetryableExecutionError(
            "Denied",
            safe_message="无权管理其他用户的凭据",
            error_code="permission_denied",
        )


class FakeAuthenticator:
    def __init__(self) -> None:
        self.password_seen = ""
        self.token = "ones-personal-token"

    def authenticate(
        self,
        *,
        provider_instance: dict[str, Any],
        email: str,
        password: str,
    ) -> AuthenticatedOnesSubject:
        assert provider_instance["status"] == "ACTIVE"
        assert email == "person@example.test"
        self.password_seen = password
        return AuthenticatedOnesSubject(
            external_user_id="ones-user-1",
            display_name="ONES Person",
            teams=(
                {"id": "team-a", "name": "Team A"},
                {"id": "team-b", "name": "Team B"},
            ),
            token=self.token,
        )


@pytest.fixture
def database() -> Database:
    value = Database("sqlite:///:memory:")
    Migrator(value, default_migrations_dir(), migrator_build="provider-identity-test").run()
    _insert_user(value, "user-1", "person")
    try:
        yield value
    finally:
        value.close()


def _insert_user(database: Database, user_id: str, username: str) -> None:
    database.execute(
        """
        insert into app_user
          (id, username, display_name, email, status, account_type,
           revision, created_at, updated_at)
        values (?, ?, ?, '', 'enabled', 'human', 1, ?, ?)
        """,
        (user_id, username, username, NOW, NOW),
    )


def _provider(database: Database) -> dict[str, Any]:
    return ProviderInstanceRepository(database).ensure_trusted_ones(
        code="ones-main",
        display_name="ONES Main",
        base_url="https://ones.example.test",
        allowed_hosts=("ones.example.test",),
    )


def _service(
    database: Database,
    *,
    authorization: Any | None = None,
) -> tuple[ExternalCredentialBindingService, FakeAuthenticator]:
    authenticator = FakeAuthenticator()
    service = ExternalCredentialBindingService(
        identity_repository=IdentityRepository(database),
        credential_repository=ProviderCredentialRepository(database),
        provider_instances=ProviderInstanceRepository(database),
        credential_cipher=ProviderCredentialCipher(MASTER_KEY),
        authenticator=authenticator,  # type: ignore[arg-type]
        audit_service=RecordingAudit(),  # type: ignore[arg-type]
        authorization=authorization or AllowAuthorization(),  # type: ignore[arg-type]
        provider_instance_code="ones-main",
        dingtalk_challenges=DingTalkBindingChallengeRepository(database),
    )
    return service, authenticator


def test_migration_preserves_ones_identity_metadata_but_requires_reverification() -> None:
    database = Database("sqlite:///:memory:")
    try:
        catalog = load_migration_catalog(default_migrations_dir())
        for artifact in catalog:
            if artifact.version == "034":
                break
            database.execute_script(artifact.sql, ignore_existing_errors=False)
        _insert_user(database, "legacy-user", "legacy")
        metadata = json.dumps(
            {
                "team_uuids": ["legacy-team"],
                "teams": [{"id": "legacy-team", "name": "Legacy Team"}],
                "default_team_id": "legacy-team",
            }
        )
        database.execute(
            """
            insert into user_external_identity
              (id, user_id, provider, tenant_code, external_subject_id,
               display_name, status, metadata_json, revision, created_at, updated_at)
            values ('legacy-ones', 'legacy-user', 'ones', 'ones-main',
                    'legacy-subject', 'Legacy ONES', 'enabled', ?, 7, ?, ?)
            """,
            (metadata, NOW, NOW),
        )
        migration = next(item for item in catalog if item.version == "034")
        database.execute_script(migration.sql, ignore_existing_errors=False)
        identity = database.execute_one(
            "select * from user_external_identity where id = 'legacy-ones'"
        )
        assert identity
        assert identity["status"] == "REVERIFICATION_REQUIRED"
        assert identity["provider_instance_id"] is None
        assert json.loads(identity["metadata_json"])["default_team_id"] == "legacy-team"
        assert (
            database.execute_one("select count(*) as count from provider_credential")["count"] == 0
        )
    finally:
        database.close()


def test_ones_challenge_discards_password_and_atomically_rotates_encrypted_token(
    database: Database,
) -> None:
    provider = _provider(database)
    service, authenticator = _service(database)
    challenge = service.begin_self_binding(
        actor_id="user-1",
        email="person@example.test",
        password="one-time-password",
    )
    assert authenticator.password_seen == "one-time-password"
    assert challenge["provider_instance_id"] == provider["id"]
    assert "token" not in json.dumps(challenge).lower()
    assert "one-time-password" not in _database_text(database)

    result = service.confirm_self_binding(
        actor_id="user-1",
        challenge_id=str(challenge["id"]),
        default_team_id="team-a",
    )
    assert result["ones"]["availability"] == "AVAILABLE"
    encrypted = ProviderCredentialRepository(database).get_current_encrypted(
        user_id="user-1",
        provider_instance_id=str(provider["id"]),
    )
    assert (
        ProviderCredentialCipher(MASTER_KEY).decrypt(
            ciphertext=encrypted.ciphertext,
            key_id=encrypted.key_id,
        )
        == "ones-personal-token"
    )
    consumed = database.execute_one(
        "select * from provider_verification_challenge where id = ?",
        (challenge["id"],),
    )
    assert consumed
    assert consumed["status"] == "CONSUMED"
    assert consumed["token_ciphertext"] == ""
    assert consumed["encryption_key_id"] == ""

    current = IdentityRepository(database).find_external_identity(
        provider="ones",
        tenant_code="ones-main",
        external_subject_id="ones-user-1",
        include_disabled=True,
    )
    assert current
    assert current["status"] == "enabled"
    assert current["metadata"]["default_team_id"] == "team-a"

    changed = service.change_default_team(
        actor_id="user-1",
        default_team_id="team-b",
        expected_identity_revision=int(current["revision"]),
    )
    assert changed["ones"]["default_team"] == {"id": "team-b", "name": "Team B"}

    authenticator.token = "rotated-ones-token"
    rotation = service.begin_self_binding(
        actor_id="user-1",
        email="person@example.test",
        password="second-one-time-password",
    )
    service.confirm_self_binding(
        actor_id="user-1",
        challenge_id=str(rotation["id"]),
        default_team_id="team-b",
    )
    credentials = database.execute(
        "select status, revision from provider_credential order by revision"
    )
    assert credentials == [
        {"status": "DISABLED", "revision": 1},
        {"status": "ACTIVE", "revision": 2},
    ]
    rotated = ProviderCredentialRepository(database).get_current_encrypted(
        user_id="user-1",
        provider_instance_id=str(provider["id"]),
    )
    assert (
        ProviderCredentialCipher(MASTER_KEY).decrypt(
            ciphertext=rotated.ciphertext,
            key_id=rotated.key_id,
        )
        == "rotated-ones-token"
    )
    service.apply_http_status(user_id="user-1", status=403)
    assert (
        ProviderCredentialRepository(database).get_current_public(user_id="user-1")["status"]
        == "ACTIVE"
    )
    service.apply_http_status(user_id="user-1", status=401)
    assert (
        ProviderCredentialRepository(database).get_current_public(user_id="user-1")["status"]
        == "INVALID"
    )


def test_provider_identity_constraints_and_challenge_single_consumption(
    tmp_path: Path,
) -> None:
    path = tmp_path / "identity-concurrency.db"
    dsn = f"sqlite:///{path}"
    setup = Database(dsn)
    Migrator(setup, default_migrations_dir(), migrator_build="provider-concurrency").run()
    _insert_user(setup, "user-1", "person")
    _insert_user(setup, "user-2", "other")
    provider = _provider(setup)
    cipher = ProviderCredentialCipher(MASTER_KEY)
    challenge = ProviderCredentialRepository(setup).create_challenge(
        user_id="user-1",
        provider_instance_id=str(provider["id"]),
        external_user_id="ones-subject",
        display_name="Person",
        teams=[{"id": "team-a", "name": "A"}],
        encrypted_token=cipher.encrypt("token"),
        expires_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
    )
    setup.close()

    def consume() -> str:
        database = Database(dsn, pool_timeout_seconds=2)
        try:
            ProviderCredentialRepository(database).consume_challenge(
                str(challenge["id"]),
                user_id="user-1",
                provider_instance_id=str(provider["id"]),
                default_team_id="team-a",
            )
            return "succeeded"
        except Exception:
            return "rejected"
        finally:
            database.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: consume(), range(2)))
    assert sorted(outcomes) == ["rejected", "succeeded"]
    verify = Database(dsn)
    try:
        assert (
            verify.execute_one(
                "select count(*) as count from provider_credential where status = 'ACTIVE'"
            )["count"]
            == 1
        )
        with pytest.raises(Exception):
            verify.execute(
                """
                insert into user_external_identity
                  (id, user_id, provider, tenant_code, external_subject_id,
                   display_name, status, metadata_json, revision, created_at,
                   updated_at, provider_instance_id)
                values ('duplicate', 'user-2', 'ones', 'ones-main', 'ones-subject',
                        '', 'enabled', '{}', 1, ?, ?, ?)
                """,
                (NOW, NOW, provider["id"]),
            )
    finally:
        verify.close()


def test_dingtalk_challenge_uses_only_trusted_event_subject_and_is_single_use(
    database: Database,
) -> None:
    repository = DingTalkBindingChallengeRepository(database)
    challenge = repository.create(
        user_id="user-1",
        expires_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
    )
    database.execute(
        """
        insert into dingtalk_enterprise
          (id, name, corp_id, status, verification_event_id, verified_at,
           revision, created_by, created_at, updated_at)
        values ('enterprise-1', 'Trusted Corp', 'corp-1', 'ACTIVE', 'event-0', ?,
                1, 'user-1', ?, ?)
        """,
        (NOW, NOW, NOW),
    )
    database.execute(
        """
        insert into integration_connector
          (id, connector_type, name, base_url, enabled, metadata,
           created_at, updated_at, dingtalk_enterprise_id)
        values ('connector-1', 'dingtalk_enterprise_stream', 'Trusted App', '', 1,
                '{}', ?, ?, 'enterprise-1')
        """,
        (NOW, NOW),
    )
    result = repository.consume_trusted_event(
        code=challenge["code"],
        dingtalk_enterprise_id="enterprise-1",
        external_subject_id="staff-from-trusted-event",
        display_name="Trusted Person",
        connector_id="connector-1",
        trusted_event_id="trusted-event-1",
        occurred_at=NOW,
    )
    identity = IdentityRepository(database).get_external_identity(result["identity_id"])
    assert identity["external_subject_id"] == "staff-from-trusted-event"
    assert identity["user_id"] == "user-1"
    with pytest.raises(Exception):
        _insert_user(database, "duplicate-system-user", "person")
    _insert_user(database, "user-2", "other")
    with pytest.raises(Exception):
        database.execute(
            """
            insert into user_external_identity
              (id, user_id, provider, tenant_code, external_subject_id,
               display_name, status, metadata_json, revision, created_at,
               updated_at, dingtalk_enterprise_id)
            values ('duplicate-dingtalk', 'user-2', 'dingtalk', 'enterprise-1',
                    'staff-from-trusted-event', '', 'enabled', '{}', 1, ?, ?,
                    'enterprise-1')
            """,
            (NOW, NOW),
        )
    with pytest.raises(NonRetryableExecutionError):
        repository.consume_trusted_event(
            code=challenge["code"],
            dingtalk_enterprise_id="enterprise-1",
            external_subject_id="forged-browser-subject",
            display_name="Forged",
            connector_id="connector-1",
            trusted_event_id="trusted-event-2",
            occurred_at=NOW,
        )


def test_self_binding_contract_has_no_target_user_or_provider_override(
    database: Database,
) -> None:
    _provider(database)
    begin_fields = BeginOnesBindingRequest.model_json_schema()["properties"]
    confirm_fields = ConfirmOnesBindingRequest.model_json_schema()["properties"]
    assert set(begin_fields) == {"email", "password"}
    assert set(confirm_fields) == {
        "challenge_id",
        "default_team_id",
        "replace_existing",
    }
    denied, _ = _service(database, authorization=DenyAuthorization())
    with pytest.raises(NonRetryableExecutionError) as raised:
        denied.admin_status(actor_id="user-1", user_id="another-user")
    assert raised.value.error_code == "permission_denied"


def _database_text(database: Database) -> str:
    values: list[str] = []
    tables = database.execute(
        "select name from sqlite_master where type = 'table' and name not like 'sqlite_%'"
    )
    for table in tables:
        name = str(table["name"])
        values.extend(
            json.dumps(row, default=str) for row in database.execute(f'select * from "{name}"')
        )
    return "\n".join(values)
