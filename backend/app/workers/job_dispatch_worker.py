from __future__ import annotations

import logging
import time
import os
from threading import Thread
from pathlib import Path

from app.bootstrap import build_worker_container
from app.shared.config import load_settings
from app.shared.logging import configure_logging
from app.modules.agent.infrastructure.runtime_pool_recovery import reconcile_runtime_nodes
from app.modules.knowledge.infrastructure.code_build_controller import CodeBuildController
from app.modules.knowledge.infrastructure.code_indexing import CodeSnapshotIndexer
from app.modules.knowledge.infrastructure.vector_clients import EmbeddingClient, QdrantClient
from app.modules.knowledge.infrastructure.code_extraction_jobs import (
    CodeArtifactCollector,
    CodeExtractionJobs,
)


logger = logging.getLogger(__name__)
HEARTBEAT_PATH = Path("/tmp/job-dispatch-worker.heartbeat")


def _code_build_loop(controller: CodeBuildController) -> None:
    # Source verification/index I/O must not stall ordinary outbox delivery or
    # its health heartbeat. One thread per Worker; source fencing is persisted.
    while True:
        try:
            controller.tick()
        except Exception:
            logger.warning("Code knowledge build scan unavailable")
        time.sleep(5)


def main() -> None:
    configure_logging()
    settings = load_settings()
    container = build_worker_container(
        settings,
        seed=settings.seed_local_config,
        service_name="job-dispatch-worker",
    )
    settings = container.settings
    code_controller = None
    if os.environ.get("CODE_KNOWLEDGE_WORKER_ENABLED") == "true":
        if container.code_source_grant is None:
            raise RuntimeError("code_source_grant_unconfigured")
        source_root = Path(
            os.environ.get("CODE_SOURCE_SNAPSHOT_ROOT", "/var/lib/code-knowledge/sources")
        )
        code_controller = CodeBuildController(
            container.database,
            CodeExtractionJobs(container.database, container.create_agent_job_service),
            CodeArtifactCollector(
                container.database,
                container.code_source_grant,
                source_root=source_root,
                artifact_root=Path(
                    os.environ.get(
                        "CODE_EXTRACTION_ARTIFACT_ROOT", "/var/lib/code-knowledge/artifacts"
                    )
                ),
            ),
            source_root=source_root,
            indexer=CodeSnapshotIndexer(container.database, EmbeddingClient(), QdrantClient()),
        )
    if code_controller is not None:
        Thread(
            target=_code_build_loop, args=(code_controller,), name="code-builds", daemon=True
        ).start()
    logger.info("Job dispatch outbox worker starting")
    while True:
        try:
            HEARTBEAT_PATH.touch()
            reconcile_runtime_nodes(settings.agent_runtime, container.database)
            result = container.job_dispatcher.publish_pending(limit=100)
            if (
                result.published
                or result.failed
                or result.dead
                or result.recovered
                or result.expired
            ):
                logger.info(
                    "Job dispatch outbox scan "
                    "published=%s failed=%s dead=%s recovered=%s expired=%s",
                    result.published,
                    result.failed,
                    result.dead,
                    result.recovered,
                    result.expired,
                )
        except Exception:
            logger.exception("Job dispatch outbox scan failed")
        finally:
            HEARTBEAT_PATH.touch()
        time.sleep(max(settings.queue.dispatch_outbox_scan_seconds, 1))


if __name__ == "__main__":
    main()
