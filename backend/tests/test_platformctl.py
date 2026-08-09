from __future__ import annotations

import io
import json
import stat
from email.message import Message
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.cli import platformctl


def test_login_session_is_0600_and_does_not_persist_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_path = tmp_path / "session.json"
    client = platformctl.PlatformClient(session_path)
    headers = Message()
    headers.add_header("Set-Cookie", "enterprise_agent_session=session-value; HttpOnly; Path=/")
    headers.add_header("Set-Cookie", "enterprise_agent_csrf=csrf-value; Path=/")
    monkeypatch.setattr(
        client,
        "_raw_request",
        lambda *args, **kwargs: (
            200,
            headers,
            {"user": {"id": "admin-1", "username": "admin"}},
        ),
    )

    result = client.login(
        base_url="http://localhost:8000",
        username="admin",
        password="password-must-not-be-stored",
    )

    assert result["status"] == "logged_in"
    assert stat.S_IMODE(session_path.stat().st_mode) == 0o600
    persisted = session_path.read_text()
    assert "password-must-not-be-stored" not in persisted
    assert json.loads(persisted)["csrf"] == "csrf-value"


def test_session_with_group_permissions_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "session.json"
    path.write_text("{}")
    path.chmod(0o640)
    with pytest.raises(platformctl.PlatformCtlError, match="0600"):
        platformctl.PlatformClient(path)


def test_resource_manifest_is_validated_before_api_call(tmp_path: Path) -> None:
    manifest = tmp_path / "resource.yaml"
    manifest.write_text(
        """
api_version: enterprise-agent/v1
kind: DATABASE
metadata:
  code: mes_db
  name: MES
spec:
  provider: mysql
  host: mysql.internal
  port: 3306
  database: mes
  username: readonly
  password: plaintext-is-forbidden
  password_ref: secret://platform/mes_password
  allowed_tables: [work_order]
  max_rows: 100
  timeout_seconds: 5
"""
    )
    with pytest.raises(platformctl.PlatformCtlError, match="无效"):
        platformctl._manifest(manifest)


def test_secret_value_is_read_only_from_stdin_and_not_returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_value = "stdin-only-secret-value"

    class Stdin(io.StringIO):
        def isatty(self) -> bool:
            return False

    class FakeClient:
        def request(self, path, *, method="GET", body=None):
            assert body["value"] == secret_value
            return {"secret": {"code": "mes_password", "masked_summary": "***"}}

    monkeypatch.setattr(platformctl.sys, "stdin", Stdin(secret_value))
    args = SimpleNamespace(
        command="secret",
        secret_command="create",
        code="mes_password",
        purpose="MES readonly",
    )
    result = platformctl.execute(args, FakeClient())
    assert secret_value not in json.dumps(result)


def test_non_local_plain_http_login_is_rejected() -> None:
    with pytest.raises(platformctl.PlatformCtlError, match="HTTPS"):
        platformctl._validate_base_url("http://platform.internal")


def test_unpublish_uses_expected_revision_and_never_sends_a_manifest() -> None:
    calls: list[tuple[str, str, object]] = []

    class FakeClient:
        def request(self, path, *, method="GET", body=None):
            calls.append((path, method, body))
            return {"deployment": {"status": "DISABLED"}}

    args = SimpleNamespace(
        command="resource",
        resource_command="unpublish",
        code="mes_db",
        expected_revision=7,
    )
    assert platformctl.execute(args, FakeClient())["deployment"]["status"] == "DISABLED"
    assert calls == [
        ("/api/admin/mcp/resources/mes_db/unpublish", "POST", {"expected_revision": 7})
    ]


def test_api_errors_are_safe_and_do_not_echo_session_material(tmp_path: Path) -> None:
    path = tmp_path / "session.json"
    path.write_text(
        json.dumps(
            {
                "base_url": "http://localhost:8000",
                "cookies": {"session": "sensitive-session-token"},
                "csrf": "sensitive-csrf-token",
            }
        )
    )
    path.chmod(0o600)
    client = platformctl.PlatformClient(path)
    client._raw_request = lambda *args, **kwargs: (  # type: ignore[method-assign]
        403,
        Message(),
        {"detail": {"message": "无权执行此操作", "code": "permission_denied"}},
    )
    with pytest.raises(platformctl.PlatformCtlError) as raised:
        client.request("/api/admin/mcp/resources")
    message = str(raised.value)
    assert "permission_denied" in message or "无权" in message
    assert "sensitive-session-token" not in message
    assert "sensitive-csrf-token" not in message
