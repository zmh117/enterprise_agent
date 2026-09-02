from __future__ import annotations

from dataclasses import replace
import json

import pytest
from fastapi.testclient import TestClient

from app.bootstrap import Container, build_test_container
from app.main import create_app
from app.modules.identity.application.ones_identity import (
    VerifiedOnesIdentity,
    VerifiedOnesTeam,
)
from app.modules.identity.infrastructure.external_identity_credentials import (
    CredentialSecretBundle,
)
from app.shared.exceptions import NonRetryableExecutionError
from app.shared.config import IdentitySettings, Settings
from backend.tests.helpers import test_settings as base_test_settings


ADMIN_PASSWORD = "111111111111"
ORIGIN = "http://admin.test"


def test_ones_identity_verifier_can_be_imported_without_bootstrap_ordering() -> None:
    from app.modules.identity.infrastructure.ones_identity_verifier import (
        UrllibOnesIdentityVerifier,
    )

    assert UrllibOnesIdentityVerifier.__name__ == "UrllibOnesIdentityVerifier"


class FakeOnesVerifier:
    available = True

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []
        self.teams = (
            VerifiedOnesTeam(id="TEAM-A", name="Team A"),
            VerifiedOnesTeam(id="TEAM-B", name="Team B"),
        )
        self.user_uuid = "ONES-USER-001"
        self.token = "single-request-token"

    def verify(self, *, email: str, password: str) -> VerifiedOnesIdentity:
        self.calls.append({"email": email, "password": password})
        return VerifiedOnesIdentity.create(
            user_uuid=self.user_uuid,
            display_name="ONES User",
            teams=self.teams,
            token=self.token,
        )


def settings() -> Settings:
    return replace(
        base_test_settings(),
        environment="test",
        identity=IdentitySettings(
            enabled=True,
            web_admin_enabled=True,
            published_agent_runtime_enabled=True,
            test_identity_headers_enabled=False,
            cookie_secure=False,
            allowed_origins=(ORIGIN,),
        ),
    )


def runtime() -> tuple[Container, FakeOnesVerifier]:
    container = build_test_container(settings(), migrate=True, seed=True)
    verifier = FakeOnesVerifier()
    container.ones_identity_binding_service.verifier = verifier
    return container, verifier


def login(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    csrf = client.cookies.get("enterprise_agent_csrf")
    assert csrf
    return {"origin": ORIGIN, "x-csrf-token": csrf}


def create_login_user(container: Container) -> tuple[dict[str, object], str]:
    user = container.identity_repository.create_user(
        username="ones-self-user",
        display_name="ONES Self User",
    )
    password = "ones-self-password"
    container.identity_repository.set_password_hash(
        str(user["id"]),
        container.auth_service.passwords.hash(password),
    )
    return user, password


def test_migration_adds_new_credential_boundary_without_legacy_credential() -> None:
    container, _ = runtime()
    tables = {
        str(row["name"])
        for row in container.database.execute("select name from sqlite_master where type = 'table'")
    }

    assert "ones_identity_verification_challenge" in tables
    assert "external_identity_credential" in tables
    assert "external_api_verification_challenge" not in tables
    assert "external_api_credential" not in tables


def test_self_binding_reverification_team_selection_and_unbind_store_no_login_material() -> None:
    container, verifier = runtime()
    user, password = create_login_user(container)
    app = create_app(settings(), container_factory=lambda _: container)
    email = "ones.user@example.test"
    login_password = "single-request-secret"

    with TestClient(app) as client:
        headers = login(client, str(user["username"]), password)
        begin = client.post(
            "/api/me/external-identities/ones/challenges",
            headers=headers,
            json={"email": email, "password": login_password},
        )
        assert begin.status_code == 200, begin.text
        challenge = begin.json()["challenge"]
        assert challenge["team_ids"] == ["TEAM-A", "TEAM-B"]
        assert challenge["teams"][0] == {"id": "TEAM-A", "name": "Team A"}
        serialized_response = json.dumps(challenge, ensure_ascii=False)
        assert email not in serialized_response
        assert login_password not in serialized_response
        assert "token" not in serialized_response.lower()
        assert "connection" not in serialized_response.lower()

        raw_challenge = container.database.execute_one(
            "select * from ones_identity_verification_challenge where id = ?",
            (challenge["id"],),
        )
        assert raw_challenge is not None
        serialized_row = json.dumps(raw_challenge, ensure_ascii=False)
        assert email not in serialized_row
        assert login_password not in serialized_row
        assert "single-request-token" not in serialized_row
        assert raw_challenge["login_material_ciphertext"]
        assert raw_challenge["token_ciphertext"]

        confirmed = client.post(
            "/api/me/external-identities/ones/confirm",
            headers=headers,
            json={
                "challenge_id": challenge["id"],
                "default_team_id": "TEAM-B",
                "replace_existing": False,
            },
        )
        assert confirmed.status_code == 200, confirmed.text
        credential = confirmed.json()["ones"]["credential"]
        assert confirmed.json()["ones"] == {
            "provider": "ones",
            "user_name": "ONES User",
            "status": "enabled",
            "default_team": {"id": "TEAM-B", "name": "Team B"},
            "verified_at": confirmed.json()["ones"]["verified_at"],
            "user_id": "ONES-USER-001",
            "teams": [
                {"id": "TEAM-A", "name": "Team A"},
                {"id": "TEAM-B", "name": "Team B"},
            ],
            "credential": credential,
        }
        assert credential == {
            "configured": True,
            "status": "ACTIVE",
            "revision": 1,
            "verified_at": challenge["verified_at"],
            "token_refreshed_at": None,
            "last_used_at": None,
            "reauth_required_at": None,
            "disabled_at": None,
            "unbound_at": None,
        }

        verifier.teams = (VerifiedOnesTeam(id="TEAM-C", name="Team C"),)
        reverified = client.post(
            "/api/me/external-identities/ones/challenges",
            headers=headers,
            json={"email": email, "password": login_password},
        )
        assert reverified.status_code == 200
        reconfirmed = client.post(
            "/api/me/external-identities/ones/confirm",
            headers=headers,
            json={
                "challenge_id": reverified.json()["challenge"]["id"],
                "default_team_id": "TEAM-C",
                "replace_existing": False,
            },
        )
        assert reconfirmed.status_code == 200, reconfirmed.text
        assert reconfirmed.json()["ones"]["teams"] == [{"id": "TEAM-C", "name": "Team C"}]
        assert reconfirmed.json()["ones"]["credential"]["revision"] == 2

        unbound = client.delete(
            "/api/me/external-identities/ones",
            headers=headers,
        )
        assert unbound.status_code == 200
        assert client.get("/api/me/external-identities/ones").json()["ones"] is None

        identity_and_secrets = json.dumps(
            {
                "identity": container.database.execute(
                    "select * from user_external_identity where user_id = ?",
                    (user["id"],),
                ),
                "challenge": container.database.execute(
                    "select * from ones_identity_verification_challenge where user_id = ?",
                    (user["id"],),
                ),
                "credential": container.database.execute(
                    """
                    select c.*
                      from external_identity_credential c
                      join user_external_identity i on i.id = c.external_identity_id
                     where i.user_id = ?
                    """,
                    (user["id"],),
                ),
            },
            ensure_ascii=False,
        )
        audit = json.dumps(
            container.database.execute(
                "select payload_summary from audit_event where actor_id = ?",
                (user["id"],),
            ),
            ensure_ascii=False,
        )

    assert verifier.calls == [
        {"email": email, "password": login_password},
        {"email": email, "password": login_password},
    ]
    assert email not in identity_and_secrets
    assert email in audit
    assert login_password not in identity_and_secrets
    assert login_password not in audit
    assert "single-request-token" not in identity_and_secrets
    assert "single-request-token" not in audit


def test_unbound_ones_subject_can_move_to_verified_user_without_rewriting_history() -> None:
    container, verifier = runtime()
    user_a, _ = create_login_user(container)
    user_b = container.identity_repository.create_user(
        username="ones-rebound-user",
        display_name="ONES Rebound User",
    )
    service = container.ones_identity_binding_service

    challenge_a = service.begin_self_binding(
        actor_id=str(user_a["id"]),
        email="owner-a@example.test",
        password="not-a-real-owner-a-password",
    )
    service.confirm_self_binding(
        actor_id=str(user_a["id"]),
        challenge_id=str(challenge_a["id"]),
        default_team_id="TEAM-A",
    )
    identity_a = next(
        identity
        for identity in container.identity_repository.list_external_identities(
            str(user_a["id"])
        )
        if identity["provider"] == "ones"
    )
    service.self_unbind(actor_id=str(user_a["id"]))
    history_before = container.database.execute_one(
        """
        select id, user_id, external_subject_id, status, revision
          from user_external_identity where id = ?
        """,
        (identity_a["id"],),
    )
    credential_before = container.database.execute_one(
        """
        select id, external_identity_id, status, revision,
               login_material_ciphertext, token_ciphertext
          from external_identity_credential where external_identity_id = ?
        """,
        (identity_a["id"],),
    )
    audit_before = container.database.execute(
        """
        select id, actor_id, payload_summary from audit_event
         where actor_id = ? order by created_at, id
        """,
        (user_a["id"],),
    )
    assert history_before is not None
    assert history_before["user_id"] == user_a["id"]
    assert history_before["status"] == "unbound"
    assert credential_before is not None
    assert credential_before["status"] == "UNBOUND"
    assert credential_before["login_material_ciphertext"] is None
    assert credential_before["token_ciphertext"] is None

    challenge_b = service.begin_self_binding(
        actor_id=str(user_b["id"]),
        email="owner-b@example.test",
        password="not-a-real-owner-b-password",
    )
    rebound = service.confirm_self_binding(
        actor_id=str(user_b["id"]),
        challenge_id=str(challenge_b["id"]),
        default_team_id="TEAM-B",
    )

    assert rebound["ones"]["user_id"] == verifier.user_uuid
    identity_b = next(
        identity
        for identity in container.identity_repository.list_external_identities(
            str(user_b["id"])
        )
        if identity["provider"] == "ones" and identity["status"] == "enabled"
    )
    assert identity_b["id"] != identity_a["id"]
    assert container.database.execute_one(
        """
        select id, user_id, external_subject_id, status, revision
          from user_external_identity where id = ?
        """,
        (identity_a["id"],),
    ) == history_before
    assert container.database.execute_one(
        """
        select id, external_identity_id, status, revision,
               login_material_ciphertext, token_ciphertext
          from external_identity_credential where external_identity_id = ?
        """,
        (identity_a["id"],),
    ) == credential_before
    assert container.database.execute(
        """
        select id, actor_id, payload_summary from audit_event
         where actor_id = ? order by created_at, id
        """,
        (user_a["id"],),
    ) == audit_before
    assert container.database.execute_one(
        """
        select count(*) as count from user_external_identity
         where provider = 'ones' and tenant_code = 'default'
           and external_subject_id = ? and status in ('enabled', 'disabled')
        """,
        (verifier.user_uuid,),
    ) == {"count": 1}

    reverse = service.begin_self_binding(
        actor_id=str(user_a["id"]),
        email="owner-a-again@example.test",
        password="not-a-real-owner-a-again-password",
    )
    with pytest.raises(NonRetryableExecutionError) as reverse_error:
        service.confirm_self_binding(
            actor_id=str(user_a["id"]),
            challenge_id=str(reverse["id"]),
            default_team_id="TEAM-A",
        )
    assert reverse_error.value.error_code == "identity_conflict"


def test_disabled_ones_subject_remains_owned_by_original_user() -> None:
    container, _ = runtime()
    user_a, _ = create_login_user(container)
    user_b = container.identity_repository.create_user(
        username="ones-disabled-contender",
        display_name="ONES Disabled Contender",
    )
    service = container.ones_identity_binding_service
    challenge_a = service.begin_self_binding(
        actor_id=str(user_a["id"]),
        email="disabled-owner@example.test",
        password="not-a-real-disabled-owner-password",
    )
    service.confirm_self_binding(
        actor_id=str(user_a["id"]),
        challenge_id=str(challenge_a["id"]),
        default_team_id="TEAM-A",
    )
    identity_a = next(
        identity
        for identity in container.identity_repository.list_external_identities(
            str(user_a["id"])
        )
        if identity["provider"] == "ones"
    )
    container.identity_repository.set_external_identity_status(
        str(identity_a["id"]),
        status="disabled",
        expected_revision=int(identity_a["revision"]),
    )

    challenge_b = service.begin_self_binding(
        actor_id=str(user_b["id"]),
        email="disabled-contender@example.test",
        password="not-a-real-disabled-contender-password",
    )
    with pytest.raises(NonRetryableExecutionError) as conflict_error:
        service.confirm_self_binding(
            actor_id=str(user_b["id"]),
            challenge_id=str(challenge_b["id"]),
            default_team_id="TEAM-A",
        )
    assert conflict_error.value.error_code == "identity_conflict"
    assert container.identity_repository.get_external_identity(str(identity_a["id"]))[
        "status"
    ] == "disabled"
    assert service.self_status(actor_id=str(user_b["id"]))["ones"] is None


def test_ones_binding_maps_database_unique_race_to_identity_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container, _ = runtime()
    owner = container.identity_repository.create_user(
        username="ones-race-owner",
        display_name="ONES Race Owner",
    )
    contender = container.identity_repository.create_user(
        username="ones-race-contender",
        display_name="ONES Race Contender",
    )
    repository = container.identity_repository
    repository.bind_external_identity(
        user_id=str(owner["id"]),
        provider="ones",
        tenant_code="default",
        external_subject_id="ONES-RACE-SUBJECT",
        connector_id="",
    )
    monkeypatch.setattr(repository, "find_external_identity", lambda **_: None)

    with pytest.raises(NonRetryableExecutionError) as conflict_error:
        repository.bind_external_identity(
            user_id=str(contender["id"]),
            provider="ones",
            tenant_code="default",
            external_subject_id="ONES-RACE-SUBJECT",
            connector_id="",
        )

    assert conflict_error.value.error_code == "identity_conflict"
    assert container.database.execute_one(
        """
        select count(*) as count from user_external_identity
         where provider = 'ones' and tenant_code = 'default'
           and external_subject_id = 'ONES-RACE-SUBJECT'
           and status in ('enabled', 'disabled')
        """
    ) == {"count": 1}


def test_admin_can_read_and_disable_ones_but_cannot_enable_unbind_or_verify_for_user() -> None:
    container, verifier = runtime()
    user, _ = create_login_user(container)
    identity = container.identity_repository.bind_external_identity(
        user_id=str(user["id"]),
        provider="ones",
        tenant_code="default",
        external_subject_id="ONES-ADMIN-BOUND",
        connector_id="",
        display_name="Admin Visible ONES",
        metadata={
            "verification_method": "ones_password_login",
            "teams": [{"id": "TEAM-ADMIN", "name": "Admin Team"}],
            "default_team_id": "TEAM-ADMIN",
        },
    )
    credential_repository = container.external_identity_credential_repository
    assert credential_repository is not None
    credential_repository.upsert_active(
        external_identity_id=str(identity["id"]),
        provider="ones",
        secrets=CredentialSecretBundle(
            email="admin.visible@example.test",
            password="not-a-real-admin-password",
            token="not-a-real-admin-token",
        ),
        verified_at="2026-08-12T00:00:00+00:00",
    )
    app = create_app(settings(), container_factory=lambda _: container)

    with TestClient(app) as client:
        headers = login(client, "admin", ADMIN_PASSWORD)
        overview = client.get(f"/api/admin/users/{user['id']}/external-identities")
        assert overview.status_code == 200, overview.text
        assert overview.json()["current"][0]["provider"] == "ones"
        serialized = json.dumps(overview.json(), ensure_ascii=False).lower()
        assert "password" not in serialized
        assert "not-a-real-admin-token" not in serialized
        assert overview.json()["current"][0]["credential"]["status"] == "ACTIVE"
        assert "connection" not in serialized

        disabled = client.put(
            f"/api/admin/identities/{identity['id']}/status",
            headers=headers,
            json={"expected_revision": identity["revision"], "status": "disabled"},
        )
        assert disabled.status_code == 200, disabled.text
        revision = disabled.json()["identity"]["revision"]
        disabled_overview = client.get(f"/api/admin/users/{user['id']}/external-identities")
        assert disabled_overview.json()["current"][0]["credential"]["status"] == "DISABLED"

        enable = client.put(
            f"/api/admin/identities/{identity['id']}/status",
            headers=headers,
            json={"expected_revision": revision, "status": "enabled"},
        )
        assert enable.status_code == 403

        unbind = client.delete(
            f"/api/admin/identities/{identity['id']}",
            headers=headers,
            params={"expected_revision": revision},
        )
        assert unbind.status_code == 403

        stored = container.identity_repository.get_external_identity(str(identity["id"]))

    assert verifier.calls == []
    assert stored["status"] == "disabled"


def test_challenge_expiry_duplicate_confirm_replacement_and_conflict_fail_closed() -> None:
    container, verifier = runtime()
    user, _ = create_login_user(container)
    service = container.ones_identity_binding_service

    expired = service.begin_self_binding(
        actor_id=str(user["id"]),
        email="expired@example.test",
        password="not-a-real-expired-password",
    )
    container.database.execute(
        "update ones_identity_verification_challenge set expires_at = ? where id = ?",
        ("2020-01-01T00:00:00+00:00", expired["id"]),
    )
    with pytest.raises(NonRetryableExecutionError) as expired_error:
        service.confirm_self_binding(
            actor_id=str(user["id"]),
            challenge_id=str(expired["id"]),
            default_team_id="TEAM-A",
        )
    assert expired_error.value.error_code == "ones_identity_challenge_expired"
    expired_row = container.database.execute_one(
        "select * from ones_identity_verification_challenge where id = ?",
        (expired["id"],),
    )
    assert expired_row is not None
    assert expired_row["status"] == "EXPIRED"
    assert expired_row["login_material_ciphertext"] is None
    assert expired_row["token_ciphertext"] is None

    first = service.begin_self_binding(
        actor_id=str(user["id"]),
        email="first@example.test",
        password="not-a-real-first-password",
    )
    first_status = service.confirm_self_binding(
        actor_id=str(user["id"]),
        challenge_id=str(first["id"]),
        default_team_id="TEAM-A",
    )
    assert first_status["ones"]["credential"]["revision"] == 1
    with pytest.raises(NonRetryableExecutionError) as duplicate_error:
        service.confirm_self_binding(
            actor_id=str(user["id"]),
            challenge_id=str(first["id"]),
            default_team_id="TEAM-A",
        )
    assert duplicate_error.value.error_code == "ones_identity_challenge_invalid"

    verifier.user_uuid = "ONES-USER-REPLACEMENT"
    verifier.token = "replacement-test-token"
    replacement = service.begin_self_binding(
        actor_id=str(user["id"]),
        email="replacement@example.test",
        password="not-a-real-replacement-password",
    )
    with pytest.raises(NonRetryableExecutionError) as replacement_error:
        service.confirm_self_binding(
            actor_id=str(user["id"]),
            challenge_id=str(replacement["id"]),
            default_team_id="TEAM-A",
            replace_existing=False,
        )
    assert replacement_error.value.error_code == "ones_identity_replace_confirmation_required"
    replacement_row = container.database.execute_one(
        "select status, login_material_ciphertext from ones_identity_verification_challenge where id = ?",
        (replacement["id"],),
    )
    assert replacement_row is not None
    assert replacement_row["status"] == "PENDING"
    assert replacement_row["login_material_ciphertext"]

    replacement_status = service.confirm_self_binding(
        actor_id=str(user["id"]),
        challenge_id=str(replacement["id"]),
        default_team_id="TEAM-A",
        replace_existing=True,
    )
    assert replacement_status["ones"]["user_id"] == "ONES-USER-REPLACEMENT"
    historical = container.database.execute_one(
        """
        select c.status, c.login_material_ciphertext, c.token_ciphertext
          from external_identity_credential c
          join user_external_identity i on i.id = c.external_identity_id
         where i.user_id = ? and i.external_subject_id = 'ONES-USER-001'
        """,
        (user["id"],),
    )
    assert historical == {
        "status": "UNBOUND",
        "login_material_ciphertext": None,
        "token_ciphertext": None,
    }

    other_user = container.identity_repository.create_user(
        username="ones-conflict-owner",
        display_name="ONES Conflict Owner",
    )
    container.identity_repository.bind_external_identity(
        user_id=str(other_user["id"]),
        provider="ones",
        tenant_code="default",
        external_subject_id="ONES-CONFLICT-SUBJECT",
        connector_id="",
        display_name="Conflict Subject",
        metadata={"default_team_id": "TEAM-A"},
    )
    verifier.user_uuid = "ONES-CONFLICT-SUBJECT"
    conflict = service.begin_self_binding(
        actor_id=str(user["id"]),
        email="conflict@example.test",
        password="not-a-real-conflict-password",
    )
    with pytest.raises(NonRetryableExecutionError) as conflict_error:
        service.confirm_self_binding(
            actor_id=str(user["id"]),
            challenge_id=str(conflict["id"]),
            default_team_id="TEAM-A",
            replace_existing=True,
        )
    assert conflict_error.value.error_code == "identity_conflict"
    conflict_row = container.database.execute_one(
        "select status, login_material_ciphertext, token_ciphertext from ones_identity_verification_challenge where id = ?",
        (conflict["id"],),
    )
    assert conflict_row == {
        "status": "EXPIRED",
        "login_material_ciphertext": None,
        "token_ciphertext": None,
    }
