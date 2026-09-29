"""小时同步可选 Compose 和默认关闭 CLI 合同；只用合成配置。"""

import base64
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
import yaml

from app.shared.config import Settings
from app.shared.master_key import MASTER_KEY_PREFIX
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


def _synthetic_file_key_settings(tmp_path: Path) -> tuple[Settings, str]:
    key = base64.urlsafe_b64encode(bytes(range(32))).decode("ascii").rstrip("=")
    path = tmp_path / "synthetic-master-key"
    path.write_text(f"{MASTER_KEY_PREFIX}{key}\n", encoding="ascii")
    path.chmod(0o400)
    return (
        Settings(
            database_dsn="postgresql://synthetic@postgres/synthetic",
            app_config_master_key_file=str(path),
            master_key_file_required=True,
            environment="local",
        ),
        key,
    )


class _FakeDatabase:
    engine = "postgres"

    def __init__(self, _dsn: str) -> None:
        pass

    def close(self) -> None:
        pass


def _stub_schema(monkeypatch: pytest.MonkeyPatch, module: object) -> None:
    monkeypatch.setattr(module, "Database", _FakeDatabase)
    monkeypatch.setattr(
        module,
        "SchemaHeadValidator",
        lambda _database, _migrations: SimpleNamespace(require_current=lambda: None),
    )


def test_collection_once_loads_file_key_before_resolving_platform_secret(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.cli import collect_ones_knowledge

    settings, key = _synthetic_file_key_settings(tmp_path)
    captured: dict[str, str] = {}
    monkeypatch.setattr(collect_ones_knowledge, "load_settings", lambda: settings)
    _stub_schema(monkeypatch, collect_ones_knowledge)
    monkeypatch.setattr(
        collect_ones_knowledge,
        "SyncRepository",
        lambda _database: SimpleNamespace(binding=lambda _binding_id: {"enabled": 1}),
    )
    monkeypatch.setattr(collect_ones_knowledge, "PlatformConfigRepository", lambda _db: object())

    def secret_provider(_repository: object, *, master_key: str) -> SimpleNamespace:
        captured["key"] = master_key
        return SimpleNamespace(resolve=lambda _ref: "synthetic")

    monkeypatch.setattr(collect_ones_knowledge, "EncryptedDbSecretProvider", secret_provider)
    monkeypatch.setattr(
        collect_ones_knowledge, "ManagedOnesCollectionProviderFactory", lambda *_a, **_k: object()
    )
    monkeypatch.setattr(
        collect_ones_knowledge,
        "KnowledgeOnesCollectionService",
        lambda _repo, _factory: SimpleNamespace(
            collect_once=lambda _binding_id: {"run_id": "synthetic-run"}
        ),
    )

    assert (
        collect_ones_knowledge.main(["--mode", "once", "--binding-code", "synthetic", "--commit"])
        == 0
    )
    assert captured["key"] == key
    assert key not in capsys.readouterr().out


@pytest.mark.parametrize("mode", ["once", "daemon"])
def test_full_sync_writer_passes_file_key_into_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    mode: str,
) -> None:
    from app.cli import sync_ones_knowledge

    settings, key = _synthetic_file_key_settings(tmp_path)
    captured: dict[str, str] = {}
    monkeypatch.setenv("KNOWLEDGE_SYNC_ENABLED", "true")
    monkeypatch.setattr(sync_ones_knowledge, "load_settings", lambda: settings)
    _stub_schema(monkeypatch, sync_ones_knowledge)
    monkeypatch.setattr(sync_ones_knowledge, "ManagedActivationRepository", lambda _db: object())

    def build_runtime(runtime_settings: Settings, *, seed: bool) -> SimpleNamespace:
        assert seed is False
        captured["key"] = runtime_settings.app_config_master_key
        return SimpleNamespace(database=_FakeDatabase("synthetic"), knowledge_services=None)

    monkeypatch.setattr(sync_ones_knowledge, "build_api_container", build_runtime)
    assert (
        sync_ones_knowledge.main(
            [
                "--mode",
                mode,
                "--binding-code",
                "synthetic",
                "--capacity-path",
                str(tmp_path),
                "--commit",
            ]
        )
        == 1
    )
    assert captured["key"] == key
    output = capsys.readouterr().out
    assert "knowledge_sync_verifier_unavailable" in output
    assert key not in output


@pytest.mark.parametrize("module_name", ["collect_ones_knowledge", "sync_ones_knowledge"])
def test_knowledge_status_does_not_require_master_key_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    module_name: str,
) -> None:
    from app.cli import collect_ones_knowledge, sync_ones_knowledge

    module = {
        "collect_ones_knowledge": collect_ones_knowledge,
        "sync_ones_knowledge": sync_ones_knowledge,
    }[module_name]
    settings = Settings(
        database_dsn="postgresql://synthetic@postgres/synthetic",
        app_config_master_key_file=str(tmp_path / "missing-master-key"),
        master_key_file_required=True,
    )
    monkeypatch.setattr(module, "load_settings", lambda: settings)
    _stub_schema(monkeypatch, module)
    binding = {"configuration_revision": 1, "enabled": 0, "interval_seconds": 3600}
    if module_name == "collect_ones_knowledge":
        monkeypatch.setattr(
            module,
            "SyncRepository",
            lambda _database: SimpleNamespace(
                binding=lambda _binding_id: binding,
                active_collection=lambda _binding_id: None,
            ),
        )
    else:
        monkeypatch.setattr(
            module,
            "ManagedActivationRepository",
            lambda _database: SimpleNamespace(
                binding=lambda _binding_id: {**binding, "next_run_at": None},
                active_run=lambda _binding_id: None,
            ),
        )

    assert module.main(["--mode", "status", "--binding-code", "synthetic"]) == 0
    assert "_status" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("module_name", "arguments", "error_code"),
    [
        (
            "collect_ones_knowledge",
            ["--mode", "once", "--binding-code", "synthetic", "--commit"],
            "knowledge_collection_master_key_unavailable",
        ),
        (
            "sync_ones_knowledge",
            [
                "--mode",
                "once",
                "--binding-code",
                "synthetic",
                "--capacity-path",
                "/tmp",
                "--commit",
            ],
            "knowledge_sync_master_key_unavailable",
        ),
    ],
)
def test_knowledge_writer_rejects_missing_file_key_before_database_access(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    module_name: str,
    arguments: list[str],
    error_code: str,
) -> None:
    from app.cli import collect_ones_knowledge, sync_ones_knowledge

    module = {
        "collect_ones_knowledge": collect_ones_knowledge,
        "sync_ones_knowledge": sync_ones_knowledge,
    }[module_name]
    settings = Settings(
        database_dsn="postgresql://synthetic@postgres/synthetic",
        app_config_master_key_file=str(tmp_path / "missing-master-key"),
        master_key_file_required=True,
        environment="local",
    )
    monkeypatch.setattr(module, "load_settings", lambda: settings)

    def database_must_not_open(_dsn: str) -> None:
        raise AssertionError("database must not open without a valid Master Key")

    monkeypatch.setattr(module, "Database", database_must_not_open)
    assert module.main(arguments) == 1
    output = capsys.readouterr().out
    assert error_code in output
    assert str(tmp_path) not in output
