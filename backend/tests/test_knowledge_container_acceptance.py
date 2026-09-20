"""Opt-in isolated production containers with synthetic ONES and Embedding HTTP."""

import base64
import json
import os
from pathlib import Path
import secrets
import subprocess
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from app.modules.identity.application.principal_jwt import PrincipalSigningKey

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "backend/tests/support/knowledge_container/compose.yml"


def test_isolated_knowledge_container_chain(tmp_path):
    if os.environ.get("KNOWLEDGE_CONTAINER_ACCEPTANCE") != "1":
        pytest.skip("explicit isolated container acceptance opt-in required")
    # No deployment environment, credentials, host ports, volumes or Docker socket mounts.
    env = {key: os.environ[key] for key in ("PATH", "HOME") if key in os.environ}
    env["KNOWLEDGE_ACCEPTANCE_STATE"] = str(tmp_path)
    project = "knowledge-acceptance-" + uuid.uuid4().hex[:12]
    command = ["docker", "compose", "--env-file", os.devnull, "-p", project, "-f", str(COMPOSE)]

    def compose(*args, timeout=120):
        result = subprocess.run(
            [*command, *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout
        )
        assert result.returncode == 0, (result.stdout + result.stderr)[-12000:]
        return result.stdout

    private = Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    files = {
        "private.pem": private.decode(),
        "jwks.json": json.dumps(PrincipalSigningKey.from_pem(private).public_jwks()),
        "master": "EA_MASTER_KEY_V1:"
        + base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("="),
        "provider-mode": "allow",
        **{
            name: secrets.token_urlsafe(48)
            for name in ("file-worker", "file-processing", "delivery", "knowledge")
        },
    }
    tmp_path.chmod(0o755)
    for name, value in files.items():
        path = tmp_path / name
        path.write_text(value)
        path.chmod(0o644 if name == "provider-mode" else 0o400 if name == "private.pem" else 0o444)
    try:
        config = json.loads(compose("config", "--format", "json"))
        assert config["networks"]["default"]["internal"]
        assert set(config["volumes"]) == {"synthetic-vectors"}
        assert config["volumes"]["synthetic-vectors"]["name"] == project + "_synthetic-vectors"
        assert all(not service.get("ports") for service in config["services"].values())
        compose("build", "api-server", "ones-mcp", "knowledge-mcp", timeout=900)
        compose("build", "driver", timeout=600)
        compose(
            "up",
            "-d",
            "--no-build",
            "--pull",
            "never",
            "postgres",
            "knowledge-qdrant",
            "ones-mock",
            "knowledge-embedding",
        )
        compose("run", "--rm", "--no-deps", "driver", "seed", timeout=240)
        compose(
            "run",
            "--rm",
            "--no-deps",
            "--entrypoint",
            "python",
            "-e",
            "KNOWLEDGE_DEADLINE_TEST_POSTGRES_DSN=postgresql://postgres@postgres:5432/knowledge_deadline_test",
            "driver",
            "-m",
            "pytest",
            "-q",
            "--tb=short",
            "backend/tests/test_knowledge_io_cancellation.py",
            "backend/tests/test_knowledge_deadline_postgres.py",
        )
        compose(
            "up", "-d", "--no-build", "--pull", "never", "api-server", "ones-mcp", "knowledge-mcp"
        )
        compose("run", "--rm", "--no-deps", "driver", "verify", timeout=240)
        compose("restart", "knowledge-mcp", "api-server", "ones-mcp", "knowledge-qdrant")
        compose("run", "--rm", "--no-deps", "driver", "restart", timeout=180)
        compose(
            "stop",
            "knowledge-mcp",
            "api-server",
            "ones-mcp",
            "knowledge-qdrant",
            "ones-mock",
            "knowledge-embedding",
        )
        compose("up", "-d", "--no-build", "--pull", "never", "api-without-knowledge")
        compose("run", "--rm", "--no-deps", "driver", "without", timeout=180)
    except AssertionError as exc:
        # Only this isolated, synthetic project; never collect deployment logs.
        logs = compose(
            "logs",
            "--no-color",
            "--tail",
            "25",
            "api-server",
            "ones-mcp",
            "knowledge-mcp",
            "api-without-knowledge",
        )
        raise AssertionError(str(exc) + "\n" + logs[-8000:]) from None
    finally:
        compose("down", "--volumes", "--timeout", "5", timeout=90)
        # Only generated test identity files; no business state or persistent volumes.
        for path in tmp_path.iterdir():
            if path.is_file():
                path.unlink()
