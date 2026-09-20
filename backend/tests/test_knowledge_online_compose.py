"""Opt-in online wiring and minimum image imports, with no deployment secrets."""

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import pytest
import yaml

from backend.tests.test_knowledge_compose import compose_cli as compose_cli_fixture

compose_cli = compose_cli_fixture
ROOT = Path(__file__).resolve().parents[2]


def online_config(compose_cli, *, missing=None):
    env = {key: os.environ[key] for key in ("PATH", "HOME") if key in os.environ}
    env.update(
        DATABASE_DSN="postgresql://synthetic:synthetic@postgres:5432/synthetic",
        KNOWLEDGE_DATABASE_DSN="postgresql://knowledge_mcp_reader:synthetic@postgres:5432/synthetic",
        KNOWLEDGE_BOOTSTRAP_TOKEN_FILE="/synthetic/not-read-knowledge-bootstrap",
    )
    if missing:
        env.pop(missing)
    return subprocess.run(
        [
            compose_cli,
            "compose",
            "--env-file",
            os.devnull,
            "-p",
            "knowledge-online-contract",
            "-f",
            "docker-compose.yml",
            "-f",
            "knowledge/compose.yml",
            "-f",
            "knowledge/mcp.compose.yml",
            "--profile",
            "knowledge",
            "config",
            "--format",
            "json",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_online_overlay_only_changes_knowledge_mcp_and_bridge():
    overlay = yaml.safe_load((ROOT / "knowledge/mcp.compose.yml").read_text())
    assert set(overlay["services"]) == {"api-server", "knowledge-mcp"}
    assert set(overlay["secrets"]) == {"knowledge_bootstrap_token"}
    assert not overlay.get("volumes")
    assert overlay["networks"] == {"knowledge-storage-egress": {"driver": "bridge"}}
    api = overlay["services"]["api-server"]
    assert set(api) == {"environment", "secrets"}
    assert set(api["environment"]) == {"KNOWLEDGE_BOOTSTRAP_TOKEN_FILE"}
    assert api["secrets"] == ["knowledge_bootstrap_token"]
    assert (
        "knowledge-mcp"
        not in yaml.safe_load((ROOT / "knowledge/compose.yml").read_text())["services"]
    )


def test_online_render_preserves_internal_network_and_read_only_secret_boundary(compose_cli):
    result = online_config(compose_cli)
    assert result.returncode == 0, "synthetic Compose rendering failed (details withheld)"
    config = json.loads(result.stdout)
    service = config["services"]["knowledge-mcp"]
    assert service["profiles"] == ["knowledge"]
    assert service["build"]["target"] == "knowledge-mcp"
    assert not service.get("ports") and not service.get("volumes")
    assert service["read_only"] and service["cap_drop"] == ["ALL"]
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert {item["source"] for item in service["secrets"]} == {
        "principal_jwks",
        "knowledge_bootstrap_token",
    }
    assert set(service["environment"]) == {
        "DATABASE_DSN",
        "PRINCIPAL_JWKS_FILE",
        "KNOWLEDGE_BOOTSTRAP_TOKEN_FILE",
    }
    assert service["environment"]["DATABASE_DSN"].startswith("postgresql://knowledge_mcp_reader:")
    assert set(service["networks"]) == {
        "knowledge-internal",
        "agent-runtime-control",
        "knowledge-storage-egress",
    }
    assert all(
        config["networks"][name]["internal"]
        for name in ("knowledge-internal", "agent-runtime-control")
    )
    assert not config["networks"]["knowledge-storage-egress"].get("internal", False)
    assert "knowledge-storage-egress" not in config["services"]["knowledge-embedding"]["networks"]
    assert "api-server" not in service["depends_on"]  # Avoid API -> Runtime boot cycles.
    assert service["depends_on"]["migrator"]["condition"] == "service_completed_successfully"
    api = config["services"]["api-server"]
    assert "knowledge-internal" in api["networks"] and "agent-runtime-control" in api["networks"]
    assert "knowledge_bootstrap_token" in {item["source"] for item in api["secrets"]}
    for name in ("agent-worker", "python-agent-runtime", "ones-mcp"):
        assert "knowledge_bootstrap_token" not in {
            item["source"] for item in config["services"][name].get("secrets", [])
        }


@pytest.mark.parametrize("missing", ["KNOWLEDGE_DATABASE_DSN", "KNOWLEDGE_BOOTSTRAP_TOKEN_FILE"])
def test_online_requires_explicit_service_identity_and_reader_dsn(compose_cli, missing):
    result = online_config(compose_cli, missing=missing)
    assert result.returncode != 0 and "在线知识检索需要独立" in result.stderr


def test_mcp_image_copy_whitelist_imports_without_platform_bootstrap(tmp_path):
    dockerfile = (ROOT / "backend/Dockerfile").read_text()
    stage = dockerfile.split("FROM python-deps AS knowledge-mcp\n", 1)[1].split("\nFROM ", 1)[0]
    assert "USER 10008:10008" in stage
    assert 'CMD ["python", "-m", "services.knowledge_mcp_server.app"]' in stage
    for line in stage.splitlines():
        if not line.startswith("COPY "):
            continue
        _, source_name, target = shlex.split(line)
        source = ROOT / source_name
        destination = tmp_path / target.removeprefix("/app/")
        destination.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(
                source,
                destination,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("__pycache__"),
            )
        else:
            shutil.copy2(source, destination / source.name)
    assert not (tmp_path / "backend/app/bootstrap.py").exists()
    assert not (tmp_path / "services/ones_mcp_server").exists()
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import services.knowledge_mcp_server.bootstrap; import services.knowledge_mcp_server.app; import sys; assert 'app.bootstrap' not in sys.modules",
        ],
        cwd=tmp_path,
        env={"PYTHONPATH": f"{tmp_path / 'backend'}:{tmp_path}"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_bootstrap_secret_is_normalized_without_private_platform_credentials():
    entrypoint = (ROOT / "backend/docker/normalize_secrets_entrypoint.sh").read_text()
    assert "KNOWLEDGE_BOOTSTRAP_TOKEN_FILE" in entrypoint
    bootstrap = (ROOT / "services/knowledge_mcp_server/bootstrap.py").read_text()
    assert "assert_reader_role(database)" in bootstrap
    assert "retention_cleanup=False" in bootstrap
    assert "APP_CONFIG_MASTER_KEY" not in bootstrap
    assert "PRINCIPAL_PRIVATE_KEY_FILE" not in bootstrap
