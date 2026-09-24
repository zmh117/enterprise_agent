"""小时同步可选 Compose 和默认关闭 CLI 合同；只用合成配置。"""

import json
import os
from pathlib import Path
import subprocess

import yaml

from backend.tests.test_knowledge_compose import compose_cli as compose_cli_fixture


compose_cli = compose_cli_fixture
ROOT = Path(__file__).resolve().parents[2]


def test_sync_overlay_is_separate_and_requires_two_explicit_gates():
    overlay = yaml.safe_load((ROOT / "knowledge/sync.compose.yml").read_text())
    assert set(overlay["services"]) == {"knowledge-sync"}
    assert not overlay.get("volumes") and not overlay.get("secrets")
    service = overlay["services"]["knowledge-sync"]
    assert service["profiles"] == ["knowledge-sync"]
    assert service["build"]["target"] == "ones-mcp"
    assert service["environment"]["KNOWLEDGE_SYNC_ENABLED"].endswith(":-false}")
    assert set(service["networks"]) == {"knowledge-internal", "provider-egress"}
    assert service["secrets"] == ["app_config_master_key"]
    assert service["read_only"] and service["cap_drop"] == ["ALL"]
    assert not service.get("ports")
    assert service["volumes"] == ["knowledge-qdrant:/qdrant/storage:ro"]


def test_sync_compose_render_is_opt_in_and_does_not_change_online_reader(compose_cli):
    env = {key: os.environ[key] for key in ("PATH", "HOME") if key in os.environ}
    env.update(
        DATABASE_DSN="postgresql://synthetic:synthetic@postgres:5432/synthetic",
        KNOWLEDGE_SYNC_DATABASE_DSN="postgresql://synthetic_writer:synthetic@postgres:5432/synthetic",
    )
    result = subprocess.run(
        [
            compose_cli,
            "compose",
            "--env-file",
            os.devnull,
            "-p",
            "knowledge-sync-contract",
            "-f",
            "docker-compose.yml",
            "-f",
            "knowledge/compose.yml",
            "-f",
            "knowledge/sync.compose.yml",
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
    assert result.returncode == 0, "synthetic Compose rendering failed (details withheld)"
    config = json.loads(result.stdout)
    assert "knowledge-sync" not in config["services"]
    result = subprocess.run(
        [
            compose_cli,
            "compose",
            "--env-file",
            os.devnull,
            "-p",
            "knowledge-sync-contract",
            "-f",
            "docker-compose.yml",
            "-f",
            "knowledge/compose.yml",
            "-f",
            "knowledge/sync.compose.yml",
            "--profile",
            "knowledge",
            "--profile",
            "knowledge-sync",
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
    assert result.returncode == 0, "synthetic Compose rendering failed (details withheld)"
    service = json.loads(result.stdout)["services"]["knowledge-sync"]
    assert service["environment"]["KNOWLEDGE_SYNC_ENABLED"] == "false"
    assert service["environment"]["DATABASE_DSN"].startswith("postgresql://synthetic_writer:")
    assert service["depends_on"]["migrator"]["condition"] == "service_completed_successfully"


def test_daemon_rejects_default_off_before_loading_database(monkeypatch, capsys):
    from app.cli import sync_ones_knowledge

    monkeypatch.delenv("KNOWLEDGE_SYNC_ENABLED", raising=False)
    monkeypatch.setattr(
        sync_ones_knowledge,
        "load_settings",
        lambda: (_ for _ in ()).throw(AssertionError("must not load settings")),
    )
    assert (
        sync_ones_knowledge.main(
            [
                "--mode",
                "daemon",
                "--binding-code",
                "synthetic",
                "--capacity-path",
                "/tmp",
                "--commit",
            ]
        )
        == 1
    )
    output = capsys.readouterr().out
    assert "knowledge_sync_worker_disabled" in output
    assert "synthetic_writer" not in output
