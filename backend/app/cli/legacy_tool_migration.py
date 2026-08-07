from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from app.bootstrap import build_api_container
from app.modules.internal_tools.application.legacy_job_migration import (
    BuiltinToolLegacyJobMigrator,
)
from app.modules.internal_tools.application.legacy_publication_migration import (
    BuiltinToolLegacyPublicationMigrator,
)
from app.modules.internal_tools.application.legacy_removal_gate import (
    BuiltinToolLegacyRemovalGate,
)
from app.modules.internal_tools.application.legacy_migration import (
    MIGRATION_VERSION,
    BuiltinToolLegacyMigrationService,
)
from app.shared.config import load_settings
from app.shared.database import default_migrations_dir
from app.shared.migrations import SchemaHeadValidator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Report legacy-v1 Built-in Tool references and exact migration "
            "candidate classes without changing data"
        )
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    report = subcommands.add_parser("report")
    report.add_argument("--detail-limit", type=int, default=500)
    migrate_publications = subcommands.add_parser("migrate-publications")
    migrate_publications.add_argument("--actor-id", required=True)
    migrate_publications.add_argument("--correlation-id", required=True)
    migrate_publications.add_argument("--source-limit", type=int, default=500)
    migrate_publications.add_argument(
        "--confirm-migration-version",
        required=True,
        help=f"Must equal {MIGRATION_VERSION}",
    )
    migrate_jobs = subcommands.add_parser("migrate-jobs")
    migrate_jobs.add_argument("--actor-id", required=True)
    migrate_jobs.add_argument("--correlation-id", required=True)
    migrate_jobs.add_argument("--source-limit", type=int, default=500)
    migrate_jobs.add_argument(
        "--confirm-migration-version",
        required=True,
        help=f"Must equal {MIGRATION_VERSION}",
    )
    removal_gate = subcommands.add_parser("observe-removal-gate")
    removal_gate.add_argument("--actor-id", required=True)
    removal_gate.add_argument("--correlation-id", required=True)
    removal_gate.add_argument("--job-id", default="")
    removal_gate.add_argument("--tool-call-id", default="")
    removal_gate.add_argument("--delivery-attempt-id", default="")
    removal_gate.add_argument(
        "--confirm-migration-version",
        required=True,
        help=f"Must equal {MIGRATION_VERSION}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime = build_api_container(load_settings())
    try:
        SchemaHeadValidator(
            runtime.database,
            default_migrations_dir(),
        ).require_current()
        if args.command == "report":
            result = BuiltinToolLegacyMigrationService(runtime.database).report(
                detail_limit=args.detail_limit,
            )
            exit_code = 0
        elif args.command == "migrate-publications":
            if args.confirm_migration_version != MIGRATION_VERSION:
                raise ValueError(
                    f"--confirm-migration-version must equal {MIGRATION_VERSION}"
                )
            result = BuiltinToolLegacyPublicationMigrator(
                runtime.database,
                agent_config_service=runtime.agent_config_service,
                business_application_service=runtime.business_application_service,
            ).migrate(
                actor_id=args.actor_id,
                correlation_id=args.correlation_id,
                source_limit=args.source_limit,
            )
            exit_code = 3 if result["blocked_count"] else 0
        elif args.command == "migrate-jobs":
            if args.confirm_migration_version != MIGRATION_VERSION:
                raise ValueError(
                    f"--confirm-migration-version must equal {MIGRATION_VERSION}"
                )
            result = BuiltinToolLegacyJobMigrator(
                runtime.database,
                snapshot_service=runtime.builtin_tool_snapshot_service,
            ).migrate(
                actor_id=args.actor_id,
                correlation_id=args.correlation_id,
                source_limit=args.source_limit,
            )
            exit_code = 0
        elif args.command == "observe-removal-gate":
            if args.confirm_migration_version != MIGRATION_VERSION:
                raise ValueError(
                    f"--confirm-migration-version must equal {MIGRATION_VERSION}"
                )
            result = BuiltinToolLegacyRemovalGate(
                runtime.database,
                snapshot_service=runtime.builtin_tool_snapshot_service,
            ).observe(
                actor_id=args.actor_id,
                correlation_id=args.correlation_id,
                job_id=args.job_id,
                tool_call_id=args.tool_call_id,
                delivery_attempt_id=args.delivery_attempt_id,
            )
            exit_code = 0 if result["decision"] == "READY" else 3
        else:
            raise ValueError("Unsupported legacy Tool migration command")
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return exit_code
    except ValueError as exc:
        print(
            json.dumps(
                {
                    "error_code": "builtin_tool_legacy_report_invalid",
                    "message": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    except Exception:
        print(
            json.dumps(
                {
                    "error_code": "builtin_tool_legacy_report_failed",
                    "message": "legacy-v1 迁移报告生成失败",
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    finally:
        runtime.database.close()


if __name__ == "__main__":
    raise SystemExit(main())
