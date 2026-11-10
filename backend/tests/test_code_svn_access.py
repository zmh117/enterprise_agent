import json

import pytest

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.infrastructure.code_svn_access import (
    CodeSvnAccess,
    account,
    connection_url,
    connection_fingerprint,
)
from app.modules.knowledge.infrastructure.code_svn import SvnCodeSource
from backend.tests.test_code_resources import setup as setup_fixture, create

setup = setup_fixture


def test_connection_is_resource_owned_and_keeps_only_secret_reference(setup, monkeypatch):
    runtime, _, _, _, service, registry = setup
    resource = create(service)
    access = CodeSvnAccess(runtime.database, registry)
    result = access.create(
        resource_id=resource["id"],
        url="https://svn.invalid/real/trunk",
        username="synthetic-user",
        password="synthetic-password",
        actor_id="user_local_admin",
        platform_config=runtime.platform_config_service,
    )
    assert "password" not in json.dumps(result)
    entry = access.entry(result["id"], resource["id"])
    assert entry["secret_ref"].startswith("secret://platform/")
    assert "synthetic-password" not in json.dumps(entry)
    monkeypatch.setattr("app.shared.config.load_settings", lambda: runtime.settings)
    monkeypatch.setattr("app.shared.master_key.load_master_key_settings", lambda settings: settings)
    configs = []

    def client_factory(entry, auth_root, cancelled, *, credentials, config_directory):
        assert credentials == ("synthetic-user", "synthetic-password")
        assert list(config_directory.iterdir()) == []
        configs.append(config_directory)
        return object()

    with access.client(entry, registry.parent, lambda: False, factory=client_factory):
        assert configs[0].is_dir()
    assert not configs[0].exists()
    fingerprint = connection_fingerprint(entry)
    access.pin(
        result["id"],
        resource["id"],
        repository_uuid="00000000-0000-0000-0000-000000000001",
        branch_path="/trunk",
    )
    assert connection_fingerprint(access.entry(result["id"], resource["id"])) == fingerprint
    with pytest.raises(CodeKnowledgeError, match="CODE_REPOSITORY_CHANGED"):
        access.pin(result["id"], resource["id"], repository_uuid="different", branch_path="/trunk")
    with pytest.raises(CodeKnowledgeError, match="CODE_REGISTRATION_CHANGED"):
        access.entry(result["id"], "another-resource")


@pytest.mark.parametrize(
    "url",
    [
        "http://svn.invalid/trunk",
        "file:///private",
        "https://u:p@svn.invalid/trunk",
        "https://svn.invalid/trunk?q=x",
        "https://svn.invalid/\ntrunk",
    ],
)
def test_invalid_svn_url_does_not_reach_credentials(url):
    with pytest.raises(CodeKnowledgeError, match="CODE_SVN_URL_INVALID"):
        connection_url(url)


def test_password_is_piped_not_in_process_arguments_or_cache(tmp_path):
    script = tmp_path / "fake-svn"
    script.write_text("""#!/usr/bin/env python3
import sys
assert 'synthetic-password' not in sys.argv
assert '--no-auth-cache' in sys.argv
assert '--password-from-stdin' in sys.argv
assert sys.stdin.readline() == 'synthetic-password\\n'
print('verified')
""")
    script.chmod(0o700)
    source = SvnCodeSource(
        branch_url="https://svn.invalid/trunk",
        expected_uuid="test",
        branch_path="/trunk",
        config_directory=tmp_path,
        executable=str(script),
        credentials=("synthetic-user", "synthetic-password"),
    )
    assert source._run("info", []) == b"verified\n"
    assert not (tmp_path / "auth").exists()


@pytest.mark.parametrize(
    ("number", "expected"),
    [
        ("E215004", "CODE_SVN_AUTH_FAILED"),
        ("E230001", "CODE_SVN_CERTIFICATE_INVALID"),
        ("E170013", "CODE_SVN_CONNECTION_FAILED"),
    ],
)
def test_svn_errors_expose_codes_not_raw_stderr(tmp_path, number, expected):
    script = tmp_path / "fake-svn"
    script.write_text(
        f"#!/usr/bin/env python3\nimport sys\nprint('{number} private synthetic detail',file=sys.stderr)\nsys.exit(1)\n"
    )
    script.chmod(0o700)
    source = SvnCodeSource(
        branch_url="https://svn.invalid/trunk",
        expected_uuid="test",
        branch_path="/trunk",
        config_directory=tmp_path,
        executable=str(script),
    )
    with pytest.raises(CodeKnowledgeError, match=expected) as exc:
        source._run("info", [])
    assert "private" not in str(exc.value)


def test_multiline_password_is_rejected():
    with pytest.raises(CodeKnowledgeError, match="CODE_SVN_CREDENTIAL_INVALID"):
        account({"username": "synthetic", "password": "synthetic\npassword"})


def test_connection_api_requires_admin_session_and_never_echoes_credentials(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from backend.tests.test_unified_identity_rbac import unified_container, login, csrf_headers

    monkeypatch.setenv("CODE_CHECKOUT_ENABLED", "true")
    monkeypatch.setenv("CODE_CHECKOUT_REGISTRY_FILE", str(tmp_path / "absent.json"))
    runtime = unified_container()
    try:
        resource = create(runtime.knowledge_services.code_resources())
        url = f"/api/platform/knowledge/code/resources/{resource['id']}/connections"
        value = dict(
            url="https://svn.invalid/trunk",
            username="synthetic-account",
            password="synthetic-password",
        )
        with TestClient(
            create_app(runtime.settings, container_factory=lambda _: runtime)
        ) as client:
            assert client.post(url, json=value).status_code == 401
            headers = csrf_headers(login(client))
            result = client.post(url, headers=headers, json=value)
            assert result.status_code == 201, result.text
            assert set(result.json()) == {"id", "url", "authentication", "configured"}
            snapshot = client.get(url.removesuffix("connections") + "checkouts")
            assert snapshot.status_code == 200
            assert "synthetic-password" not in snapshot.text
            assert "synthetic-account" not in snapshot.text
    finally:
        runtime.database.close()
