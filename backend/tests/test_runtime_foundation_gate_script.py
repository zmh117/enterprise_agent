from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "runtime_foundation_gate.py"
SPEC = importlib.util.spec_from_file_location("runtime_foundation_gate", SCRIPT)
assert SPEC is not None
assert SPEC.loader is not None
gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gate
SPEC.loader.exec_module(gate)


def _manifest(targets: list[dict[str, object]]) -> dict[str, object]:
    return {
        "operation_id": "reset_123",
        "generated_at": "2026-07-28T00:00:00+00:00",
        "database_fingerprint": "a" * 64,
        "backup_reference": "backup/reset_123",
        "targets": targets,
        "impact": {
            "resource_count": len(targets),
            "applications": ["diagnostic"],
        },
    }


def test_parse_tasks_and_gate_report_keep_incomplete_tasks_visible() -> None:
    tasks = gate.parse_tasks(
        "\n".join(
            [
                "- [x] 1.1 baseline",
                "- [x] 1.2 baseline",
                "- [ ] 2.1 debug",
                "- [x] 2.2 query",
            ]
        )
    )

    assert [(task.number, task.complete) for task in tasks] == [
        ("1.1", True),
        ("1.2", True),
        ("2.1", False),
        ("2.2", True),
    ]
    report = gate.gate_report(tasks, gate.GATES[0])
    assert report["incomplete_tasks"] == ["2.1"]
    assert report["passed"] is False


def test_phase_one_gate_has_fixed_security_and_isolation_targets(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    command = gate.phase_one_test_command()
    serialized = " ".join(command)
    assert command[:4] == [
        str(ROOT / ".venv" / "bin" / "python"),
        "-m",
        "pytest",
        "-q",
    ]
    assert "test_webhook_api.py" in serialized
    assert "test_agent_job_debug_authorization.py" in serialized
    assert "test_internal_api_service_auth.py" in serialized
    assert "test_internal_api_job_fact_authorization.py" in serialized
    assert "test_business_application_runtime_routing.py" in serialized
    assert "test_continuous_multimodal_conversations.py" in serialized
    assert "test_managed_multi_dingtalk_runtime.py" in serialized
    assert "test_role_authorization_control_center.py" in serialized

    calls: list[tuple[list[str], Path, bool]] = []

    def fake_run(
        args: list[str],
        *,
        cwd: Path,
        check: bool,
    ) -> SimpleNamespace:
        calls.append((args, cwd, check))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(gate.subprocess, "run", fake_run)
    assert gate._verify_phase_one_command() == 0
    assert calls == [(command, ROOT, False)]
    assert "PHASE_1_AUTOMATED_GATE: PASS" in capsys.readouterr().out


def test_phase_two_a_gate_requires_postgres_and_has_fixed_targets(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("MIGRATION_POSTGRES_DSN", raising=False)
    with pytest.raises(ValueError, match="真实 PostgreSQL 测试不得以 skip 代替"):
        gate.phase_two_a_test_command()

    monkeypatch.setenv(
        "MIGRATION_POSTGRES_DSN",
        "postgresql://integration.invalid/postgres",
    )
    command = gate.phase_two_a_test_command()
    serialized = " ".join(command)
    assert command[:4] == [
        str(ROOT / ".venv" / "bin" / "python"),
        "-m",
        "pytest",
        "-q",
    ]
    assert "test_schema_migration_runtime.py" in serialized
    assert "test_schema_migration_postgres_integration.py" in serialized
    assert "test_database_unit_of_work.py" in serialized
    assert "test_external_io_transaction_boundaries.py" in serialized
    assert "test_compose_migrator_gate.py" in serialized

    calls: list[tuple[list[str], Path, bool]] = []

    def fake_run(
        args: list[str],
        *,
        cwd: Path,
        check: bool,
    ) -> SimpleNamespace:
        calls.append((args, cwd, check))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(gate.subprocess, "run", fake_run)
    assert gate._verify_phase_two_a_command() == 0
    assert calls == [(command, ROOT, False)]
    assert "PHASE_2A_AUTOMATED_GATE: PASS" in capsys.readouterr().out


def test_phase_two_b_gate_requires_real_dependencies_and_has_fixed_targets(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("MIGRATION_POSTGRES_DSN", raising=False)
    monkeypatch.delenv("RABBITMQ_TEST_URL", raising=False)
    with pytest.raises(ValueError, match="不得以 skip 代替"):
        gate.phase_two_b_test_command()

    monkeypatch.setenv(
        "MIGRATION_POSTGRES_DSN",
        "postgresql://integration.invalid/postgres",
    )
    monkeypatch.setenv(
        "RABBITMQ_TEST_URL",
        "amqp://integration.invalid/",
    )
    command = gate.phase_two_b_test_command()
    serialized = " ".join(command)
    assert command[:4] == [
        str(ROOT / ".venv" / "bin" / "python"),
        "-m",
        "pytest",
        "-q",
    ]
    assert "test_job_dispatch_atomic_creation.py" in serialized
    assert "test_job_dispatch_outbox_dispatcher.py" in serialized
    assert "test_job_dispatch_operations.py" in serialized
    assert "test_job_dispatch_cutover.py" in serialized
    assert "test_job_dispatch_fault_integration.py" in serialized
    assert "test_agent_retry_and_failure_delivery.py" in serialized
    assert "test_schema_migration_postgres_integration.py" in serialized
    assert "test_phase2b_postgres_rabbitmq_integration.py" in serialized

    calls: list[tuple[list[str], Path, bool]] = []

    def fake_run(
        args: list[str],
        *,
        cwd: Path,
        check: bool,
    ) -> SimpleNamespace:
        calls.append((args, cwd, check))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(gate.subprocess, "run", fake_run)
    assert gate._verify_phase_two_b_command() == 0
    assert calls == [(command, ROOT, False)]
    assert "PHASE_2B_AUTOMATED_GATE: PASS" in capsys.readouterr().out


def test_phase_two_c_gate_requires_real_dependencies_and_has_fixed_targets(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("MIGRATION_POSTGRES_DSN", raising=False)
    monkeypatch.delenv("RABBITMQ_TEST_URL", raising=False)
    with pytest.raises(ValueError, match="不得以 skip 代替"):
        gate.phase_two_c_test_command()

    monkeypatch.setenv(
        "MIGRATION_POSTGRES_DSN",
        "postgresql://integration.invalid/postgres",
    )
    monkeypatch.setenv(
        "RABBITMQ_TEST_URL",
        "amqp://integration.invalid/",
    )
    command = gate.phase_two_c_test_command()
    serialized = " ".join(command)
    assert command[:4] == [
        str(ROOT / ".venv" / "bin" / "python"),
        "-m",
        "pytest",
        "-q",
    ]
    assert "test_delivery_outbox_schema.py" in serialized
    assert "test_delivery_outbox_atomic_terminal.py" in serialized
    assert "test_delivery_outbox_dispatcher.py" in serialized
    assert "test_delivery_outbox_chunk_idempotency.py" in serialized
    assert "test_delivery_operations.py" in serialized
    assert "test_admin_api_contracts.py" in serialized
    assert "test_schema_migration_postgres_integration.py" in serialized
    assert "test_phase2c_postgres_rabbitmq_integration.py" in serialized

    calls: list[tuple[list[str], Path, bool]] = []

    def fake_run(
        args: list[str],
        *,
        cwd: Path,
        check: bool,
    ) -> SimpleNamespace:
        calls.append((args, cwd, check))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(gate.subprocess, "run", fake_run)
    assert gate._verify_phase_two_c_command() == 0
    assert calls == [(command, ROOT, False)]
    assert "PHASE_2C_AUTOMATED_GATE: PASS" in capsys.readouterr().out


def test_phase_three_a_gate_has_fixed_secret_and_leak_targets(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    command = gate.phase_three_a_test_command()
    serialized = " ".join(command)
    assert command[:4] == [
        str(ROOT / ".venv" / "bin" / "python"),
        "-m",
        "pytest",
        "-q",
    ]
    assert "test_master_key_file.py" in serialized
    assert "test_platform_secret_security.py" in serialized
    assert "test_legacy_env_secret_import.py" in serialized
    assert "test_secret_change_reload.py" in serialized
    assert "test_master_key_runbook_contract.py" in serialized
    assert "test_phase3a_secret_leak_gate.py" in serialized

    calls: list[tuple[list[str], Path, bool]] = []

    def fake_run(
        args: list[str],
        *,
        cwd: Path,
        check: bool,
    ) -> SimpleNamespace:
        calls.append((args, cwd, check))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(gate.subprocess, "run", fake_run)
    assert gate._verify_phase_three_a_command() == 0
    assert calls == [(command, ROOT, False)]
    assert "PHASE_3A_AUTOMATED_GATE: PASS" in capsys.readouterr().out


def test_phase_three_b_gate_has_fixed_resource_and_handler_targets(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    command = gate.phase_three_b_test_command()
    serialized = " ".join(command)
    assert command[:4] == [
        str(ROOT / ".venv" / "bin" / "python"),
        "-m",
        "pytest",
        "-q",
    ]
    for target in (
        "test_governed_tool_resource_schema.py",
        "test_governed_tool_resource_lifecycle.py",
        "test_provider_contract_registry.py",
        "test_database_resource_verifier.py",
        "test_database_driver_boundaries.py",
        "test_oracle_image_contract.py",
        "test_handler_registry_governance.py",
        "test_handler_execution_resolution.py",
        "test_governed_job_execution_scope.py",
        "test_internal_api_job_fact_authorization.py",
    ):
        assert target in serialized

    calls: list[tuple[list[str], Path, bool]] = []

    def fake_run(
        args: list[str],
        *,
        cwd: Path,
        check: bool,
    ) -> SimpleNamespace:
        calls.append((args, cwd, check))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(gate.subprocess, "run", fake_run)
    assert gate._verify_phase_three_b_command() == 0
    assert calls == [(command, ROOT, False)]
    assert "PHASE_3B_AUTOMATED_GATE: PASS" in capsys.readouterr().out


def test_manifest_digest_is_independent_of_target_order() -> None:
    first = {
        "type": "resource",
        "id": "resource_a",
        "revision": 3,
        "action": "DELETE",
    }
    second = {
        "type": "application",
        "id": "application_b",
        "revision": 2,
        "action": "BLOCK",
    }

    digest_a, _ = gate.manifest_digest(_manifest([first, second]))
    digest_b, _ = gate.manifest_digest(_manifest([second, first]))

    assert digest_a == digest_b


def test_manifest_rejects_sensitive_fields() -> None:
    manifest = _manifest(
        [
            {
                "type": "resource",
                "id": "resource_a",
                "revision": 3,
                "action": "DELETE",
                "password": "must-not-be-here",
            }
        ]
    )

    with pytest.raises(ValueError, match="禁止的敏感字段"):
        gate.manifest_digest(manifest)


def test_manifest_rejects_duplicate_targets() -> None:
    target = {
        "type": "resource",
        "id": "resource_a",
        "revision": 3,
        "action": "DELETE",
    }

    with pytest.raises(ValueError, match="重复 target"):
        gate.manifest_digest(_manifest([target, dict(target)]))


def test_load_manifest_accepts_resource_reset_cli_wrapper(
    tmp_path: Path,
) -> None:
    manifest = _manifest(
        [
            {
                "type": "resource",
                "id": "resource_a",
                "revision": 3,
                "action": "DELETE",
            }
        ]
    )
    digest, _ = gate.manifest_digest(manifest)
    path = tmp_path / "resource-reset-prepare.json"
    path.write_text(
        json.dumps({"digest": digest, "manifest": manifest}),
        encoding="utf-8",
    )

    assert gate.load_manifest(path) == manifest


def test_load_manifest_rejects_cli_wrapper_digest_mismatch(
    tmp_path: Path,
) -> None:
    manifest = _manifest(
        [
            {
                "type": "resource",
                "id": "resource_a",
                "revision": 3,
                "action": "DELETE",
            }
        ]
    )
    path = tmp_path / "resource-reset-prepare.json"
    path.write_text(
        json.dumps({"digest": "0" * 64, "manifest": manifest}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="digest 与清单不匹配"):
        gate.load_manifest(path)
