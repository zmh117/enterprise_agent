from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.modules.api_capability.infrastructure import (
    ApiConnectionRepository,
    HttpJsonResponse,
)
from app.modules.identity.application.external_credentials import (
    ExternalCredentialBindingService,
)
from app.modules.identity.infrastructure import (
    ExternalApiCredentialCipher,
    ExternalApiCredentialRepository,
    IdentityRepository,
)
from app.shared.database import Database, default_migrations_dir
from app.shared.exceptions import NonRetryableExecutionError
from app.shared.migrations import Migrator


USER_ID = "external-credential-user"
ADMIN_ID = "external-credential-admin"
OTHER_ID = "external-credential-other"
NOW = "2026-07-31T00:00:00+00:00"


def _profile() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "login": {
            "method": "POST",
            "relative_path": "/project/api/project/auth/login",
            "email_field": "email",
            "password_field": "password",
        },
        "extract": {
            "token_path": "$.user.token",
            "user_id_path": "$.user.uuid",
            "display_name_path": "$.user.name",
            "teams_path": "$.teams",
            "team_id_field": "uuid",
            "team_name_field": "name",
        },
        "inject": {
            "header_name": "Ones-Auth-Token",
            "value_prefix": "",
        },
    }


class AllowAuthorization:
    def require(self, **_: Any) -> None:
        return None


class RecordingAudit:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def record(self, event_type: str, **values: Any) -> str:
        self.events.append({"event_type": event_type, **values})
        return f"audit-{len(self.events)}"


class LoginHttpClient:
    def __init__(self) -> None:
        self.external_user_id = "ones-user-a"
        self.token = "ones-token-a"
        self.teams = [
            {"uuid": "team-a", "name": "Team A"},
            {"uuid": "team-b", "name": "Team B"},
        ]
        self.calls: list[dict[str, Any]] = []

    def request(self, **values: Any) -> HttpJsonResponse:
        self.calls.append(values)
        return HttpJsonResponse(
            payload={
                "user": {
                    "uuid": self.external_user_id,
                    "name": "ONES User",
                    "token": self.token,
                },
                "teams": self.teams,
            },
            status=200,
            duration_ms=1,
            response_size=128,
        )


@pytest.fixture
def database() -> Database:
    value = Database("sqlite:///:memory:")
    Migrator(
        value,
        default_migrations_dir(),
        migrator_build="external-credential-binding-test",
    ).run()
    for user_id, username in (
        (USER_ID, "credential-user"),
        (ADMIN_ID, "credential-admin"),
        (OTHER_ID, "credential-other"),
    ):
        value.execute(
            """
            insert into app_user
              (id, username, display_name, status, created_at, updated_at)
            values (?, ?, ?, 'enabled', ?, ?)
            """,
            (user_id, username, username, NOW, NOW),
        )
    try:
        yield value
    finally:
        value.close()


def _published_connection(database: Database) -> dict[str, Any]:
    repository = ApiConnectionRepository(database)
    connection = repository.create(
        code="ones-credential-test",
        name="ONES Credential Test",
        provider="ones",
        origin={
            "scheme": "https",
            "host": "ones.example.test",
            "port": 443,
        },
        authentication=_profile(),
        actor_id=ADMIN_ID,
    )
    draft = connection["draft"]
    repository.record_verification(
        str(connection["id"]),
        draft_revision=int(draft["draft_revision"]),
        draft_hash=str(draft["content_hash"]),
        actor_id=ADMIN_ID,
        status="PASSED",
        checks={"login": "passed"},
    )
    return repository.publish(
        str(connection["id"]),
        draft_revision=int(draft["draft_revision"]),
        draft_hash=str(draft["content_hash"]),
        actor_id=ADMIN_ID,
    )


def _service(
    database: Database,
) -> tuple[
    ExternalCredentialBindingService,
    LoginHttpClient,
    RecordingAudit,
    ExternalApiCredentialRepository,
]:
    _published_connection(database)
    http_client = LoginHttpClient()
    audit = RecordingAudit()
    credential_repository = ExternalApiCredentialRepository(database)
    service = ExternalCredentialBindingService(
        identity_repository=IdentityRepository(database),
        credential_repository=credential_repository,
        connection_repository=ApiConnectionRepository(database),
        credential_cipher=ExternalApiCredentialCipher("external-credential-test-key"),
        audit_service=audit,  # type: ignore[arg-type]
        authorization=AllowAuthorization(),  # type: ignore[arg-type]
        http_client=http_client,  # type: ignore[arg-type]
        challenge_ttl_seconds=300,
    )
    return service, http_client, audit, credential_repository


def test_two_phase_binding_returns_candidates_and_persists_only_ciphertext(
    database: Database,
) -> None:
    service, _, audit, credentials = _service(database)
    challenge = service.begin_self_binding(
        actor_id=USER_ID,
        email="user@example.test",
        password="not-persisted-password",
    )
    assert challenge["team_ids"] == ["team-a", "team-b"]
    assert challenge["teams"][0] == {"id": "team-a", "name": "Team A"}
    assert "token" not in json.dumps(challenge).lower()
    result = service.confirm_self_binding(
        actor_id=USER_ID,
        challenge_id=str(challenge["id"]),
        connection_revision_id=str(challenge["connection_revision_id"]),
        default_team_id="team-b",
    )
    assert result["identity"]["metadata"]["default_team_id"] == "team-b"
    assert result["identity"]["credential_status"] == "ACTIVE"
    assert result["credential"]["status"] == "ACTIVE"
    persisted = json.dumps(
        {
            "challenge": database.execute("select * from external_api_verification_challenge"),
            "credential": database.execute("select * from external_api_credential"),
            "identity": database.execute("select * from user_external_identity"),
            "audit": audit.events,
            "result": result,
        }
    )
    assert "not-persisted-password" not in persisted
    assert "ones-token-a" not in persisted
    encrypted = credentials.get_current_encrypted(user_id=USER_ID)
    assert encrypted.ciphertext != "ones-token-a"


def test_self_unbind_soft_disables_identity_and_credential(
    database: Database,
) -> None:
    service, _, audit, credentials = _service(database)
    challenge = service.begin_self_binding(
        actor_id=USER_ID,
        email="user@example.test",
        password="not-persisted-password",
    )
    service.confirm_self_binding(
        actor_id=USER_ID,
        challenge_id=str(challenge["id"]),
        connection_revision_id=str(challenge["connection_revision_id"]),
        default_team_id="team-a",
    )

    service.self_unbind(actor_id=USER_ID)

    assert credentials.get_latest_public(user_id=USER_ID)["status"] == "DISABLED"
    identities = IdentityRepository(database).list_external_identities(USER_ID)
    assert identities[0]["status"] == "unbound"
    assert audit.events[-1]["event_type"] == "external_credential.self_unbound"


def test_challenge_rejects_replay_cross_user_expiry_and_unverified_team(
    database: Database,
) -> None:
    service, _, _, _ = _service(database)
    challenge = service.begin_self_binding(
        actor_id=USER_ID,
        email="user@example.test",
        password="password",
    )
    with pytest.raises(NonRetryableExecutionError) as wrong_user:
        service.confirm_self_binding(
            actor_id=OTHER_ID,
            challenge_id=str(challenge["id"]),
            connection_revision_id=str(challenge["connection_revision_id"]),
            default_team_id="team-a",
        )
    assert wrong_user.value.error_code == "external_challenge_invalid"
    with pytest.raises(NonRetryableExecutionError) as wrong_team:
        service.confirm_self_binding(
            actor_id=USER_ID,
            challenge_id=str(challenge["id"]),
            connection_revision_id=str(challenge["connection_revision_id"]),
            default_team_id="forged-team",
        )
    assert wrong_team.value.error_code == "ones_team_not_verified"
    service.confirm_self_binding(
        actor_id=USER_ID,
        challenge_id=str(challenge["id"]),
        connection_revision_id=str(challenge["connection_revision_id"]),
        default_team_id="team-a",
    )
    with pytest.raises(NonRetryableExecutionError) as replay:
        service.confirm_self_binding(
            actor_id=USER_ID,
            challenge_id=str(challenge["id"]),
            connection_revision_id=str(challenge["connection_revision_id"]),
            default_team_id="team-a",
        )
    assert replay.value.error_code == "external_challenge_invalid"

    expired = service.begin_self_binding(
        actor_id=OTHER_ID,
        email="other@example.test",
        password="password",
    )
    database.execute(
        """
        update external_api_verification_challenge
           set expires_at = ? where id = ?
        """,
        (
            (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
            expired["id"],
        ),
    )
    with pytest.raises(NonRetryableExecutionError):
        service.confirm_self_binding(
            actor_id=OTHER_ID,
            challenge_id=str(expired["id"]),
            connection_revision_id=str(expired["connection_revision_id"]),
            default_team_id="team-a",
        )
    row = database.execute_one(
        """
        select status from external_api_verification_challenge where id = ?
        """,
        (expired["id"],),
    )
    assert row == {"status": "EXPIRED"}


def test_concurrent_challenge_confirmation_has_exactly_one_winner(
    database: Database,
) -> None:
    service, _, _, _ = _service(database)
    challenge = service.begin_self_binding(
        actor_id=USER_ID,
        email="user@example.test",
        password="password",
    )

    def confirm(_: int) -> str:
        try:
            service.confirm_self_binding(
                actor_id=USER_ID,
                challenge_id=str(challenge["id"]),
                connection_revision_id=str(challenge["connection_revision_id"]),
                default_team_id="team-a",
            )
            return "bound"
        except NonRetryableExecutionError as exc:
            return exc.error_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(confirm, range(2)))
    assert sorted(outcomes) == ["bound", "external_challenge_invalid"]


def test_default_team_switch_refreshes_teams_and_account_change_is_explicit(
    database: Database,
) -> None:
    service, http_client, _, _ = _service(database)
    first = service.begin_self_binding(
        actor_id=USER_ID,
        email="user@example.test",
        password="password",
    )
    service.confirm_self_binding(
        actor_id=USER_ID,
        challenge_id=str(first["id"]),
        connection_revision_id=str(first["connection_revision_id"]),
        default_team_id="team-a",
    )
    http_client.teams = [
        {"uuid": "team-b", "name": "Team B"},
        {"uuid": "team-c", "name": "Team C"},
    ]
    refreshed = service.begin_self_binding(
        actor_id=USER_ID,
        email="user@example.test",
        password="password",
    )
    switched = service.confirm_self_binding(
        actor_id=USER_ID,
        challenge_id=str(refreshed["id"]),
        connection_revision_id=str(refreshed["connection_revision_id"]),
        default_team_id="team-c",
    )
    assert switched["identity"]["metadata"]["team_uuids"] == [
        "team-b",
        "team-c",
    ]
    assert switched["identity"]["metadata"]["default_team_id"] == "team-c"

    http_client.external_user_id = "ones-user-b"
    changed = service.begin_self_binding(
        actor_id=USER_ID,
        email="second@example.test",
        password="password",
    )
    with pytest.raises(NonRetryableExecutionError) as confirmation:
        service.confirm_self_binding(
            actor_id=USER_ID,
            challenge_id=str(changed["id"]),
            connection_revision_id=str(changed["connection_revision_id"]),
            default_team_id="team-b",
        )
    assert confirmation.value.error_code == "ones_rebind_confirmation_required"
    replaced = service.confirm_self_binding(
        actor_id=USER_ID,
        challenge_id=str(changed["id"]),
        connection_revision_id=str(changed["connection_revision_id"]),
        default_team_id="team-b",
        replace_existing=True,
    )
    assert replaced["identity"]["external_subject_id"] == "ones-user-b"
    assert database.execute_one(
        """
            select count(*) as count from user_external_identity
             where user_id = ? and provider = 'ones' and status = 'enabled'
            """,
        (USER_ID,),
    ) == {"count": 1}


def test_401_invalidates_credential_403_preserves_and_admin_never_reads_token(
    database: Database,
) -> None:
    service, _, _, credentials = _service(database)
    challenge = service.begin_self_binding(
        actor_id=USER_ID,
        email="user@example.test",
        password="password",
    )
    service.confirm_self_binding(
        actor_id=USER_ID,
        challenge_id=str(challenge["id"]),
        connection_revision_id=str(challenge["connection_revision_id"]),
        default_team_id="team-a",
    )
    service.apply_http_status(user_id=USER_ID, status=403)
    assert credentials.get_current_public(user_id=USER_ID)["status"] == "ACTIVE"
    service.apply_http_status(user_id=USER_ID, status=401)
    assert credentials.get_current_public(user_id=USER_ID)["status"] == "INVALID"
    admin_view = service.admin_status(actor_id=ADMIN_ID, user_id=USER_ID)
    assert admin_view["credential"]["status"] == "INVALID"
    assert "token" not in json.dumps(admin_view).lower()
    disabled = service.admin_disable(actor_id=ADMIN_ID, user_id=USER_ID)
    assert disabled["status"] == "DISABLED"
    service.admin_unbind(actor_id=ADMIN_ID, user_id=USER_ID)
    identity = IdentityRepository(database).list_external_identities(USER_ID)[0]
    assert identity["status"] == "unbound"
