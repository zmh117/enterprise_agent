"""文档独立生效的受管同步；批次完成不触发发布。"""

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from datetime import date
from typing import Any, Protocol

from app.modules.knowledge.application.managed_sync_pipeline import ManagedPipelineStore
from app.modules.knowledge.domain.collection_window import check_resumed_range
from app.modules.knowledge.domain.normalization import ExportValidationError
from app.modules.knowledge.domain.vector_contract import VectorError


class IncrementalStore(ManagedPipelineStore, Protocol):
    def source_lock(self, source_id: str) -> AbstractContextManager[None]: ...
    def candidate(self, run_id: str, document_id: str) -> dict[str, Any] | None: ...
    def pending(self, run_id: str) -> Iterator[dict[str, Any]]: ...
    def step(self, candidate: dict[str, Any], step: str, error: str | None = None) -> None: ...
    def finish(self, run_id: str) -> None: ...


class IncrementalSyncPipeline:
    def __init__(
        self,
        repository: IncrementalStore,
        collect_once: Callable[[str], dict[str, Any]],
        process: Callable[[dict[str, Any]], None],
        check_active: Callable[[], None],
    ) -> None:
        self.repository, self.collect_once, self.process, self.check_active = (
            repository,
            collect_once,
            process,
            check_active,
        )

    def run_once(
        self,
        binding_id: str,
        *,
        resume_run_id: str | None = None,
        on_run_selected: Callable[[str], None] | None = None,
        backfill: tuple[date, date] | None = None,
    ) -> dict[str, Any]:
        repo = self.repository
        self.check_active()
        run = repo.run(resume_run_id) if resume_run_id else repo.active_collection(binding_id)
        if run is not None:
            if run["binding_id"] != binding_id or run["incremental"] != 1:
                raise ExportValidationError("knowledge_sync_migration_required")
            check_resumed_range(run, backfill)
            repo.assert_configuration(run)
            if run["phase"] == "CANCELLED":
                raise ExportValidationError("knowledge_sync_cancelled")
        if run is None or run["phase"] == "COLLECTING":
            result = self.collect_once(binding_id)
            run = repo.run(result["run_id"])
        if on_run_selected is not None:
            on_run_selected(run["id"])
        if run["phase"] == "ACTIVATED":
            return repo.summary(run["id"])
        with repo.source_lock(run["source_id"]):
            repo.assert_configuration(repo.run(run["id"]))
            if run["phase"] == "STAGED":
                repo.advance(run["id"], expected_phase="STAGED", phase="CHUNKING")
            failed = False
            for candidate in repo.pending(run["id"]):
                self.check_active()
                try:
                    self.process(candidate)
                except (VectorError, ExportValidationError) as exc:
                    if exc.code in {
                        "knowledge_sync_cancelled",
                        "knowledge_collection_disabled",
                        "knowledge_sync_configuration_changed",
                        "knowledge_sync_resource_profile_changed",
                        "knowledge_sync_migration_required",
                    }:
                        raise
                    stored = repo.candidate(run["id"], candidate["document_id"]) or candidate
                    repo.step(stored, stored["processing_step"], exc.code)
                    failed = True
            if failed:
                repo.fail(run["id"], "knowledge_sync_partial")
                return repo.summary(run["id"])
            current = repo.run(run["id"])
            for before, after in (("CHUNKING", "INDEXING"), ("INDEXING", "VERIFIED")):
                if current["phase"] == before:
                    repo.advance(run["id"], expected_phase=before, phase=after)
                    current = repo.run(run["id"])
            repo.finish(run["id"])
            return repo.summary(run["id"])
