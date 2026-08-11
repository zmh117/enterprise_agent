#!/usr/bin/env python3
"""Read-only gates and destructive-operation manifest checks.

This script never mutates the repository, database, RabbitMQ, or runtime.
It also never converts a matching digest into authorization to apply.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Callable


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CHANGE_ROOT = REPOSITORY_ROOT / "openspec" / "changes" / "stabilize-platform-runtime-foundation"
TASKS_PATH = CHANGE_ROOT / "tasks.md"

TASK_PATTERN = re.compile(
    r"^- \[(?P<mark>[ xX])\] "
    r"(?P<number>\d+(?:\.\d+)?) "
    r"(?P<title>.+)$"
)

FORBIDDEN_MANIFEST_KEYS = {
    "authorization",
    "ciphertext",
    "config_json",
    "dsn",
    "nonce",
    "password",
    "password_value",
    "plaintext",
    "secret_value",
    "snapshot_json",
    "token",
    "token_value",
}


@dataclass(frozen=True)
class Task:
    number: str
    title: str
    complete: bool


@dataclass(frozen=True)
class Gate:
    number: int
    name: str
    selector: Callable[[str], bool]
    evidence_file: str


def _prefix(*prefixes: str) -> Callable[[str], bool]:
    return lambda number: any(number.startswith(prefix) for prefix in prefixes)


def _phase_three(number: str) -> bool:
    return number.startswith("6.") or (number.startswith("7.") and number not in {"7.5", "7.6"})


GATES = (
    Gate(1, "严格授权与信任边界", _prefix("2."), "gate-1-strict-runtime.md"),
    Gate(
        2,
        "Migrator、UoW 与双 Outbox",
        _prefix("3.", "4.", "5."),
        "gate-2-transactional-runtime.md",
    ),
    Gate(
        3,
        "Secret、资源版本与 Handler 治理",
        _phase_three,
        "gate-3-governed-resources.md",
    ),
    Gate(
        4,
        "Oracle、热加载与受控资源重置",
        lambda number: number in {"7.5", "7.6"} or number.startswith("8."),
        "gate-4-runtime-reset.md",
    ),
    Gate(
        5,
        "管理 API 与界面",
        _prefix("9.", "10."),
        "gate-5-management-ui.md",
    ),
    Gate(6, "完整验收", _prefix("11."), "gate-6-acceptance.md"),
)

PHASE_ONE_TEST_TARGETS = (
    ("backend/tests/test_webhook_api.py::test_public_webhook_returns_202_and_stable_safe_errors"),
    (
        "backend/tests/test_agent_job_debug_authorization.py"
        "::test_debug_create_requires_login_and_does_not_create_job"
    ),
    (
        "backend/tests/test_agent_job_debug_authorization.py"
        "::test_debug_create_uses_authenticated_internal_user"
    ),
    (
        "backend/tests/test_agent_job_debug_authorization.py"
        "::test_debug_create_requires_agent_debug_execute_capability"
    ),
    (
        "backend/tests/test_agent_job_debug_authorization.py"
        "::test_debug_create_rejects_authority_expanding_fields"
    ),
    (
        "backend/tests/test_mcp_tool_runtime.py"
        "::test_tool_mcp_bootstrap_resolves_published_resource_secret"
    ),
    ("backend/tests/test_mcp_tool_runtime.py::test_job_snapshot_fails_closed_on_schema_drift"),
    (
        "backend/tests/test_business_application_runtime_routing.py"
        "::test_session_policy_is_publication_scoped_and_publication_upgrade_splits_session"
    ),
    (
        "backend/tests/test_business_application_runtime_routing.py"
        "::test_session_key_modes_and_different_applications_are_isolated"
    ),
    (
        "backend/tests/test_business_application_runtime_routing.py"
        "::test_route_audit_is_correlated_hashed_and_never_contains_session_credentials"
    ),
    (
        "backend/tests/test_continuous_multimodal_conversations.py"
        "::test_direct_sessions_are_isolated_by_requester"
    ),
    (
        "backend/tests/test_continuous_multimodal_conversations.py"
        "::test_legacy_actor_session_remains_readable_but_cannot_accept_new_job"
    ),
    (
        "backend/tests/test_managed_multi_dingtalk_runtime.py"
        "::test_managed_channels_keep_secrets_out_of_admin_reads_and_runtime_states_are_independent"
    ),
    (
        "backend/tests/test_role_authorization_control_center.py"
        "::test_concurrent_platform_admin_removals_cannot_commit_below_two"
    ),
)

PHASE_TWO_A_TEST_TARGETS = (
    "backend/tests/test_schema_migration_runtime.py",
    "backend/tests/test_schema_migration_postgres_integration.py",
    "backend/tests/test_database_unit_of_work.py",
    "backend/tests/test_external_io_transaction_boundaries.py",
    "backend/tests/test_compose_migrator_gate.py",
)

PHASE_TWO_B_TEST_TARGETS = (
    "backend/tests/test_job_dispatch_atomic_creation.py",
    "backend/tests/test_job_dispatch_outbox_schema.py",
    "backend/tests/test_job_dispatch_outbox_dispatcher.py",
    "backend/tests/test_job_dispatch_operations.py",
    "backend/tests/test_job_dispatch_cutover.py",
    "backend/tests/test_job_dispatch_fault_integration.py",
    "backend/tests/test_agent_retry_and_failure_delivery.py",
    (
        "backend/tests/test_schema_migration_postgres_integration.py"
        "::test_postgres_job_dispatchers_use_skip_locked_without_duplicate_claims"
    ),
    "backend/tests/test_phase2b_postgres_rabbitmq_integration.py",
)

PHASE_TWO_C_TEST_TARGETS = (
    "backend/tests/test_delivery_outbox_schema.py",
    "backend/tests/test_delivery_outbox_atomic_terminal.py",
    "backend/tests/test_delivery_outbox_dispatcher.py",
    "backend/tests/test_delivery_outbox_chunk_idempotency.py",
    "backend/tests/test_delivery_operations.py",
    (
        "backend/tests/test_admin_api_contracts.py"
        "::test_operations_browser_is_bounded_read_only_and_secret_safe"
    ),
    (
        "backend/tests/test_schema_migration_postgres_integration.py"
        "::test_postgres_delivery_dispatchers_use_skip_locked_without_duplicate_sends"
    ),
    "backend/tests/test_phase2c_postgres_rabbitmq_integration.py",
)

PHASE_THREE_A_TEST_TARGETS = (
    "backend/tests/test_master_key_file.py",
    "backend/tests/test_platform_secret_security.py",
    "backend/tests/test_legacy_env_secret_import.py",
    "backend/tests/test_secret_change_reload.py",
    "backend/tests/test_master_key_runbook_contract.py",
    "backend/tests/test_phase3a_secret_leak_gate.py",
)

PHASE_THREE_B_TEST_TARGETS = (
    "backend/tests/test_governed_tool_resource_schema.py",
    "backend/tests/test_governed_tool_resource_lifecycle.py",
    "backend/tests/test_provider_contract_registry.py",
    "backend/tests/test_database_resource_verifier.py",
    "backend/tests/test_database_driver_boundaries.py",
    "backend/tests/test_oracle_image_contract.py",
    "backend/tests/test_mcp_tool_runtime.py",
    "backend/tests/test_retired_legacy_platform_contract.py",
)


def parse_tasks(text: str) -> list[Task]:
    tasks: list[Task] = []
    for line in text.splitlines():
        match = TASK_PATTERN.match(line)
        if not match:
            continue
        tasks.append(
            Task(
                number=match.group("number"),
                title=match.group("title"),
                complete=match.group("mark").lower() == "x",
            )
        )
    return tasks


def load_tasks(path: Path = TASKS_PATH) -> list[Task]:
    return parse_tasks(path.read_text(encoding="utf-8"))


def gate_report(tasks: list[Task], gate: Gate) -> dict[str, Any]:
    baseline = [task for task in tasks if task.number.startswith("1.")]
    selected = [task for task in tasks if gate.selector(task.number)]
    evidence_path = CHANGE_ROOT / "evidence" / gate.evidence_file
    incomplete_baseline = [task.number for task in baseline if not task.complete]
    incomplete_tasks = [task.number for task in selected if not task.complete]
    return {
        "gate": gate.number,
        "name": gate.name,
        "baseline_complete": bool(baseline) and not incomplete_baseline,
        "baseline_incomplete": incomplete_baseline,
        "task_count": len(selected),
        "complete_count": sum(task.complete for task in selected),
        "incomplete_tasks": incomplete_tasks,
        "evidence_file": str(evidence_path.relative_to(REPOSITORY_ROOT)),
        "evidence_exists": evidence_path.is_file(),
        "passed": (
            bool(baseline)
            and not incomplete_baseline
            and bool(selected)
            and not incomplete_tasks
            and evidence_path.is_file()
        ),
    }


def _canonicalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _canonicalize(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        normalized = [_canonicalize(item) for item in value]
        return sorted(
            normalized,
            key=lambda item: json.dumps(
                item,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
    return value


def _find_forbidden_keys(value: Any, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_path = f"{path}.{key}"
            if str(key).lower() in FORBIDDEN_MANIFEST_KEYS:
                findings.append(key_path)
            findings.extend(_find_forbidden_keys(item, key_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            findings.extend(_find_forbidden_keys(item, f"{path}[{index}]"))
    return findings


def validate_destructive_manifest(manifest: Any) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise ValueError("manifest 必须是 JSON object")

    required = {
        "operation_id",
        "generated_at",
        "database_fingerprint",
        "backup_reference",
        "targets",
        "impact",
    }
    missing = sorted(required.difference(manifest))
    if missing:
        raise ValueError(f"manifest 缺少字段: {', '.join(missing)}")

    forbidden = _find_forbidden_keys(manifest)
    if forbidden:
        raise ValueError("manifest 包含禁止的敏感字段: " + ", ".join(forbidden))

    targets = manifest["targets"]
    if not isinstance(targets, list) or not targets:
        raise ValueError("manifest.targets 必须是非空数组")

    seen: set[tuple[str, str]] = set()
    allowed_actions = {"DELETE", "INVALIDATE", "BLOCK"}
    for index, target in enumerate(targets):
        if not isinstance(target, dict):
            raise ValueError(f"targets[{index}] 必须是 object")
        target_missing = {
            "type",
            "id",
            "revision",
            "action",
        }.difference(target)
        if target_missing:
            raise ValueError(f"targets[{index}] 缺少字段: " + ", ".join(sorted(target_missing)))
        identity = (str(target["type"]), str(target["id"]))
        if identity in seen:
            raise ValueError(f"manifest 包含重复 target: {identity[0]}/{identity[1]}")
        seen.add(identity)
        if target["action"] not in allowed_actions:
            raise ValueError(f"targets[{index}].action 不允许: {target['action']}")

    if not isinstance(manifest["impact"], dict):
        raise ValueError("manifest.impact 必须是 object")
    return _canonicalize(manifest)


def manifest_digest(manifest: Any) -> tuple[str, bytes]:
    normalized = validate_destructive_manifest(manifest)
    canonical = json.dumps(
        normalized,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest(), canonical


def load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("manifest 必须是 JSON object")
    if "manifest" not in payload:
        return payload

    manifest = payload["manifest"]
    if not isinstance(manifest, dict):
        raise ValueError("manifest 包装对象中的 manifest 必须是 JSON object")
    embedded_digest = payload.get("digest")
    if embedded_digest is not None:
        actual_digest, _ = manifest_digest(manifest)
        if embedded_digest != actual_digest:
            raise ValueError("manifest 包装对象中的 digest 与清单不匹配")
    return manifest


def print_manifest_summary(manifest: dict[str, Any], digest: str) -> None:
    print(f"operation_id: {manifest['operation_id']}")
    print(f"generated_at: {manifest['generated_at']}")
    print(f"database_fingerprint: {manifest['database_fingerprint']}")
    print(f"backup_reference: {manifest['backup_reference']}")
    print(f"digest_sha256: {digest}")
    print(f"target_count: {len(manifest['targets'])}")
    for target in sorted(
        manifest["targets"],
        key=lambda item: (
            str(item["type"]),
            str(item["id"]),
            str(item["action"]),
        ),
    ):
        print(
            "target: "
            f"{target['action']} {target['type']}/{target['id']} "
            f"revision={target['revision']}"
        )
    print(
        "impact: "
        + json.dumps(
            manifest["impact"],
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def _gate_by_number(number: int) -> Gate:
    for gate in GATES:
        if gate.number == number:
            return gate
    raise ValueError(f"未知 Gate: {number}")


def _status_command(as_json: bool) -> int:
    tasks = load_tasks()
    reports = [gate_report(tasks, gate) for gate in GATES]
    if as_json:
        print(json.dumps(reports, ensure_ascii=False, indent=2))
    else:
        for report in reports:
            marker = "PASS" if report["passed"] else "BLOCKED"
            print(
                f"Gate {report['gate']} {marker}: {report['name']} "
                f"({report['complete_count']}/{report['task_count']})"
            )
            if report["baseline_incomplete"]:
                print("  baseline incomplete: " + ", ".join(report["baseline_incomplete"]))
            if report["incomplete_tasks"]:
                print("  tasks incomplete: " + ", ".join(report["incomplete_tasks"]))
            if not report["evidence_exists"]:
                print(f"  evidence missing: {report['evidence_file']}")
    return 0


def _check_command(gate_number: int, as_json: bool) -> int:
    report = gate_report(load_tasks(), _gate_by_number(gate_number))
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            f"Gate {report['gate']} {'PASS' if report['passed'] else 'BLOCKED'}: {report['name']}"
        )
        print(
            f"tasks: {report['complete_count']}/{report['task_count']}; "
            f"evidence: {'present' if report['evidence_exists'] else 'missing'}"
        )
        if report["baseline_incomplete"]:
            print("baseline incomplete: " + ", ".join(report["baseline_incomplete"]))
        if report["incomplete_tasks"]:
            print("tasks incomplete: " + ", ".join(report["incomplete_tasks"]))
    return 0 if report["passed"] else 1


def phase_one_test_command() -> list[str]:
    python = REPOSITORY_ROOT / ".venv" / "bin" / "python"
    if not python.is_file():
        raise ValueError("Phase 1 Gate 需要仓库 .venv/bin/python")
    return [
        str(python),
        "-m",
        "pytest",
        "-q",
        *PHASE_ONE_TEST_TARGETS,
    ]


def _verify_phase_one_command() -> int:
    print(
        "Phase 1 automated gate: invalid Token, RBAC, Debug identity, "
        "Session isolation, secret redaction"
    )
    result = subprocess.run(
        phase_one_test_command(),
        cwd=REPOSITORY_ROOT,
        check=False,
    )
    if result.returncode != 0:
        print("PHASE_1_AUTOMATED_GATE: FAIL")
        return int(result.returncode or 1)
    print("PHASE_1_AUTOMATED_GATE: PASS")
    return 0


def phase_two_a_test_command() -> list[str]:
    python = REPOSITORY_ROOT / ".venv" / "bin" / "python"
    if not python.is_file():
        raise ValueError("Phase 2A Gate 需要仓库 .venv/bin/python")
    if not os.getenv("MIGRATION_POSTGRES_DSN", "").strip():
        raise ValueError(
            "Phase 2A Gate 需要 MIGRATION_POSTGRES_DSN；真实 PostgreSQL 测试不得以 skip 代替"
        )
    return [
        str(python),
        "-m",
        "pytest",
        "-q",
        *PHASE_TWO_A_TEST_TARGETS,
    ]


def _verify_phase_two_a_command() -> int:
    print(
        "Phase 2A automated gate: one-shot Migrator, schema head, "
        "connection pool, Unit of Work, external I/O boundaries"
    )
    result = subprocess.run(
        phase_two_a_test_command(),
        cwd=REPOSITORY_ROOT,
        check=False,
    )
    if result.returncode != 0:
        print("PHASE_2A_AUTOMATED_GATE: FAIL")
        return int(result.returncode or 1)
    print("PHASE_2A_AUTOMATED_GATE: PASS")
    return 0


def phase_two_b_test_command() -> list[str]:
    python = REPOSITORY_ROOT / ".venv" / "bin" / "python"
    if not python.is_file():
        raise ValueError("Phase 2B Gate 需要仓库 .venv/bin/python")
    missing = [
        name
        for name in ("MIGRATION_POSTGRES_DSN", "RABBITMQ_TEST_URL")
        if not os.getenv(name, "").strip()
    ]
    if missing:
        raise ValueError(
            "Phase 2B Gate 需要 "
            + "、".join(missing)
            + "；真实 PostgreSQL/RabbitMQ 测试不得以 skip 代替"
        )
    return [
        str(python),
        "-m",
        "pytest",
        "-q",
        *PHASE_TWO_B_TEST_TARGETS,
    ]


def _verify_phase_two_b_command() -> int:
    print(
        "Phase 2B automated gate: atomic Job/Outbox commit, "
        "PostgreSQL SKIP LOCKED, RabbitMQ publisher confirm, "
        "consumer idempotency, finite retry/DEAD and bounded replay"
    )
    result = subprocess.run(
        phase_two_b_test_command(),
        cwd=REPOSITORY_ROOT,
        check=False,
    )
    if result.returncode != 0:
        print("PHASE_2B_AUTOMATED_GATE: FAIL")
        return int(result.returncode or 1)
    print("PHASE_2B_AUTOMATED_GATE: PASS")
    return 0


def phase_two_c_test_command() -> list[str]:
    python = REPOSITORY_ROOT / ".venv" / "bin" / "python"
    if not python.is_file():
        raise ValueError("Phase 2C Gate 需要仓库 .venv/bin/python")
    missing = [
        name
        for name in ("MIGRATION_POSTGRES_DSN", "RABBITMQ_TEST_URL")
        if not os.getenv(name, "").strip()
    ]
    if missing:
        raise ValueError(
            "Phase 2C Gate 需要 "
            + "、".join(missing)
            + "；真实 PostgreSQL/RabbitMQ 测试不得以 skip 代替"
        )
    return [
        str(python),
        "-m",
        "pytest",
        "-q",
        *PHASE_TWO_C_TEST_TARGETS,
    ]


def _verify_phase_two_c_command() -> int:
    print(
        "Phase 2C automated gate: atomic Delivery intent, independent "
        "Job/Delivery state, PostgreSQL SKIP LOCKED, chunk idempotency, "
        "RabbitMQ recovery, finite DEAD and frozen-intent replay"
    )
    result = subprocess.run(
        phase_two_c_test_command(),
        cwd=REPOSITORY_ROOT,
        check=False,
    )
    if result.returncode != 0:
        print("PHASE_2C_AUTOMATED_GATE: FAIL")
        return int(result.returncode or 1)
    print("PHASE_2C_AUTOMATED_GATE: PASS")
    return 0


def phase_three_a_test_command() -> list[str]:
    python = REPOSITORY_ROOT / ".venv" / "bin" / "python"
    if not python.is_file():
        raise ValueError("Phase 3A Gate 需要仓库 .venv/bin/python")
    return [
        str(python),
        "-m",
        "pytest",
        "-q",
        *PHASE_THREE_A_TEST_TARGETS,
    ]


def _verify_phase_three_a_command() -> int:
    print(
        "Phase 3A automated gate: external fixed Master Key, AAD-bound "
        "Secret versions, provider/import restrictions, metadata-only APIs, "
        "reload LKG and database/API/log/audit/Job/tool-call/frontend redaction"
    )
    result = subprocess.run(
        phase_three_a_test_command(),
        cwd=REPOSITORY_ROOT,
        check=False,
    )
    if result.returncode != 0:
        print("PHASE_3A_AUTOMATED_GATE: FAIL")
        return int(result.returncode or 1)
    print("PHASE_3A_AUTOMATED_GATE: PASS")
    return 0


def phase_three_b_test_command() -> list[str]:
    python = REPOSITORY_ROOT / ".venv" / "bin" / "python"
    if not python.is_file():
        raise ValueError("Phase 3B Gate 需要仓库 .venv/bin/python")
    return [
        str(python),
        "-m",
        "pytest",
        "-q",
        *PHASE_THREE_B_TEST_TARGETS,
    ]


def _verify_phase_three_b_command() -> int:
    print(
        "Phase 3B automated gate: canonical Provider contracts, "
        "secret:// resource versions, readonly probes, immutable "
        "application Handler bindings and Job Execution Scope"
    )
    result = subprocess.run(
        phase_three_b_test_command(),
        cwd=REPOSITORY_ROOT,
        check=False,
    )
    if result.returncode != 0:
        print("PHASE_3B_AUTOMATED_GATE: FAIL")
        return int(result.returncode or 1)
    print("PHASE_3B_AUTOMATED_GATE: PASS")
    return 0


def _digest_command(path: Path) -> int:
    manifest = load_manifest(path)
    digest, _ = manifest_digest(manifest)
    print_manifest_summary(manifest, digest)
    return 0


def _destructive_preflight_command(
    path: Path,
    expected_digest: str,
) -> int:
    manifest = load_manifest(path)
    actual_digest, _ = manifest_digest(manifest)
    print_manifest_summary(manifest, actual_digest)
    if not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
        print("DIGEST_INVALID: expected digest 必须是 64 位小写 SHA-256")
        return 2
    if actual_digest != expected_digest:
        print("DIGEST_MISMATCH: inventory 已变化，必须重新 report/prepare")
        return 2
    print(
        "USER_CONFIRMATION_REQUIRED: digest 匹配不等于获得 apply 授权；"
        "必须向用户重新展示以上精确影响并获得本次明确确认。"
    )
    return 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Runtime Foundation 只读 Gate 和破坏性操作清单检查"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="显示六阶段 Gate 状态")
    status.add_argument("--json", action="store_true")

    check = subparsers.add_parser("check", help="检查指定 Gate")
    check.add_argument("--gate", type=int, choices=range(1, 7), required=True)
    check.add_argument("--json", action="store_true")

    subparsers.add_parser(
        "verify-phase1",
        help="执行固定的 Phase 1 安全与隔离自动化回归",
    )
    subparsers.add_parser(
        "verify-phase2a",
        help="执行固定的 Phase 2A Migrator、UoW 与事务边界回归",
    )
    subparsers.add_parser(
        "verify-phase2b",
        help="执行固定的 Phase 2B Job Dispatch Outbox 自动化与真实链路回归",
    )
    subparsers.add_parser(
        "verify-phase2c",
        help="执行固定的 Phase 2C Delivery Outbox 自动化与真实链路回归",
    )
    subparsers.add_parser(
        "verify-phase3a",
        help="执行固定的 Phase 3A Master Key、Secret、LKG 与泄漏自动化回归",
    )
    subparsers.add_parser(
        "verify-phase3b",
        help="执行固定的 Phase 3B Resource、Provider、Handler 与 Execution Scope 回归",
    )

    digest = subparsers.add_parser(
        "manifest-digest",
        help="校验并展示破坏性操作 manifest/digest",
    )
    digest.add_argument("--manifest", type=Path, required=True)

    preflight = subparsers.add_parser(
        "destructive-preflight",
        help="重算 digest 并强制停在用户确认边界",
    )
    preflight.add_argument("--manifest", type=Path, required=True)
    preflight.add_argument("--expected-digest", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "status":
            return _status_command(args.json)
        if args.command == "check":
            return _check_command(args.gate, args.json)
        if args.command == "verify-phase1":
            return _verify_phase_one_command()
        if args.command == "verify-phase2a":
            return _verify_phase_two_a_command()
        if args.command == "verify-phase2b":
            return _verify_phase_two_b_command()
        if args.command == "verify-phase2c":
            return _verify_phase_two_c_command()
        if args.command == "verify-phase3a":
            return _verify_phase_three_a_command()
        if args.command == "verify-phase3b":
            return _verify_phase_three_b_command()
        if args.command == "manifest-digest":
            return _digest_command(args.manifest)
        if args.command == "destructive-preflight":
            return _destructive_preflight_command(
                args.manifest,
                args.expected_digest,
            )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
