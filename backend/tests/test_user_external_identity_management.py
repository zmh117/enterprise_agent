from __future__ import annotations

import json
import os
from dataclasses import replace
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request

import pytest
from fastapi.testclient import TestClient

from app.bootstrap import Container, build_test_container
from app.main import create_app
from app.modules.identity.application.ones_identity import VerifiedOnesIdentity
from app.modules.identity.infrastructure.ones_identity_verifier import (
    ONES_LOGIN_PATH,
    UrllibOnesIdentityVerifier,
)
from app.shared.config import IdentitySettings, OnesIdentitySettings, Settings
from app.shared.exceptions import NonRetryableExecutionError, RetryableExecutionError
from backend.tests.helpers import (
    activate_dingtalk_test_application,
    grant_test_application_access,
    test_settings as base_test_settings,
)

ADMIN_PASSWORD = "111111111111"
ORIGIN = "http://admin.test"


class FakeOnesVerifier:
    available = True

    def __init__(self, user_uuid: str = "ONES-USER-001") -> None:
        self.user_uuid = user_uuid
        self.calls: list[dict[str, str]] = []

    def verify(self, *, email: str, password: str) -> VerifiedOnesIdentity:
        self.calls.append({"email": email, "password": password})
        if password == "wrong-password":
            raise NonRetryableExecutionError(
                "ONES credentials rejected",
                safe_message="ONES email or password is invalid",
                error_code="ones_invalid_credentials",
            )
        return VerifiedOnesIdentity.create(
            user_uuid=self.user_uuid,
            display_name="ONES Test User",
            team_uuids=("TEAM-002", "TEAM-001", "TEAM-002"),
        )


class FakeResponse:
    def __init__(self, payload: bytes, *, status: int = 200) -> None:
        self.payload = payload
        self.status = status

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self, limit: int = -1) -> bytes:
        return self.payload if limit < 0 else self.payload[:limit]


class FakeRejectionNotifier:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def notify(
        self,
        *,
        conversation_id: str,
        session_webhook: str,
        session_webhook_expires: str,
        sender_user_id: str,
        reason: str,
    ) -> bool:
        self.calls.append(
            {
                "conversation_id": conversation_id,
                "session_webhook": session_webhook,
                "session_webhook_expires": session_webhook_expires,
                "sender_user_id": sender_user_id,
                "reason": reason,
            }
        )
        return bool(session_webhook)


def identity_settings() -> Settings:
    return replace(
        base_test_settings(),
        environment="local",
        feature_business_application_control_plane=True,
        identity=IdentitySettings(
            enabled=True,
            web_admin_enabled=True,
            published_agent_runtime_enabled=True,
            test_identity_headers_enabled=False,
            cookie_secure=False,
            allowed_origins=(ORIGIN,),
        ),
        ones_identity=OnesIdentitySettings(
            instance_code="ones-test",
            display_name="ONES 测试实例",
        ),
    )


def identity_container(verifier: FakeOnesVerifier | None = None) -> Container:
    container = build_test_container(identity_settings(), migrate=True, seed=True)
    container.identity_service.ones_verifier = verifier or FakeOnesVerifier()
    activate_dingtalk_test_application(
        container,
        code="identity-test-application",
        robot_code="test-robot-code",
    )
    application = container.business_application_repository.get_by_code("identity-test-application")
    grant_test_application_access(
        container,
        application_id=str(application["id"]),
        role_code="identity-runtime-reader",
    )
    return container


def login(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200, response.text
    csrf = client.cookies.get("enterprise_agent_csrf")
    assert csrf
    return {"origin": ORIGIN, "x-csrf-token": csrf}


def create_user(
    client: TestClient,
    headers: dict[str, str],
    *,
    username: str,
    display_name: str,
) -> dict[str, Any]:
    response = client.post(
        "/api/admin/users",
        headers=headers,
        json={"username": username, "display_name": display_name},
    )
    assert response.status_code == 200, response.text
    return response.json()["user"]


def test_user_directory_search_pagination_and_safe_detail() -> None:
    container = identity_container()
    app = create_app(identity_settings(), container_factory=lambda _: container)
    with TestClient(app) as client:
        headers = login(client)
        first = create_user(
            client,
            headers,
            username="directory-a",
            display_name="Directory Alpha",
        )
        create_user(
            client,
            headers,
            username="directory-b",
            display_name="Directory Beta",
        )
        container.identity_repository.bind_external_identity(
            user_id=str(first["id"]),
            provider="ones",
            tenant_code="ones-test",
            external_subject_id="ONES-SEARCH-001",
            connector_id="",
            display_name="External Search Name",
            metadata={
                "verification_method": "ones_password_login",
                "team_uuids": ["TEAM-001"],
            },
        )

        search = client.get(
            "/api/admin/users",
            params={"search": "external search", "page": 1, "page_size": 1},
        )
        assert search.status_code == 200
        assert [item["id"] for item in search.json()["users"]] == [first["id"]]
        assert search.json()["pagination"] == {
            "page": 1,
            "page_size": 1,
            "total": 1,
            "total_pages": 1,
        }

        detail = client.get(
            f"/api/admin/users/{first['id']}/external-identities"
        )
        serialized = json.dumps(detail.json())
        assert detail.status_code == 200
        assert detail.json()["current"][0]["teams"] == [
            {"id": "TEAM-001", "name": ""}
        ]
        assert "identities" not in client.get(
            f"/api/admin/users/{first['id']}"
        ).json()
        for forbidden in ("password_hash", "token_hash", "csrf_hash"):
            assert forbidden not in serialized


def test_self_and_admin_identity_contracts_are_whitelisted_and_fail_closed() -> None:
    container = identity_container()
    user = container.identity_repository.create_user(
        username="identity-contract-user",
        display_name="Identity Contract User",
    )
    password = "identity-contract-password"
    container.identity_repository.set_password_hash(
        str(user["id"]),
        container.auth_service.passwords.hash(password),
    )
    service = container.external_credential_binding_service
    connection = service.connection_repository.create(
        code="ones-identity-contract-test",
        name="ONES Identity Contract Test",
        provider="ones",
        origin={
            "scheme": "https",
            "host": "ones-contract.example.test",
            "port": 443,
        },
        authentication={
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
        },
        actor_id="user_local_admin",
    )
    draft = connection["draft"]
    service.connection_repository.record_verification(
        str(connection["id"]),
        draft_revision=int(draft["draft_revision"]),
        draft_hash=str(draft["content_hash"]),
        actor_id="user_local_admin",
        status="PASSED",
        checks={"login": "passed"},
    )
    revision = service.connection_repository.publish(
        str(connection["id"]),
        draft_revision=int(draft["draft_revision"]),
        draft_hash=str(draft["content_hash"]),
        actor_id="user_local_admin",
    )
    secret_token = "ONES-CONTRACT-SECRET-TOKEN"
    encrypted = service.credential_cipher.encrypt(secret_token)
    challenge = service.credential_repository.create_challenge(
        user_id=str(user["id"]),
        connection_revision_id=str(revision["id"]),
        external_user_id="ONES-CONTRACT-USER",
        display_name="Contract ONES User",
        teams=[
            {"id": "TEAM-CONTRACT-A", "name": "Contract Team A"},
            {"id": "TEAM-CONTRACT-B", "name": "Contract Team B"},
        ],
        encrypted_token=encrypted,
        expires_at="2099-01-01T00:00:00+00:00",
    )
    credential = service.credential_repository.consume_challenge(
        str(challenge["id"]),
        user_id=str(user["id"]),
        connection_revision_id=str(revision["id"]),
        default_team_id="TEAM-CONTRACT-A",
        replace_existing=False,
    )
    service.credential_repository.record_usage_failure(
        credential_id=str(credential["id"]),
        error_code="contract_internal_error",
    )
    app = create_app(identity_settings(), container_factory=lambda _: container)

    with TestClient(app) as client:
        login(client)
        admin_overview = client.get(
            f"/api/admin/users/{user['id']}/external-identities"
        )
        admin_technical = client.get(
            f"/api/admin/users/{user['id']}/external-credentials/ones"
        )
        assert admin_overview.status_code == 200
        assert admin_technical.status_code == 200

        client.cookies.clear()
        authenticated = client.post(
            "/api/auth/login",
            json={"username": user["username"], "password": password},
        )
        assert authenticated.status_code == 200
        self_overview = client.get("/api/me/external-identities")
        assert self_overview.status_code == 200
        assert set(self_overview.json()) == {"user", "dingtalk", "ones"}
        assert set(self_overview.json()["ones"]) == {
            "provider",
            "user_name",
            "availability",
            "default_team",
            "verified_at",
            "last_success_at",
            "user_id",
            "teams",
        }
        assert self_overview.json()["ones"]["default_team"] == {
            "id": "TEAM-CONTRACT-A",
            "name": "Contract Team A",
        }

        denied_other = client.get(
            "/api/admin/users/user_local_admin/external-identities"
        )
        denied_observations = client.get(
            f"/api/admin/users/{user['id']}/external-identities"
        )
        denied_technical = client.get(
            f"/api/admin/users/{user['id']}/external-credentials/ones"
        )
        assert denied_other.status_code == 403
        assert denied_observations.status_code == 403
        assert denied_technical.status_code == 403

        serialized = json.dumps(
            {
                "self": self_overview.json(),
                "admin": admin_overview.json(),
                "technical": admin_technical.json(),
            },
            ensure_ascii=False,
        ).lower()
        assert secret_token.lower() not in serialized
        for forbidden in (
            "token_ciphertext",
            "encryption_key_id",
            "password",
            "authorization",
            "client_secret",
            "session_webhook",
            "challenge_id",
            "connector_id",
        ):
            assert forbidden not in serialized
        self_serialized = json.dumps(self_overview.json()).lower()
        for admin_only in (
            "identity_id",
            "identity_revision",
            "credential",
            "observations",
            "last_error_code",
            "last_attempt_at",
        ):
            assert admin_only not in self_serialized


def test_user_create_conflict_revision_and_session_revocation() -> None:
    container = identity_container()
    app = create_app(identity_settings(), container_factory=lambda _: container)
    with TestClient(app) as client:
        headers = login(client)
        user = create_user(
            client,
            headers,
            username="managed-user",
            display_name="Managed User",
        )
        duplicate = client.post(
            "/api/admin/users",
            headers=headers,
            json={"username": "managed-user", "display_name": "Duplicate"},
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["detail"]["code"] == "username_conflict"

        current = client.put(
            f"/api/admin/users/{user['id']}",
            headers=headers,
            json={
                "expected_revision": user["revision"],
                "display_name": "Managed User Updated",
                "email": "",
                "status": "enabled",
            },
        )
        assert current.status_code == 200
        stale = client.put(
            f"/api/admin/users/{user['id']}",
            headers=headers,
            json={
                "expected_revision": user["revision"],
                "display_name": "Stale",
                "email": "",
                "status": "disabled",
            },
        )
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "revision_conflict"


def test_provider_catalog_and_admin_ones_binding_requires_user_self_service() -> None:
    verifier = FakeOnesVerifier()
    container = identity_container(verifier)
    app = create_app(identity_settings(), container_factory=lambda _: container)
    secret_password = "ones-one-time-password"
    email = "ones.user@example.test"

    with TestClient(app) as client:
        headers = login(client)
        user = create_user(
            client,
            headers,
            username="ones-user",
            display_name="ONES User",
        )
        providers = client.get("/api/admin/external-identity-providers")
        assert providers.status_code == 200
        assert [item["code"] for item in providers.json()["providers"]] == [
            "dingtalk",
            "ones",
        ]
        assert providers.json()["providers"][1] == {
            "code": "ones",
            "display_name": "ONES 测试实例",
            "available": True,
            "instance_code": "ones-test",
        }

        bound = client.post(
            f"/api/admin/users/{user['id']}/ones-identities",
            headers=headers,
            json={
                "expected_user_revision": user["revision"],
                "email": email,
                "password": secret_password,
            },
        )
        assert bound.status_code == 409, bound.text
        assert bound.json()["detail"]["code"] == ("external_credential_self_service_required")
        assert verifier.calls == []

        raw = json.dumps(
            {
                "identities": container.database.execute(
                    "select * from user_external_identity where user_id = ?",
                    (user["id"],),
                ),
                "audit": container.database.execute(
                    "select * from audit_event order by created_at"
                ),
                "response": bound.json(),
            },
            ensure_ascii=False,
        )
        assert secret_password not in raw
        assert email not in raw
        assert "MOCK-ONES-TOKEN" not in raw

        repeated = client.post(
            f"/api/admin/users/{user['id']}/ones-identities",
            headers=headers,
            json={
                "expected_user_revision": user["revision"],
                "email": email,
                "password": secret_password,
            },
        )
        assert repeated.status_code == 409
        assert (
            container.database.execute_one(
                "select count(*) as count from user_external_identity where provider = 'ones'"
            )["count"]
            == 0
        )


def test_admin_ones_binding_fails_closed_before_using_untrusted_fields() -> None:
    verifier = FakeOnesVerifier()
    container = identity_container(verifier)
    app = create_app(identity_settings(), container_factory=lambda _: container)
    with TestClient(app) as client:
        headers = login(client)
        first = create_user(client, headers, username="ones-a", display_name="ONES A")
        second = create_user(client, headers, username="ones-b", display_name="ONES B")

        extra = client.post(
            f"/api/admin/users/{first['id']}/ones-identities",
            headers=headers,
            json={
                "expected_user_revision": first["revision"],
                "email": "ones@example.test",
                "password": "not-used",
                "user_uuid": "FORGED",
                "token": "FORGED-TOKEN",
                "url": "http://attacker.invalid",
            },
        )
        assert extra.status_code == 409
        assert extra.json()["detail"]["code"] == ("external_credential_self_service_required")
        assert verifier.calls == []

        invalid = client.post(
            f"/api/admin/users/{first['id']}/ones-identities",
            headers=headers,
            json={
                "expected_user_revision": first["revision"],
                "email": "ones@example.test",
                "password": "wrong-password",
            },
        )
        assert invalid.status_code == 409
        assert invalid.json()["detail"]["code"] == ("external_credential_self_service_required")
        assert (
            container.database.execute_one(
                "select count(*) as count from user_external_identity where provider = 'ones'"
            )["count"]
            == 0
        )

        first_bound = client.post(
            f"/api/admin/users/{first['id']}/ones-identities",
            headers=headers,
            json={
                "expected_user_revision": first["revision"],
                "email": "ones@example.test",
                "password": "valid-password",
            },
        )
        assert first_bound.status_code == 409
        conflict = client.post(
            f"/api/admin/users/{second['id']}/ones-identities",
            headers=headers,
            json={
                "expected_user_revision": second["revision"],
                "email": "ones@example.test",
                "password": "valid-password",
            },
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == ("external_credential_self_service_required")
        assert verifier.calls == []


def test_identity_lifecycle_is_optimistic_and_soft_unbinds() -> None:
    container = identity_container()
    app = create_app(identity_settings(), container_factory=lambda _: container)
    with TestClient(app) as client:
        headers = login(client)
        user = create_user(client, headers, username="lifecycle", display_name="Lifecycle")
        manual = client.post(
            f"/api/admin/users/{user['id']}/dingtalk-identities",
            headers=headers,
            json={
                "expected_user_revision": user["revision"],
                "tenant_code": "default",
                "external_subject_id": "lifecycle-dingtalk-user",
                "connector_id": "connector-dingtalk-stream-default",
                "display_name": "Lifecycle",
            },
        )
        assert manual.status_code == 404
        enterprise = container.database.execute_one(
            "select id from dingtalk_enterprise where corp_id = ?",
            ("corp-test-enterprise",),
        )
        assert enterprise is not None
        bound = container.identity_repository.bind_dingtalk_identity(
            user_id=str(user["id"]),
            dingtalk_enterprise_id=str(enterprise["id"]),
            external_subject_id="lifecycle-dingtalk-user",
            display_name="Lifecycle",
            source_connector_id="connector-dingtalk-stream-default",
            source_ingress_event_id="",
            observed_at="2026-08-03T00:00:00+00:00",
            replace_current=False,
        )

        disabled = client.put(
            f"/api/admin/identities/{bound['id']}/status",
            headers=headers,
            json={"expected_revision": bound["revision"], "status": "disabled"},
        )
        assert disabled.status_code == 200
        stale = client.put(
            f"/api/admin/identities/{bound['id']}/status",
            headers=headers,
            json={"expected_revision": bound["revision"], "status": "enabled"},
        )
        assert stale.status_code == 409

        identity = disabled.json()["identity"]
        unbound = client.delete(
            f"/api/admin/identities/{identity['id']}",
            headers=headers,
            params={"expected_revision": identity["revision"]},
        )
        assert unbound.status_code == 200
        assert unbound.json()["identity"]["status"] == "unbound"
        assert (
            container.database.execute_one(
                "select status from user_external_identity where id = ?",
                (identity["id"],),
            )["status"]
            == "unbound"
        )

        rebound = client.post(
            f"/api/admin/users/{user['id']}/dingtalk-identities",
            headers=headers,
            json={
                "expected_user_revision": user["revision"],
                "tenant_code": "default",
                "external_subject_id": "lifecycle-dingtalk-user",
                "connector_id": "connector-dingtalk-stream-default",
                "display_name": "Lifecycle",
            },
        )
        assert rebound.status_code == 404


def test_service_accounts_and_unsupported_providers_fail_closed() -> None:
    container = identity_container()
    service = container.identity_repository.create_user(
        username="svc-external",
        display_name="Service External",
        account_type="service",
    )
    with pytest.raises(NonRetryableExecutionError) as unsupported:
        container.identity_repository.bind_external_identity(
            user_id=str(service["id"]),
            provider="github",
            tenant_code="default",
            external_subject_id="subject",
            connector_id="",
        )
    assert unsupported.value.error_code == "identity_provider_unsupported"

    app = create_app(identity_settings(), container_factory=lambda _: container)
    with TestClient(app) as client:
        headers = login(client)
        rejected = client.post(
            f"/api/admin/users/{service['id']}/ones-identities",
            headers=headers,
            json={
                "expected_user_revision": service["revision"],
                "email": "service@example.test",
                "password": "valid-password",
            },
        )
        assert rejected.status_code == 409
        assert rejected.json()["detail"]["code"] == ("external_credential_self_service_required")
        assert (
            container.database.execute_one(
                "select count(*) as count from user_external_identity where user_id = ?",
                (service["id"],),
            )["count"]
            == 0
        )


def test_dingtalk_binding_state_controls_ingress_and_replies_with_safe_rejection() -> None:
    container = identity_container()
    notifier = FakeRejectionNotifier()
    container.dingtalk_stream_message_service.rejection_notifier = notifier

    def payload(suffix: str) -> dict[str, object]:
        return {
            "conversationId": f"conversation-{suffix}",
            "senderStaffId": "local-user",
            "senderCorpId": "corp-test-enterprise",
            "chatbotCorpId": "corp-test-enterprise",
            "msgId": f"message-{suffix}",
            "robotCode": "test-robot-code",
            "sessionWebhook": "https://oapi.dingtalk.com/robot/sendBySession",
            "sessionWebhookExpiredTime": "2099-01-01T00:00:00+00:00",
            "text": {"content": "check status"},
        }

    accepted = container.dingtalk_stream_message_service.handle_callback(
        payload=payload("enabled"),
        correlation_id="correlation-enabled",
    )
    assert accepted.accepted is True
    identity_row = container.identity_repository.get_external_identity("identity_local_dingtalk")

    disabled = container.identity_service.set_identity_status(
        actor_id="user_local_admin",
        identity_id=str(identity_row["id"]),
        status="disabled",
        expected_revision=int(identity_row["revision"]),
    )
    denied_disabled = container.dingtalk_stream_message_service.handle_callback(
        payload=payload("disabled"),
        correlation_id="correlation-disabled",
    )
    assert denied_disabled.accepted is False
    assert denied_disabled.status == "permission_denied"
    assert notifier.calls[-1]["reason"] == "你的钉钉身份已停用，请联系管理员"
    assert "https://oapi.dingtalk.com/robot/sendBySession" not in json.dumps(
        container.database.execute("select payload_summary from audit_event")
    )

    enabled = container.identity_service.set_identity_status(
        actor_id="user_local_admin",
        identity_id=str(disabled["id"]),
        status="enabled",
        expected_revision=int(disabled["revision"]),
    )
    user_row = container.identity_repository.get_user("user_local_admin")
    disabled_user = container.identity_repository.update_user(
        "user_local_admin",
        expected_revision=int(user_row["revision"]),
        display_name=str(user_row["display_name"]),
        email=str(user_row["email"]),
        status="disabled",
    )
    denied_user = container.dingtalk_stream_message_service.handle_callback(
        payload=payload("disabled-user"),
        correlation_id="correlation-disabled-user",
    )
    assert denied_user.accepted is False
    assert len(notifier.calls) == 2
    assert notifier.calls[-1]["reason"] == "你的平台账号已停用，请联系管理员"

    container.identity_repository.update_user(
        "user_local_admin",
        expected_revision=int(disabled_user["revision"]),
        display_name=str(disabled_user["display_name"]),
        email=str(disabled_user["email"]),
        status="enabled",
    )
    unbound = container.identity_service.unbind_identity(
        actor_id="user_local_admin",
        identity_id=str(enabled["id"]),
        expected_revision=int(enabled["revision"]),
    )
    assert unbound["status"] == "unbound"
    denied_unbound = container.dingtalk_stream_message_service.handle_callback(
        payload=payload("unbound"),
        correlation_id="correlation-unbound",
    )
    assert denied_unbound.accepted is False
    assert len(notifier.calls) == 3
    assert notifier.calls[-1]["reason"] == ("你的钉钉账号尚未绑定平台用户，请联系管理员完成绑定")

    jobs = container.database.execute(
        "select id from agent_job where external_event_id like 'message-%'"
    )
    assert len(jobs) == 1


def verifier_settings(**overrides: object) -> OnesIdentitySettings:
    values: dict[str, object] = {
        "instance_code": "ones-test",
        "display_name": "ONES",
        "base_url": "https://ones.example.test/ignored/path",
        "allowed_hosts": ("ones.example.test",),
        "timeout_seconds": 3,
        "max_response_bytes": 1024,
        "allow_insecure_local": False,
    }
    values.update(overrides)
    return OnesIdentitySettings(**values)  # type: ignore[arg-type]


def test_ones_verifier_uses_fixed_path_and_returns_only_whitelisted_identity() -> None:
    captured: dict[str, object] = {}

    def open_response(request: Request, timeout: float) -> FakeResponse:
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["request"] = json.loads((request.data or b"{}").decode())
        return FakeResponse(
            json.dumps(
                {
                    "user": {
                        "uuid": "ONES-VERIFIED",
                        "name": "Verified User",
                        "email": "response@example.test",
                        "token": "SECRET-UPSTREAM-TOKEN",
                    },
                    "teams": [
                        {"uuid": "TEAM-B"},
                        {"uuid": "TEAM-A"},
                        {"uuid": "TEAM-B"},
                    ],
                }
            ).encode()
        )

    verifier = UrllibOnesIdentityVerifier(
        verifier_settings(),
        environment="production",
        open_response=open_response,
    )
    identity = verifier.verify(
        email="login@example.test",
        password="one-time-password",
    )
    assert captured["url"] == f"https://ones.example.test{ONES_LOGIN_PATH}"
    assert captured["timeout"] == 3.0
    assert captured["request"] == {
        "email": "login@example.test",
        "password": "one-time-password",
    }
    assert identity.user_uuid == "ONES-VERIFIED"
    assert identity.display_name == "Verified User"
    assert identity.team_uuids == ("TEAM-B", "TEAM-A")
    assert "token" not in identity.__dict__
    assert "email" not in identity.__dict__


@pytest.mark.parametrize(
    ("open_response", "error_code"),
    [
        (
            lambda request, timeout: (_ for _ in ()).throw(
                HTTPError(request.full_url, 401, "unauthorized", None, None)
            ),
            "ones_invalid_credentials",
        ),
        (
            lambda request, timeout: (_ for _ in ()).throw(
                HTTPError(request.full_url, 302, "redirect", None, None)
            ),
            "ones_response_invalid",
        ),
        (
            lambda request, timeout: (_ for _ in ()).throw(URLError("connection unavailable")),
            "ones_connection_unavailable",
        ),
        (
            lambda request, timeout: FakeResponse(b"not-json"),
            "ones_response_invalid",
        ),
        (
            lambda request, timeout: FakeResponse(
                json.dumps({"user": {"name": "missing UUID"}, "teams": []}).encode()
            ),
            "ones_response_invalid",
        ),
    ],
)
def test_ones_verifier_maps_upstream_failures_without_response_bodies(
    open_response: Any,
    error_code: str,
) -> None:
    verifier = UrllibOnesIdentityVerifier(
        verifier_settings(),
        environment="production",
        open_response=open_response,
    )
    expected = (
        RetryableExecutionError
        if error_code == "ones_connection_unavailable"
        else NonRetryableExecutionError
    )
    with pytest.raises(expected) as raised:
        verifier.verify(email="user@example.test", password="secret")
    assert raised.value.error_code == error_code
    assert "secret" not in raised.value.safe_message


def test_ones_verifier_rejects_oversize_untrusted_host_and_production_http() -> None:
    oversized = UrllibOnesIdentityVerifier(
        verifier_settings(max_response_bytes=16),
        environment="production",
        open_response=lambda request, timeout: FakeResponse(b"x" * 17),
    )
    with pytest.raises(NonRetryableExecutionError) as too_large:
        oversized.verify(email="user@example.test", password="secret")
    assert too_large.value.error_code == "ones_response_invalid"

    with pytest.raises(NonRetryableExecutionError) as untrusted:
        UrllibOnesIdentityVerifier(
            verifier_settings(allowed_hosts=("other.example.test",)),
            environment="production",
        )
    assert untrusted.value.error_code == "ones_configuration_invalid"

    with pytest.raises(NonRetryableExecutionError) as insecure:
        UrllibOnesIdentityVerifier(
            verifier_settings(
                base_url="http://ones.example.test",
                allow_insecure_local=True,
            ),
            environment="production",
        )
    assert insecure.value.error_code == "ones_configuration_invalid"

    local = UrllibOnesIdentityVerifier(
        verifier_settings(
            base_url="http://ones.example.test",
            allow_insecure_local=True,
        ),
        environment="local",
        open_response=lambda request, timeout: FakeResponse(
            json.dumps({"user": {"uuid": "LOCAL", "name": "Local"}, "teams": []}).encode()
        ),
    )
    assert local.verify(email="local@example.test", password="secret").user_uuid == "LOCAL"


@pytest.mark.skipif(
    not os.getenv("ONES_MOCK_BASE_URL"),
    reason="Set ONES_MOCK_BASE_URL to run the live ONES Mock API flow",
)
def test_live_ones_mock_binding_failure_idempotency_and_conflict() -> None:
    base_url = os.environ["ONES_MOCK_BASE_URL"]
    hostname = urlparse(base_url).hostname
    assert hostname
    settings = replace(
        identity_settings(),
        ones_identity=OnesIdentitySettings(
            instance_code="ones-mock",
            display_name="ONES Mock",
            base_url=base_url,
            allowed_hosts=(hostname,),
            allow_insecure_local=True,
        ),
    )
    container = build_test_container(settings, migrate=True, seed=True)
    container.identity_service.ones_verifier = UrllibOnesIdentityVerifier(
        settings.ones_identity,
        environment=settings.environment,
    )
    app = create_app(settings, container_factory=lambda _: container)

    with TestClient(app) as client:
        headers = login(client)
        first = create_user(
            client,
            headers,
            username="live-ones-first",
            display_name="Live ONES First",
        )
        second = create_user(
            client,
            headers,
            username="live-ones-second",
            display_name="Live ONES Second",
        )
        request = {
            "expected_user_revision": first["revision"],
            "email": "mock.user@example.test",
            "password": "ones-mock-password-not-a-secret",
        }
        bound = client.post(
            f"/api/admin/users/{first['id']}/ones-identities",
            headers=headers,
            json=request,
        )
        assert bound.status_code == 200, bound.text
        identity_id = bound.json()["identity"]["id"]

        repeated = client.post(
            f"/api/admin/users/{first['id']}/ones-identities",
            headers=headers,
            json=request,
        )
        assert repeated.status_code == 200
        assert repeated.json()["identity"]["id"] == identity_id

        invalid = client.post(
            f"/api/admin/users/{second['id']}/ones-identities",
            headers=headers,
            json={
                "expected_user_revision": second["revision"],
                "email": "mock.user@example.test",
                "password": "wrong-password",
            },
        )
        assert invalid.status_code == 400
        assert invalid.json()["detail"]["code"] == "ones_invalid_credentials"
        assert container.identity_repository.list_external_identities(str(second["id"])) == []

        conflict = client.post(
            f"/api/admin/users/{second['id']}/ones-identities",
            headers=headers,
            json={
                "expected_user_revision": second["revision"],
                "email": "mock.user@example.test",
                "password": "ones-mock-password-not-a-secret",
            },
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "identity_conflict"
