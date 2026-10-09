"""可选 ONES 知识同步入口；默认关闭，状态仅输出安全计数。"""

from __future__ import annotations

import argparse
from contextlib import suppress
from datetime import UTC, datetime
import json
import os
from pathlib import Path
from threading import Event
from typing import Any, NoReturn

from app.cli.knowledge_database_recovery import (
    RecoveryCheckpoint,
    database_error,
    recover_database,
    stop_signals,
)
from app.bootstrap import build_api_container
from app.modules.knowledge.application.managed_sync_activation import ManagedSyncActivation
from app.modules.knowledge.application.managed_sync_pipeline import ManagedSyncPipeline
from app.modules.knowledge.application.ones_collection_service import KnowledgeOnesCollectionService
from app.modules.knowledge.domain.governance import KnowledgeGovernanceError
from app.modules.knowledge.domain.identity import stable_id
from app.modules.knowledge.domain.normalization import ExportValidationError
from app.modules.knowledge.domain.vector_contract import VectorError
from app.modules.knowledge.infrastructure.candidate_corpus import CandidateVectorRepository
from app.modules.knowledge.infrastructure.managed_activation_repository import (
    ManagedActivationRepository,
)
from app.modules.knowledge.infrastructure.managed_sync_steps import ManagedSyncSteps
from app.modules.knowledge.infrastructure.ones_collection_factory import (
    ManagedOnesCollectionProviderFactory,
)
from app.modules.platform_config.application.secrets import EncryptedDbSecretProvider
from app.modules.platform_config.infrastructure.repository import PlatformConfigRepository
from app.shared.config import Settings, load_settings
from app.shared.database import Database, default_migrations_dir
from app.shared.master_key import MasterKeyConfigurationError, load_master_key_settings
from app.shared.migrations import SchemaHeadError, SchemaHeadValidator
from app.modules.knowledge.infrastructure.vector_clients import EmbeddingClient, QdrantClient


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ExportValidationError("knowledge_sync_arguments_invalid")


def emit(event: str, value: dict[str, Any]) -> None:
    print(json.dumps({"event": event, **value}, ensure_ascii=False, default=str), flush=True)


def execute_pipeline(
    repository: ManagedActivationRepository,
    binding_id: str,
    pipeline: ManagedSyncPipeline,
    *,
    scheduled: bool,
    checkpoint: RecoveryCheckpoint | None = None,
) -> dict[str, Any] | None:
    """整轮只允许一个写者；拿到锁后重查时钟，合并同一到期 tick。"""
    with repository.source_lock(stable_id("sync-worker", binding_id)):
        if (
            scheduled
            and not (checkpoint and checkpoint.run_id)
            and not repository.scheduled_due(binding_id, datetime.now(UTC))
        ):
            return None
        if checkpoint is None:
            return pipeline.run_once(binding_id)
        return pipeline.run_once(
            binding_id,
            resume_run_id=checkpoint.run_id,
            on_run_selected=checkpoint.select_run,
        )


def _execute(  # noqa: C901, PLR0915
    args: argparse.Namespace, settings: Settings, stop: Event, checkpoint: RecoveryCheckpoint
) -> int:
    database = embedding = qdrant = None
    try:
        database = Database(settings.database_dsn)
        if database.engine != "postgres":
            raise ExportValidationError("knowledge_sync_postgres_required")
        SchemaHeadValidator(database, default_migrations_dir()).require_current()
        checkpoint.database_verified = True
        binding_id = stable_id("sync-binding", args.binding_code)
        repo = ManagedActivationRepository(database)
        if args.mode == "status":
            binding = repo.binding(binding_id)
            active = repo.active_run(binding_id)
            emit(
                "knowledge_sync_status",
                {
                    "binding_id": binding_id,
                    "revision": binding["configuration_revision"],
                    "enabled": bool(binding["enabled"]),
                    "interval_seconds": binding["interval_seconds"],
                    "next_run_at": binding["next_run_at"],
                    "active": repo.summary(active["id"]) if active else None,
                },
            )
            return 0
        database.close()
        runtime = build_api_container(settings, seed=False)
        database = runtime.database
        if runtime.knowledge_services is None:
            raise ExportValidationError("knowledge_sync_verifier_unavailable")
        repo = ManagedActivationRepository(database)
        checkpoint.check_binding(repo.binding(binding_id))
        embedding, qdrant = EmbeddingClient(), QdrantClient()
        resources = runtime.knowledge_services.resources()
        resources.embedding, resources.qdrant = embedding, qdrant
        steps = ManagedSyncSteps(
            database,
            embedding,
            qdrant,
            args.capacity_path,
        )
        steps.capacity.check(0)
        steps.cancelled = stop.is_set
        secret_provider = EncryptedDbSecretProvider(
            PlatformConfigRepository(database), master_key=settings.app_config_master_key
        )
        provider_factory = ManagedOnesCollectionProviderFactory(
            secret_provider.resolve,
            allowed_hosts=settings.ones_mcp.provider_allowed_hosts,
            app_env=settings.environment,
            allow_insecure_local=settings.ones_mcp.allow_insecure_local,
        )
        collector = KnowledgeOnesCollectionService(repo, provider_factory, cancelled=stop.is_set)

        def check_active() -> None:
            if stop.is_set():
                raise ExportValidationError("knowledge_sync_cancelled")
            if repo.binding(binding_id)["enabled"] != 1:
                raise ExportValidationError("knowledge_collection_disabled")

        def collect(code: str) -> dict[str, Any]:
            return collector.collect_once(
                code,
                resume_run_id=checkpoint.run_id,
                on_run_selected=checkpoint.select_run,
                on_run_started=(
                    lambda run_id: (
                        repo.scheduled_started(code, run_id, datetime.now(UTC))
                        if args.mode == "daemon"
                        else None
                    )
                ),
            )

        pipeline = ManagedSyncPipeline(
            repo,
            collect_once=collect,
            chunk_base=steps.chunk,
            index_base=steps.index,
            activate=lambda run_id: ManagedSyncActivation(
                repo,
                resources,
                CandidateVectorRepository(database, run_id),
                check_active=check_active,
            ).run(run_id),
        )
        if args.mode == "once":
            completed = execute_pipeline(
                repo, binding_id, pipeline, scheduled=False, checkpoint=checkpoint
            )
            assert completed is not None
            emit("knowledge_sync_completed", completed)
            return 0
        while not stop.is_set():
            binding = repo.binding(binding_id)
            if binding["enabled"] != 1:
                active = repo.active_run(binding_id)
                if active is not None:
                    repo.cancel(active["id"])
                return 0
            if checkpoint.run_id is not None or repo.scheduled_due(binding_id, datetime.now(UTC)):
                try:
                    completed = execute_pipeline(
                        repo, binding_id, pipeline, scheduled=True, checkpoint=checkpoint
                    )
                    if completed is not None:
                        emit("knowledge_sync_completed", completed)
                        checkpoint.run_id = None
                except (ExportValidationError, VectorError, KnowledgeGovernanceError) as exc:
                    if database_error(exc) is not None:
                        raise
                    code = getattr(exc, "code", getattr(exc, "error_code", "knowledge_sync_failed"))
                    if code not in {
                        "knowledge_collection_provider_unavailable",
                        "knowledge_collection_rate_limited",
                        "knowledge_embedding_busy",
                        "knowledge_embedding_unavailable",
                        "knowledge_embedding_read_timeout",
                        "knowledge_vector_unavailable",
                        "knowledge_vector_timeout",
                    }:
                        raise
                    emit(
                        "knowledge_sync_retry_pending",
                        {
                            "error_code": getattr(
                                exc, "code", getattr(exc, "error_code", "knowledge_sync_failed")
                            )
                        },
                    )
                    for _ in range(10):
                        if stop.is_set() or repo.binding(binding_id)["enabled"] != 1:
                            break
                        stop.wait(30)
                    continue
            stop.wait(30)
        return 0
    finally:
        if embedding is not None:
            with suppress(Exception):
                embedding.http.close()
        if qdrant is not None:
            with suppress(Exception):
                qdrant.http.close()
        if database is not None:
            with suppress(Exception):
                database.close()


def main(argv: list[str] | None = None) -> int:
    try:
        parser = SafeParser(description="受管 ONES 知识同步；默认停用且不首次发布或授权")
        parser.add_argument("--mode", choices=("status", "once", "daemon"), default="status")
        parser.add_argument("--binding-code", required=True)
        parser.add_argument("--capacity-path", type=Path)
        parser.add_argument("--commit", action="store_true")
        args = parser.parse_args(argv)
        if args.mode != "status" and (not args.commit or args.capacity_path is None):
            raise ExportValidationError("knowledge_sync_commit_required")
        if args.mode == "daemon" and os.environ.get("KNOWLEDGE_SYNC_ENABLED") != "true":
            raise ExportValidationError("knowledge_sync_worker_disabled")
        settings = load_settings()
        stop, checkpoint = Event(), RecoveryCheckpoint()
        if args.mode == "status":
            return _execute(args, settings, stop, checkpoint)
        settings = load_master_key_settings(settings)
        with stop_signals(stop):
            return recover_database(
                lambda: _execute(args, settings, stop, checkpoint),
                dsn=settings.database_dsn,
                stop=stop,
                emit=emit,
                prefix="knowledge_sync",
                previously_connected=lambda: checkpoint.database_verified,
            )
    except MasterKeyConfigurationError:
        code = "knowledge_sync_master_key_unavailable"
    except SchemaHeadError:
        code = "knowledge_schema_head_mismatch"
    except (ExportValidationError, VectorError) as exc:
        if exc.code == "knowledge_sync_cancelled":
            emit("knowledge_sync_stopped", {"error_code": exc.code})
            return 0
        code = exc.code
    except KnowledgeGovernanceError as exc:
        code = exc.error_code
    except Exception:
        code = "knowledge_sync_failed"
    emit("knowledge_sync_failed", {"error_code": code})
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
