from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from app.modules.file_workspace.open_test_reset import OpenTestFileDomainResetService
from app.modules.file_workspace.storage import (
    FileObjectStorageSettings,
    MinioFileObjectStorage,
)
from app.modules.platform_config.application.secrets import EncryptedDbSecretProvider
from app.modules.platform_config.infrastructure import PlatformConfigRepository
from app.shared.config import load_settings
from app.shared.database import Database, default_migrations_dir
from app.shared.exceptions import AppError
from app.shared.master_key import load_master_key_settings
from app.shared.migrations import SchemaHeadValidator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Guarded destructive reset for open-test file/Job facts and incompatible "
            "single-contract configuration"
        )
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("report", help="Print redacted counts and an exact inventory digest")
    apply_command = commands.add_parser("apply", help="Delete the exact drained inventory")
    apply_command.add_argument("--expected-digest", required=True)
    apply_command.add_argument("--confirm", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_master_key_settings(load_settings())
    database = Database(settings.database_dsn)
    try:
        SchemaHeadValidator(
            database,
            default_migrations_dir(),
        ).require_current_or_previous(
            allowed_previous_heads=frozenset({"118"}),
        )
        secret_provider = EncryptedDbSecretProvider(
            PlatformConfigRepository(database),
            master_key=settings.app_config_master_key,
        )

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
                secret_provider.resolve,
            )

        service = OpenTestFileDomainResetService(
            database,
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
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())
