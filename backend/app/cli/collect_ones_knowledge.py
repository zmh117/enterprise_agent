"""受管 ONES 全量采集入口；默认停用，单次运行只建立候选。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, NoReturn

from app.modules.knowledge.application.ones_collection_service import KnowledgeOnesCollectionService
from app.modules.knowledge.domain.identity import stable_id
from app.modules.knowledge.domain.normalization import ExportValidationError
from app.modules.knowledge.infrastructure.ones_collection_factory import (
    ManagedOnesCollectionProviderFactory,
)
from app.modules.knowledge.infrastructure.sync_repository import SyncRepository
from app.modules.platform_config.application.secrets import EncryptedDbSecretProvider
from app.modules.platform_config.infrastructure.repository import PlatformConfigRepository
from app.shared.config import load_settings
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import SchemaHeadError, SchemaHeadValidator


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ExportValidationError("knowledge_collection_arguments_invalid")


def emit(event: str, result: dict[str, Any]) -> None:
    print(json.dumps({"event": event, **result}, ensure_ascii=False), flush=True)


def main(argv: list[str] | None = None) -> int:  # noqa: C901, PLR0915
    database = None
    try:
        parser = SafeParser(description="ONES 全量采集：默认关闭，不采评论/附件，不自动发布")
        parser.add_argument(
            "--mode",
            choices=("configure", "status", "enable", "disable", "once", "cancel"),
            default="status",
        )
        parser.add_argument("--binding-code", required=True)
        parser.add_argument("--source-code")
        parser.add_argument("--configuration-file", type=Path)
        parser.add_argument("--expected-revision", type=int)
        parser.add_argument("--run-id")
        parser.add_argument("--commit", action="store_true")
        args = parser.parse_args(argv)
        if args.mode != "status" and not args.commit:
            raise ExportValidationError("knowledge_collection_commit_required")
        settings = load_settings()
        database = Database(settings.database_dsn)
        if database.engine != "postgres":
            raise ExportValidationError("knowledge_collection_postgres_required")
        SchemaHeadValidator(database, default_migrations_dir()).require_current()
        repo = SyncRepository(database)
        binding_id = stable_id("sync-binding", args.binding_code)
        if args.mode == "configure":
            if (
                not args.source_code
                or not args.configuration_file
                or args.expected_revision is None
            ):
                raise ExportValidationError("knowledge_collection_arguments_invalid")
            if (
                args.configuration_file.is_symlink()
                or args.configuration_file.stat().st_size > 64 * 1024
            ):
                raise ExportValidationError("knowledge_collection_configuration_invalid")
            config = json.loads(args.configuration_file.read_text(encoding="utf-8"))
            binding = repo.configure(
                code=args.binding_code,
                source_code=args.source_code,
                configuration=config,
                expected_revision=args.expected_revision,
            )
            emit(
                "knowledge_collection_configured",
                {
                    "binding_id": binding["id"],
                    "revision": binding["configuration_revision"],
                    "enabled": bool(binding["enabled"]),
                },
            )
            return 0
        binding = repo.binding(binding_id)
        if args.mode in {"enable", "disable"}:
            if args.expected_revision is None:
                raise ExportValidationError("knowledge_collection_arguments_invalid")
            binding = repo.set_collection_enabled(
                binding_id,
                enabled=args.mode == "enable",
                expected_revision=args.expected_revision,
            )
        if args.mode == "once":
            secret_provider = EncryptedDbSecretProvider(
                PlatformConfigRepository(database), master_key=settings.app_config_master_key
            )
            factory = ManagedOnesCollectionProviderFactory(
                secret_provider.resolve,
                allowed_hosts=settings.ones_mcp.provider_allowed_hosts,
                app_env=settings.environment,
                allow_insecure_local=settings.ones_mcp.allow_insecure_local,
            )
            result = KnowledgeOnesCollectionService(repo, factory).collect_once(binding_id)
            emit("knowledge_collection_staged", result)
            return 0
        if args.mode == "cancel":
            if not args.run_id:
                raise ExportValidationError("knowledge_collection_arguments_invalid")
            run = repo.run(args.run_id)
            if run["binding_id"] != binding_id:
                raise ExportValidationError("knowledge_collection_scope_changed")
            repo.cancel(args.run_id)
        active = repo.active_collection(binding_id)
        emit(
            "knowledge_collection_status",
            {
                "binding_id": binding_id,
                "revision": binding["configuration_revision"],
                "enabled": bool(binding["enabled"]),
                "interval_seconds": binding["interval_seconds"],
                "active": repo.summary(active["id"]) if active else None,
            },
        )
        return 0
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        code = "knowledge_collection_configuration_invalid"
    except SchemaHeadError:
        code = "knowledge_schema_head_mismatch"
    except ExportValidationError as exc:
        code = exc.code
    except Exception:
        code = "knowledge_collection_failed"
    finally:
        if database is not None:
            database.close()
    emit("knowledge_collection_failed", {"error_code": code})
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
