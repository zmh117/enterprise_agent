from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _dependencies(path: Path) -> tuple[str, ...]:
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    return tuple(payload["project"]["dependencies"])


def test_worker_and_mcp_server_major_versions_are_isolated() -> None:
    worker = _dependencies(ROOT / "pyproject.toml")
    ones = _dependencies(ROOT / "services/ones-mcp-server/pyproject.toml")
    data = _dependencies(ROOT / "services/data-mcp-server/pyproject.toml")
    assert "claude-agent-sdk==0.2.134" in worker
    assert "mcp>=1.23.0,<2.0.0" in worker
    assert "mcp==2.0.0" in ones
    assert "mcp==2.0.0" in data
    assert not any(item.startswith("claude-agent-sdk") for item in (*ones, *data))


def test_each_mcp_service_has_a_hash_locked_dependency_file_and_image() -> None:
    for service in ("ones-mcp-server", "data-mcp-server"):
        service_root = ROOT / "services" / service
        locked = (service_root / "requirements.lock").read_text(encoding="utf-8")
        assert "mcp==2.0.0" in locked
        assert "--hash=sha256:" in locked
        dockerfile = (service_root / "Dockerfile").read_text(encoding="utf-8")
        assert "--require-hashes" in dockerfile
        assert "USER 65532:65532" in dockerfile


def test_root_docker_context_includes_independent_mcp_service_sources() -> None:
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "!services/" in dockerignore
    assert "!services/**" in dockerignore
    assert "!config/" in dockerignore
    assert "!config/**" in dockerignore


def test_agent_worker_image_includes_mcp_runtime_dependencies() -> None:
    dockerfile = (ROOT / "backend/Dockerfile").read_text(encoding="utf-8")
    api_server = dockerfile.split("FROM python-deps AS api-server", 1)[1].split(
        "FROM python-deps AS dingtalk-stream-ingress", 1
    )[0]
    assert "COPY services/__init__.py /app/services/" in api_server
    assert "COPY services/mcp_common /app/services/mcp_common" in api_server
    assert "services/data_mcp_server/contracts.py" in api_server
    assert "services/ones_mcp_server/contracts.py" in api_server
    assert "COPY config /app/config" in api_server

    agent_worker = dockerfile.split("FROM claude-runtime AS agent-worker", 1)[1].split(
        "FROM claude-runtime AS backend-runtime", 1
    )[0]
    assert (
        "COPY backend/app/modules/mcp_runtime /app/backend/app/modules/mcp_runtime"
        in agent_worker
    )
    assert (
        "COPY backend/app/modules/mcp_resources /app/backend/app/modules/mcp_resources"
        in agent_worker
    )
    assert "COPY backend/app/modules/cutover /app/backend/app/modules/cutover" in agent_worker
    assert "COPY services/__init__.py /app/services/" in agent_worker
    assert "COPY services/mcp_common /app/services/mcp_common" in agent_worker


def test_retirement_manifest_is_explicitly_non_migrating() -> None:
    manifest = json.loads(
        (ROOT / "config/legacy-platform-retirement.json").read_text(encoding="utf-8")
    )
    assert manifest["policy"] == {
        "backup": False,
        "export": False,
        "transform": False,
        "legacy_read_compatibility": False,
        "data_rollback": False,
    }
    serialized = json.dumps(manifest, sort_keys=True)
    assert not re.search(r"backup_(path|reference)|export_path|archive_path", serialized)
