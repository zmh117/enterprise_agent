from __future__ import annotations

from dataclasses import replace
import json

from fastapi.testclient import TestClient

from app.bootstrap import Container, build_test_container
from app.main import create_app
from app.modules.identity.application.ones_identity import (
    VerifiedOnesIdentity,
    VerifiedOnesTeam,
)
from app.shared.config import IdentitySettings, Settings
from backend.tests.helpers import test_settings as base_test_settings


ADMIN_PASSWORD = "111111111111"
ORIGIN = "http://admin.test"


class FakeOnesVerifier:
    available = True

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []
        self.teams = (
            VerifiedOnesTeam(id="TEAM-A", name="Team A"),
            VerifiedOnesTeam(id="TEAM-B", name="Team B"),
        )

    def verify(self, *, email: str, password: str) -> VerifiedOnesIdentity:
        self.calls.append({"email": email, "password": password})
        return VerifiedOnesIdentity.create(
            user_uuid="ONES-USER-001",
            display_name="ONES User",
            teams=self.teams,
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


def test_migration_restores_identity_only_challenge_without_legacy_credential() -> None:
    container, _ = runtime()
    tables = {
        str(row["name"])
        for row in container.database.execute(
            "select name from sqlite_master where type = 'table'"
        )
    }

    assert "ones_identity_verification_challenge" in tables
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
        assert "token" not in serialized_row.lower()

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
        assert reconfirmed.json()["ones"]["teams"] == [
            {"id": "TEAM-C", "name": "Team C"}
        ]

        unbound = client.delete(
            "/api/me/external-identities/ones",
            headers=headers,
        )
        assert unbound.status_code == 200
        assert client.get("/api/me/external-identities/ones").json()["ones"] is None

        persisted = json.dumps(
            {
                "identity": container.database.execute(
                    "select * from user_external_identity where user_id = ?",
                    (user["id"],),
                ),
                "challenge": container.database.execute(
                    "select * from ones_identity_verification_challenge where user_id = ?",
                    (user["id"],),
                ),
                    "audit": container.database.execute(
                        "select payload_summary from audit_event where actor_id = ?",
                    (user["id"],),
                ),
            },
            ensure_ascii=False,
        )

    assert verifier.calls == [
        {"email": email, "password": login_password},
        {"email": email, "password": login_password},
    ]
    assert email not in persisted
    assert login_password not in persisted
    assert "single-request-token" not in persisted


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
    app = create_app(settings(), container_factory=lambda _: container)

    with TestClient(app) as client:
        headers = login(client, "admin", ADMIN_PASSWORD)
        overview = client.get(
            f"/api/admin/users/{user['id']}/external-identities"
        )
        assert overview.status_code == 200, overview.text
        assert overview.json()["current"][0]["provider"] == "ones"
        serialized = json.dumps(overview.json(), ensure_ascii=False).lower()
        assert "password" not in serialized
        assert "token" not in serialized
        assert "credential" not in serialized
        assert "connection" not in serialized

        disabled = client.put(
            f"/api/admin/identities/{identity['id']}/status",
            headers=headers,
            json={"expected_revision": identity["revision"], "status": "disabled"},
        )
        assert disabled.status_code == 200, disabled.text
        revision = disabled.json()["identity"]["revision"]

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

        stored = container.identity_repository.get_external_identity(
            str(identity["id"])
        )

    assert verifier.calls == []
    assert stored["status"] == "disabled"
