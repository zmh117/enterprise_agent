from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from app.bootstrap import build_worker_container
from app.modules.file_workspace.open_test_reset import OpenTestFileDomainResetService
from app.modules.file_workspace.storage import (
    FileObjectStorageSettings,
    MinioFileObjectStorage,
)
from app.shared.config import load_settings
from app.shared.exceptions import AppError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Guarded destructive reset for open-test file and Job facts"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("report", help="Print redacted counts and an exact inventory digest")
    apply_command = commands.add_parser("apply", help="Delete the exact drained inventory")
    apply_command.add_argument("--expected-digest", required=True)
    apply_command.add_argument("--confirm", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings()
    runtime = build_worker_container(
        settings,
        seed=False,
        service_name="file-service",
    )
    settings = runtime.settings

    def storage(bucket: str) -> MinioFileObjectStorage:
        return MinioFileObjectStorage(
            FileObjectStorageSettings(
                endpoint_url=settings.file_service.endpoint_url,
                bucket=bucket,
                access_key_ref=settings.file_service.access_key_ref,
                secret_key_ref=settings.file_service.secret_key_ref,
                region=settings.file_service.region,
                secure=settings.file_service.secure,
            ),
            runtime.platform_config_service.resolve_secret,
        )

    try:
        service = OpenTestFileDomainResetService(
            runtime.database,
            storage(settings.file_service.bucket),
            storage(settings.file_service.legacy_attachment_bucket),
        )
        result = (
            service.report()
            if args.command == "report"
            else service.apply(
                expected_digest=args.expected_digest,
                confirmation=args.confirm,
            )
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except AppError as exc:
        print(
            json.dumps(
                {"error_code": exc.error_code, "message": exc.safe_message},
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
                    "error_code": "open_test_file_domain_reset_failed",
                    "message": "开放测试文件域重置失败",
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
