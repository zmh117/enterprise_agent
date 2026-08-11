from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
from collections.abc import Sequence

from app.shared.config import load_settings
from app.shared.database import Database, default_migrations_dir
from app.shared.schema_consolidation import (
    SchemaConsolidationError,
    SchemaConsolidationPreflight,
    SessionJobMessageBackfill,
    WorkflowGraphBackfill,
    expected_head_from_manifest,
    require_write_authorization,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Dry-run-first, content-safe schema consolidation operations"
    )
    parser.add_argument(
        "action",
        choices=("preflight", "backfill-session-job-message", "backfill-workflow"),
    )
    parser.add_argument(
        "--expected-head",
        default="",
        help="Exact migration head required for this stage",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--target-label",
        default=os.getenv("SCHEMA_CONSOLIDATION_TARGET_LABEL", ""),
        help="Non-secret environment label configured by the operator",
    )
    parser.add_argument("--confirm-target", default="")
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--after-id", default="")
    parser.add_argument("--after-session-id", default="")
    parser.add_argument("--after-job-id", default="")
    parser.add_argument("--limit", type=int, default=100)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    expected_head = str(args.expected_head) or expected_head_from_manifest(
        phase="preflight" if args.action == "preflight" else "backfill"
    )
    database = Database(load_settings().database_dsn)
    try:
        preflight = SchemaConsolidationPreflight(
            database,
            default_migrations_dir(),
        ).run(expected_head=expected_head)
        if args.action == "preflight":
            if args.apply:
                raise SchemaConsolidationError("Preflight is always read-only")
            report = preflight
        else:
            if (
                preflight["migration"]["status"] != "current"
                or str(preflight["migration"]["current_head"]) != expected_head
            ):
                raise SchemaConsolidationError(
                    "Schema backfill requires the exact expected migration head"
                )
            authorization = require_write_authorization(
                apply=bool(args.apply),
                phase="backfill",
                expected_head=expected_head,
                actual_head=str(preflight["migration"]["current_head"]),
                target_label=str(args.target_label),
                confirmed_target=str(args.confirm_target),
                evidence_directory=args.evidence_dir,
                repository_root=Path(__file__).resolve().parents[3],
            )
            if args.action == "backfill-workflow":
                report = WorkflowGraphBackfill(database).run(
                    apply=bool(args.apply),
                    after_id=str(args.after_id),
                    limit=int(args.limit),
                )
                evidence_scope = "workflow"
            else:
                report = SessionJobMessageBackfill(database).run(
                    apply=bool(args.apply),
                    after_session_id=str(args.after_session_id),
                    after_job_id=str(args.after_job_id),
                    limit=int(args.limit),
                )
                evidence_scope = "session-job-message"
            if authorization is not None:
                timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
                evidence_path = (
                    authorization.evidence_directory
                    / f"schema-consolidation-{evidence_scope}-{timestamp}.json"
                )
                evidence_path.write_text(
                    json.dumps(
                        {
                            "phase": authorization.phase,
                            "expected_head": authorization.expected_head,
                            "target_label": authorization.target_label,
                            "report": report,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    encoding="utf-8",
                )
    except SchemaConsolidationError as exc:
        print(f"SCHEMA_CONSOLIDATION_PREFLIGHT_FAILED: {exc}")
        return 1
    except Exception:
        print(
            "SCHEMA_CONSOLIDATION_PREFLIGHT_FAILED: "
            "database unavailable or safe verification failed"
        )
        return 1
    finally:
        database.close()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0 if report["status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
