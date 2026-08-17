from __future__ import annotations

import argparse
import json
import os
import subprocess
from collections.abc import Mapping, Sequence

from app.bootstrap import build_api_container
from app.modules.agent.application.typescript_runtime_retirement import (
    TypeScriptRuntimeRetirementPreflight,
)
from app.modules.message_bus.infrastructure.rabbitmq_topology import (
    inspect_agent_job_topology_read_only,
)
from app.shared.config import Settings, load_settings
from app.shared.database import Database, default_migrations_dir
from app.shared.exceptions import NonRetryableExecutionError
from app.shared.migrations import SchemaHeadValidator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only, redacted preflight for retiring TypeScript Agent Runtime"
    )
    parser.add_argument(
        "action",
        nargs="?",
        choices=("preflight", "migrate"),
        default="preflight",
    )
    parser.add_argument("--target-environment", required=True)
    parser.add_argument(
        "--expected-environment",
        action="append",
        default=[],
        help="Repeat for every deployment environment whose evidence is required",
    )
    parser.add_argument("--source-application-publication-id", default="")
    parser.add_argument("--source-agent-publication-id", default="")
    parser.add_argument("--target-python-agent-publication-id", default="")
    parser.add_argument("--expected-application-revision", type=int, default=-1)
    parser.add_argument("--expected-deployment-revision", type=int, default=-1)
    parser.add_argument("--actor-id", default="")
    parser.add_argument("--correlation-id", default="")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the exact migration; omitted means transactional dry-run",
    )
    parser.add_argument(
        "--confirm-target",
        default="",
        help="Required with --apply and must exactly match --target-environment",
    )
    return parser


def collect_checkout() -> dict[str, object]:
    try:
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return {"verified": False, "branch": "unknown", "commit": "unknown"}
    return {"verified": bool(branch and commit), "branch": branch, "commit": commit}


def build_report(
    *,
    settings: Settings,
    target_environment: str,
    expected_environments: Sequence[str],
    checkout: Mapping[str, object],
    environ: Mapping[str, str],
) -> dict[str, object]:
    database = Database(settings.database_dsn)
    try:
        return TypeScriptRuntimeRetirementPreflight(
            database=database,
            queue_inspector=lambda: inspect_agent_job_topology_read_only(
                settings.rabbitmq_url,
                settings.queue,
            ),
            target_environment=target_environment,
            observed_environment=settings.environment,
            expected_environments=expected_environments,
            checkout=checkout,
            environ=environ,
        ).run()
    finally:
        database.close()


def run_migration(*, settings: Settings, args: argparse.Namespace) -> dict[str, object]:
    required = {
        "source_application_publication_id": args.source_application_publication_id,
        "source_agent_publication_id": args.source_agent_publication_id,
        "target_python_agent_publication_id": args.target_python_agent_publication_id,
        "actor_id": args.actor_id,
        "correlation_id": args.correlation_id,
    }
    missing = sorted(key for key, value in required.items() if not str(value).strip())
    if missing or args.expected_application_revision < 0 or args.expected_deployment_revision < 0:
        return {
            "status": "blocked",
            "write_performed": False,
            "error_code": "retirement_migration_arguments_incomplete",
            "missing_fields": missing,
            "sensitive_values_exposed": False,
        }
    if str(args.target_environment) != settings.environment:
        return {
            "status": "blocked",
            "write_performed": False,
            "error_code": "target_environment_mismatch",
            "target_environment": str(args.target_environment),
            "observed_environment": settings.environment,
            "sensitive_values_exposed": False,
        }
    if args.apply and str(args.confirm_target) != str(args.target_environment):
        return {
            "status": "blocked",
            "write_performed": False,
            "error_code": "retirement_migration_target_confirmation_required",
            "target_environment": str(args.target_environment),
            "sensitive_values_exposed": False,
        }
    container = build_api_container(settings, seed=False)
    try:
        SchemaHeadValidator(container.database, default_migrations_dir()).require_current()
        return container.business_application_service.migrate_retired_typescript_publication(
            actor_id=str(args.actor_id),
            source_application_publication_id=str(args.source_application_publication_id),
            source_agent_publication_id=str(args.source_agent_publication_id),
            target_python_agent_publication_id=str(args.target_python_agent_publication_id),
            environment=str(args.target_environment),
            expected_application_revision=int(args.expected_application_revision),
            expected_deployment_revision=int(args.expected_deployment_revision),
            correlation_id=str(args.correlation_id),
            apply=bool(args.apply),
        )
    except NonRetryableExecutionError as exc:
        return {
            "status": "blocked",
            "write_performed": False,
            "error_code": exc.error_code,
            "safe_message": exc.safe_message,
            "field_errors": exc.field_errors,
            "sensitive_values_exposed": False,
        }
    except Exception as exc:
        return {
            "status": "blocked",
            "write_performed": False,
            "error_code": f"retirement_migration_{type(exc).__name__.lower()}",
            "sensitive_values_exposed": False,
        }
    finally:
        container.database.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings(validate_object_storage=False)
    if args.action == "migrate":
        report = run_migration(settings=settings, args=args)
    else:
        if args.apply:
            report = {
                "status": "blocked",
                "write_performed": False,
                "error_code": "retirement_preflight_is_read_only",
            }
        else:
            report = build_report(
                settings=settings,
                target_environment=args.target_environment,
                expected_environments=args.expected_environment or [args.target_environment],
                checkout=collect_checkout(),
                environ=os.environ,
            )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] in {"ready", "migrated"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
