from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.bootstrap import build_worker_container
from app.modules.internal_api_platform.app import create_app
from app.modules.internal_api_platform.domain.results import ToolResponse
from app.modules.internal_tools.infrastructure.internal_api_client import (
    HttpInternalApiClient,
    ToolRequestContext,
)
from app.shared.config import Settings
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import Migrator
from app.shared.service_token import ServiceTokenSet
import app.modules.internal_api_platform.app as internal_app_module
import app.shared.service_token as service_token_module


CURRENT_TOKEN = "internal-api-current-token-0000000001"
NEXT_TOKEN = "internal-api-next-token-000000000002"
WRONG_TOKEN = "internal-api-wrong-token-00000000003"


class StubPlatformService:
    def __init__(self) -> None:
        self.calls = 0
        self.closed = False

    def config_status(self) -> dict[str, Any]:
        return {
            "valid": True,
            "source": "test",
            "revision": 1,
            "config_hash": "test",
            "errors": [],
            "resource_count": 0,
        }

    def er_context(
        self,
        *,
        user_id: str,
        job_id: str,
        project_code: str,
        application_id: str,
        query: str,
        tool_call_id: str = "",
        correlation_id: str = "",
    ) -> ToolResponse:
        del tool_call_id, correlation_id
        self.calls += 1
        return ToolResponse(
            summary={
                "user_id": user_id,
                "job_id": job_id,
                "project_code": project_code,
                "application_id": application_id,
                "query": query,
            },
        )

    def close(self) -> None:
        self.closed = True

    def poll_secret_changes(self) -> bool:
        return False


class FakeResponse:
    def __init__(self) -> None:
        self.body = b'{"summary":{"ok":true}}'

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def _write_tokens(
    path: Path,
    *,
    current: str = CURRENT_TOKEN,
    next_token: str = "",
) -> None:
    path.write_text(
        json.dumps(
            {
                "current": current,
                **({"next": next_token} if next_token else {}),
            }
        ),
        encoding="utf-8",
    )


def _settings(path: Path, *, environment: str = "test") -> Settings:
    return Settings(
        environment=environment,
        internal_api_auth_token_file=str(path),
    )


def _tool_request(client: TestClient, token: str = ""):
    headers = {
        "x-agent-user-id": "user-1",
        "x-agent-job-id": "job-1",
    }
    if token:
        headers["authorization"] = f"Bearer {token}"
    return client.post(
        "/tools/context/er",
        json={"query": "order"},
        headers=headers,
    )


def test_internal_api_accepts_current_and_next_without_leaking_tokens(
    tmp_path: Path,
) -> None:
    token_path = tmp_path / "server-tokens.json"
    _write_tokens(token_path, next_token=NEXT_TOKEN)
    service = StubPlatformService()
    with TestClient(
        create_app(_settings(token_path), service=service)  # type: ignore[arg-type]
    ) as client:
        health = client.get("/health")
        missing = _tool_request(client)
        wrong = _tool_request(client, WRONG_TOKEN)
        current = _tool_request(client, CURRENT_TOKEN)
        next_response = _tool_request(client, NEXT_TOKEN)

    assert health.status_code == 200
    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert current.status_code == 200
    assert next_response.status_code == 200
    assert service.calls == 2
    serialized = json.dumps(
        {
            "missing": missing.json(),
            "wrong": wrong.json(),
            "repr": repr(
                ServiceTokenSet.from_file(str(token_path), required=True)
            ),
        }
    )
    assert CURRENT_TOKEN not in serialized
    assert NEXT_TOKEN not in serialized
    assert WRONG_TOKEN not in serialized


def test_rotation_completion_revokes_old_current_token(tmp_path: Path) -> None:
    token_path = tmp_path / "server-tokens.json"
    _write_tokens(token_path, next_token=NEXT_TOKEN)
    with TestClient(
        create_app(
            _settings(token_path),
            service=StubPlatformService(),  # type: ignore[arg-type]
        )
    ) as client:
        assert _tool_request(client, CURRENT_TOKEN).status_code == 200
        assert _tool_request(client, NEXT_TOKEN).status_code == 200

    _write_tokens(token_path, current=NEXT_TOKEN)
    with TestClient(
        create_app(
            _settings(token_path),
            service=StubPlatformService(),  # type: ignore[arg-type]
        )
    ) as client:
        assert _tool_request(client, CURRENT_TOKEN).status_code == 401
        assert _tool_request(client, NEXT_TOKEN).status_code == 200


def test_non_test_internal_api_startup_requires_token_file() -> None:
    with pytest.raises(RuntimeError, match="INTERNAL_API_AUTH_TOKEN_FILE"):
        create_app(
            Settings(environment="local", internal_api_auth_token_file=""),
            service=StubPlatformService(),  # type: ignore[arg-type]
        )


def test_internal_api_readiness_loads_master_key_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    master_key_path = tmp_path / "app-config-master-key"
    encoded = base64.urlsafe_b64encode(b"k" * 32).decode("ascii").rstrip("=")
    master_key_path.write_text(
        f"EA_MASTER_KEY_V1:{encoded}\n",
        encoding="ascii",
    )
    master_key_path.chmod(0o600)

    class ReadyDatabase:
        def __init__(self, _dsn: str) -> None:
            pass

        def ping(self) -> bool:
            return True

        def close(self) -> None:
            return None

    class CurrentSchema:
        def __init__(self, _database: object, _migrations_dir: Path) -> None:
            pass

        def require_current(self) -> str:
            return "023"

    monkeypatch.setattr(internal_app_module, "Database", ReadyDatabase)
    monkeypatch.setattr(
        internal_app_module,
        "SchemaHeadValidator",
        CurrentSchema,
    )
    app = create_app(
        Settings(
            environment="test",
            app_config_master_key_file=str(master_key_path),
        ),
        service=StubPlatformService(),  # type: ignore[arg-type]
    )

    response = TestClient(app).get("/ready")

    assert response.status_code == 200
    assert response.json()["core"]["master_key"] is True


def test_non_test_real_tool_worker_startup_requires_token_file(
    tmp_path: Path,
) -> None:
    database_dsn = f"sqlite:///{tmp_path / 'runtime.db'}"
    database = Database(database_dsn)
    try:
        Migrator(
            database,
            default_migrations_dir(),
            migrator_build="service-auth-test",
        ).run()
    finally:
        database.close()
    with pytest.raises(RuntimeError, match="INTERNAL_API_AUTH_TOKEN_FILE"):
        build_worker_container(
            Settings(
                database_dsn=database_dsn,
                environment="local",
                feature_real_internal_tools=True,
                internal_api_auth_token_file="",
            ),
            seed=True,
        )


def test_token_comparison_always_checks_current_and_next(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokens = ServiceTokenSet(current=CURRENT_TOKEN, next_token=NEXT_TOKEN)
    calls: list[tuple[bytes, bytes]] = []
    original = service_token_module.hmac.compare_digest

    def counting_compare(left: bytes, right: bytes) -> bool:
        calls.append((left, right))
        return original(left, right)

    monkeypatch.setattr(
        service_token_module.hmac,
        "compare_digest",
        counting_compare,
    )

    assert tokens.matches(CURRENT_TOKEN)
    assert len(calls) == 2
    calls.clear()
    assert not tokens.matches(WRONG_TOKEN)
    assert len(calls) == 2


def test_worker_client_loads_only_current_token_from_file(tmp_path: Path) -> None:
    token_path = tmp_path / "client-token.json"
    _write_tokens(token_path, next_token=NEXT_TOKEN)
    tokens = ServiceTokenSet.from_file(str(token_path), required=True)
    assert tokens is not None
    captured: dict[str, str] = {}

    def fake_urlopen(request: Any, timeout: int) -> FakeResponse:
        del timeout
        captured.update(dict(request.header_items()))
        return FakeResponse()

    client = HttpInternalApiClient(
        "http://internal.test",
        auth_token=tokens.outbound_token,
        urlopen_func=fake_urlopen,
    )
    client.get_er_context(
        "order",
        ToolRequestContext(
            job_id="job-1",
            user_id="user-1",
            project_code="default",
            correlation_id="correlation-1",
        ),
    )

    assert captured["Authorization"] == f"Bearer {CURRENT_TOKEN}"
    assert NEXT_TOKEN not in json.dumps(captured)


@pytest.mark.parametrize(
    "content",
    (
        "{}",
        '{"current":"short"}',
        '{"current":"internal-api-current-token-0000000001","unknown":"value"}',
        '{"current":"internal-api-current-token-0000000001",'
        '"next":"internal-api-current-token-0000000001"}',
    ),
)
def test_invalid_token_files_fail_without_echoing_content(
    tmp_path: Path,
    content: str,
) -> None:
    token_path = tmp_path / "invalid-token.json"
    token_path.write_text(content, encoding="utf-8")

    with pytest.raises(RuntimeError) as raised:
        ServiceTokenSet.from_file(str(token_path), required=True)

    assert CURRENT_TOKEN not in str(raised.value)
    assert NEXT_TOKEN not in str(raised.value)
