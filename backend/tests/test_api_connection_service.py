from __future__ import annotations

import json
from typing import Any

import pytest

from app.modules.api_capability.application import (
    ApiConnectionService,
    AuthenticationProfileV1,
    normalize_origin,
)
from app.modules.api_capability.infrastructure import (
    ApiConnectionRepository,
    RestrictedHttpJsonClient,
)
from app.shared.database import Database, default_migrations_dir
from app.shared.exceptions import (
    NonRetryableExecutionError,
    RetryableExecutionError,
)
from app.shared.migrations import Migrator


ACTOR_ID = "api-connection-admin"
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
            "token_path": "$.token",
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


class FakeSocket:
    def __init__(self) -> None:
        self.timeout = 0.0

    def settimeout(self, value: float) -> None:
        self.timeout = value


class FakeResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        payload: Any = None,
        raw: bytes | None = None,
        content_type: str = "application/json",
    ) -> None:
        self.status = status
        self._raw = (
            raw if raw is not None else json.dumps(payload if payload is not None else {}).encode()
        )
        self._content_type = content_type

    def read(self, maximum: int) -> bytes:
        return self._raw[:maximum]

    def getheader(self, name: str) -> str:
        return self._content_type if name.lower() == "content-type" else ""


class FakeConnection:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.sock = FakeSocket()
        self.requests: list[dict[str, Any]] = []
        self.closed = False

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None,
        headers: dict[str, str],
    ) -> None:
        self.requests.append(
            {
                "method": method,
                "path": path,
                "body": body,
                "headers": headers,
            }
        )

    def getresponse(self) -> FakeResponse:
        return self.response

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def database() -> Database:
    value = Database("sqlite:///:memory:")
    Migrator(
        value,
        default_migrations_dir(),
        migrator_build="api-connection-service-test",
    ).run()
    value.execute(
        """
        insert into app_user
          (id, username, display_name, status, created_at, updated_at)
        values (?, 'api-connection-admin', 'API Admin', 'enabled', ?, ?)
        """,
        (ACTOR_ID, NOW, NOW),
    )
    try:
        yield value
    finally:
        value.close()


def _service(
    database: Database,
    response: FakeResponse,
) -> tuple[ApiConnectionService, FakeConnection, RecordingAudit]:
    connection = FakeConnection(response)
    client = RestrictedHttpJsonClient(connection_factory=lambda *_: connection)
    audit = RecordingAudit()
    return (
        ApiConnectionService(
            ApiConnectionRepository(database),
            AllowAuthorization(),  # type: ignore[arg-type]
            audit,
            environment="test",
            http_client=client,
        ),
        connection,
        audit,
    )


def test_origin_allows_only_explicit_local_mock_http() -> None:
    local = normalize_origin(
        {
            "scheme": "http",
            "host": "127.0.0.1",
            "port": 18080,
            "allow_insecure_local_http": True,
        },
        environment="test",
    )
    assert local["host"] == "127.0.0.1"
    with pytest.raises(NonRetryableExecutionError):
        normalize_origin(
            {
                "scheme": "http",
                "host": "ones.example.test",
                "port": 80,
                "allow_insecure_local_http": True,
            },
            environment="test",
        )
    with pytest.raises(NonRetryableExecutionError):
        normalize_origin(
            {
                "scheme": "http",
                "host": "localhost",
                "port": 18080,
                "allow_insecure_local_http": True,
            },
            environment="production",
        )
    with pytest.raises(NonRetryableExecutionError):
        normalize_origin(
            {
                "scheme": "https",
                "host": "user@ones.example.test",
                "port": 443,
            },
            environment="production",
        )


def test_authentication_profile_fails_closed_and_extracts_typed_subject() -> None:
    invalid = _profile()
    invalid["unexpected"] = True
    with pytest.raises(NonRetryableExecutionError):
        AuthenticationProfileV1(invalid)

    response = FakeResponse(
        payload={
            "token": "token-in-memory",
            "user": {"uuid": "ones-user", "name": "ONES User"},
            "teams": [
                {"uuid": "team-a", "name": "A"},
                {"uuid": "team-b", "name": "B"},
            ],
        }
    )
    fake = FakeConnection(response)
    subject = AuthenticationProfileV1(_profile()).authenticate(
        client=RestrictedHttpJsonClient(connection_factory=lambda *_: fake),
        connection={
            "origin_scheme": "https",
            "origin_host": "ones.example.test",
            "origin_port": 443,
            "connect_timeout_ms": 3000,
            "read_timeout_ms": 10000,
            "max_response_bytes": 1024,
        },
        email="user@example.test",
        password="not-persisted",
    )
    assert subject.external_user_id == "ones-user"
    assert subject.teams[1]["id"] == "team-b"
    assert subject.authentication_header == (
        "Ones-Auth-Token",
        "token-in-memory",
    )
    request_body = json.loads(fake.requests[0]["body"])
    assert request_body["password"] == "not-persisted"


@pytest.mark.parametrize(
    ("response", "error_type", "error_code"),
    [
        (
            FakeResponse(status=302),
            NonRetryableExecutionError,
            "external_api_redirect_rejected",
        ),
        (
            FakeResponse(raw=b"not-json"),
            NonRetryableExecutionError,
            "external_api_json_invalid",
        ),
        (
            FakeResponse(payload={}, content_type="text/html"),
            NonRetryableExecutionError,
            "external_api_content_type_invalid",
        ),
        (
            FakeResponse(status=429),
            RetryableExecutionError,
            "external_api_retryable_status",
        ),
    ],
)
def test_restricted_http_client_classifies_unsafe_responses(
    response: FakeResponse,
    error_type: type[Exception],
    error_code: str,
) -> None:
    fake = FakeConnection(response)
    client = RestrictedHttpJsonClient(connection_factory=lambda *_: fake)
    with pytest.raises(error_type) as captured:
        client.request(
            connection={
                "origin_scheme": "https",
                "origin_host": "ones.example.test",
                "origin_port": 443,
                "connect_timeout_ms": 3000,
                "read_timeout_ms": 10000,
                "max_response_bytes": 1024,
            },
            method="GET",
            relative_path="/health",
        )
    assert getattr(captured.value, "error_code", "") == error_code
    assert fake.closed is True


def test_restricted_http_client_rejects_oversized_response() -> None:
    fake = FakeConnection(FakeResponse(raw=b"{" + b"x" * 2048 + b"}"))
    with pytest.raises(NonRetryableExecutionError) as captured:
        RestrictedHttpJsonClient(connection_factory=lambda *_: fake).request(
            connection={
                "origin_scheme": "https",
                "origin_host": "ones.example.test",
                "origin_port": 443,
                "connect_timeout_ms": 3000,
                "read_timeout_ms": 10000,
                "max_response_bytes": 1024,
            },
            method="GET",
            relative_path="/health",
        )
    assert captured.value.error_code == "external_api_response_too_large"


def test_connection_verify_publish_and_disable_exclude_password_and_token(
    database: Database,
) -> None:
    service, fake, audit = _service(
        database,
        FakeResponse(
            payload={
                "token": "ephemeral-token",
                "user": {"uuid": "ones-user", "name": "ONES User"},
                "teams": [{"uuid": "team-a", "name": "Team A"}],
            }
        ),
    )
    connection = service.create(
        actor_id=ACTOR_ID,
        code="ones-test",
        name="ONES Test",
        origin={
            "scheme": "https",
            "host": "ones.example.test",
            "port": 443,
        },
        authentication=_profile(),
    )
    draft = connection["draft"]
    verified = service.verify_bootstrap(
        str(connection["id"]),
        actor_id=ACTOR_ID,
        draft_revision=int(draft["draft_revision"]),
        draft_hash=str(draft["content_hash"]),
        email="admin@example.test",
        password="secret-password",
    )
    assert verified["subject"]["teams"][0]["id"] == "team-a"
    assert "token" not in json.dumps(verified).lower()
    revision = service.publish(
        str(connection["id"]),
        actor_id=ACTOR_ID,
        draft_revision=int(draft["draft_revision"]),
        draft_hash=str(draft["content_hash"]),
        correlation_id="connection-correlation-1",
    )
    disabled = service.set_revision_status(
        str(revision["id"]),
        actor_id=ACTOR_ID,
        status="DISABLED",
    )
    assert disabled["status"] == "DISABLED"
    assert disabled["authentication_status"] == "DISABLED"
    persisted = json.dumps(
        {
            "connection": service.get(
                str(connection["id"]),
                actor_id=ACTOR_ID,
            ),
            "audit": audit.events,
        }
    )
    assert "secret-password" not in persisted
    assert "ephemeral-token" not in persisted
    assert fake.requests[0]["path"] == "/project/api/project/auth/login"
    published_audit = next(
        item for item in audit.events if item["event_type"] == "api_connection.published"
    )
    assert published_audit["payload"]["correlation_id"] == ("connection-correlation-1")
    assert set(published_audit["payload"]) == {
        "actor_id",
        "connection_id",
        "revision",
        "content_hash",
        "result",
        "error_code",
        "correlation_id",
    }
